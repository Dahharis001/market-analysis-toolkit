"""Thin client for the three OpenRouter APIs this bot needs:

1. Chat completions (stable, documented, OpenAI-compatible) - used to look at the
   reference photo and write the per-stage renovation prompts.
2. Image generation via chat completions with modalities=["image","text"] - used to
   render one still image per stage, anchored on the reference photo (image-to-image
   edit), before any video is generated.
3. Video generation (POST /api/v1/videos, GET /api/v1/videos/{id}) - used to turn
   each stage into a video clip, keyframed between that stage's image and the next.

NOTE on the video generation field names: outbound access to openrouter.ai was
blocked by this sandbox's network policy while this file was written, so the
exact request/response schema could not be smoke-tested live. Field names below
(`image`, `last_frame_image`, `duration`, `aspect_ratio`, `resolution`,
`generate_audio`) are taken from OpenRouter's public announcement and docs
summaries. Before running a full multi-stage batch, run a single cheap test
clip first (see README) - if the API rejects a field, the error body is printed
in full and the only fix needed is renaming that field here.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import time

import requests

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Appended to every image/video generation prompt as a hard constraint, independent
# of whatever the stage-prompt LLM wrote - this is the single most important
# requirement for this bot: no people anywhere in the renovation stages.
NO_PEOPLE_SUFFIX = (
    " Strictly no people: not a single person, face, hand, silhouette, or worker in frame at "
    "any stage - only the empty room and materials/tools by themselves."
)

# Appended alongside NO_PEOPLE_SUFFIX to stop the image/video model from inventing or
# moving architectural elements (a common failure mode: adding a window that isn't in
# the real photo, moving a door, changing the room's proportions).
STRUCTURE_LOCK_SUFFIX = (
    " Keep the exact same room architecture as the original reference photo: same walls, same "
    "window and door positions and sizes, same room shape and proportions. Do not add, remove, "
    "resize, or move any window, door, or wall - only surface finishes and contents change."
)


class OpenRouterError(RuntimeError):
    pass


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def image_to_data_uri(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/jpeg"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _parse_json_string_array(content: str, expected: int) -> list[str]:
    match = re.search(r"\[.*\]", content, re.DOTALL)
    raw = match.group(0) if match else content
    stages = json.loads(raw)
    if not isinstance(stages, list) or not all(isinstance(s, str) for s in stages):
        raise OpenRouterError(f"Model did not return a JSON array of strings: {content[:300]}")
    if len(stages) != expected:
        # Model miscounted - trim or accept what we got rather than failing the whole run.
        stages = stages[:expected] if len(stages) > expected else stages
    return stages


def generate_stage_prompts(
    api_key: str, model: str, image_data_uri: str, num_stages: int, style_notes: str
) -> list[str]:
    """Ask a vision-capable chat model to reverse-engineer renovation stages from the final photo.

    Works for any room type (bathroom, bedroom, kitchen, living room, etc.) - the model
    first identifies the room from the photo, then writes a construction sequence
    appropriate to that specific room (a bedroom has no plumbing/waterproofing stage,
    a kitchen or bathroom does, etc.) instead of a fixed bathroom-only checklist.
    """
    system = (
        "You are a director writing short, punchy prompts in English for text/image-to-video "
        "renovation timelapse generation, for ANY room type (bathroom, bedroom, kitchen, living "
        "room, office, etc.). Always reply with a STRICTLY valid JSON array of strings, in "
        "English, no markdown, no explanation."
    )
    user_text = (
        f"The photo shows a finished room (the final renovation result). First figure out what "
        f"type of room this is and what work it realistically needs (a bedroom/living room has no "
        f"plumbing or waterproofing stage, just walls/floor/furniture/decor; a bathroom/kitchen has "
        f"plumbing, waterproofing, tiling, etc.).\n\n"
        f"Write exactly {num_stages} prompts in English, one per renovation stage of THIS SPECIFIC "
        f"room, from a bare concrete shell to the exact state shown in the photo.\n\n"
        f"Match this style and structure for every prompt (real example for a bathroom - adapt the "
        f"materials/objects to whatever room type you detected, keep the same terse cinematic "
        f"tone):\n"
        f'"Fixed camera, narrow empty bathroom, bare concrete shell, rough grey block walls, '
        f'exposed concrete slab floor, dust particles in the air, no people, timelapse, '
        f'photorealistic, static wide angle shot."\n'
        f'"Fixed camera, same bathroom, large-format dark tiles appearing on the walls one by '
        f'one, floor tiles covering piece by piece, no people, smooth timelapse assembly, '
        f'photorealistic."\n\n'
        f"Requirements for every prompt:\n"
        f'- Start with "Fixed camera, same [room]" (except stage 1) so the shot stays locked.\n'
        f"- Keep the exact same room architecture as the photo: same walls, same window and door "
        f"positions, same room shape and size - never add, remove, resize, or move any window, "
        f"door, or wall. Only surface finishes and contents change, never the structure.\n"
        f"- No people, no floating tools, no hands in frame, ever.\n"
        f"- Style: {style_notes}.\n"
        f"- Stages follow a logical order for this room type: bare concrete shell -> utilities "
        f"relevant to this room (electrical; plus plumbing/waterproofing only if it's a "
        f"bathroom/kitchen) -> screed and plastering -> wall/floor finishing materials appropriate "
        f"to this room type -> ceiling and lighting -> furniture/fixtures/appliances appropriate to "
        f"this room -> final cleanup with the lights turning on.\n"
        f"- Stage 1 must explicitly and aggressively strip away every finished material from the "
        f'photo: no tile, no fixtures, no furniture, no finished ceiling or decorative lighting - '
        f'bare unfinished concrete only, formwork marks, dust. State this explicitly (e.g. "all '
        f'tile and fixtures removed, bare concrete walls and floor") or the image generator will '
        f"leave the room looking nearly finished.\n"
        f"- Every later stage adds EXACTLY ONE layer of work on top of the previous stage and must "
        f"not contain finish materials/furniture that belong to a later stage - no jumping ahead. "
        f"The difference between consecutive stages must be visually obvious.\n"
        f"- The last prompt must precisely match what's visible in the reference photo, including "
        f"lighting and the position of every object.\n"
        f"- Each prompt is a self-contained 2-4 sentence description for a photo/video generator, "
        f"photorealistic, 4K.\n\n"
        f"Return a JSON array of exactly {num_stages} strings and nothing else."
    )
    resp = requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers=_headers(api_key),
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_data_uri}},
                    ],
                },
            ],
            "temperature": 0.8,
        },
        timeout=120,
    )
    if resp.status_code >= 400:
        raise OpenRouterError(f"Chat completion failed ({resp.status_code}): {resp.text[:500]}")
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return _parse_json_string_array(content, num_stages)


def generate_stage_image(api_key: str, model: str, prompt: str, reference_image_data_uri: str) -> str:
    """Image-edit the reference photo into an earlier renovation stage.

    Uses OpenRouter's unified image API convention: a normal /chat/completions
    request with modalities=["image","text"]; the generated image comes back as a
    data URI in choices[0].message.images[0].image_url.url.
    """
    resp = requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers=_headers(api_key),
        json={
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt + NO_PEOPLE_SUFFIX + STRUCTURE_LOCK_SUFFIX},
                        {"type": "image_url", "image_url": {"url": reference_image_data_uri}},
                    ],
                }
            ],
            "modalities": ["image", "text"],
        },
        timeout=180,
    )
    if resp.status_code >= 400:
        raise OpenRouterError(f"Image generation failed ({resp.status_code}): {resp.text[:800]}")
    data = resp.json()
    images = (data["choices"][0]["message"].get("images")) or []
    if not images:
        raise OpenRouterError(f"Model did not return an image: {json.dumps(data)[:500]}")
    return images[0]["image_url"]["url"]


def create_video_job(
    api_key: str,
    model: str,
    prompt: str,
    *,
    duration: int,
    aspect_ratio: str,
    resolution: str,
    generate_audio: bool,
    first_frame: str | None = None,
    last_frame: str | None = None,
    seed: int | None = None,
) -> str:
    """Submit a video generation job, return its job id."""
    body = {
        "model": model,
        "prompt": prompt + NO_PEOPLE_SUFFIX + STRUCTURE_LOCK_SUFFIX,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "generate_audio": generate_audio,
    }
    if first_frame:
        body["image"] = first_frame
    if last_frame:
        body["last_frame_image"] = last_frame
    if seed is not None:
        body["seed"] = seed

    resp = requests.post(f"{OPENROUTER_BASE}/videos", headers=_headers(api_key), json=body, timeout=60)
    if resp.status_code >= 400:
        raise OpenRouterError(f"Video job creation failed ({resp.status_code}): {resp.text[:800]}")
    data = resp.json()
    job_id = data.get("id") or data.get("job_id") or data.get("data", {}).get("id")
    if not job_id:
        raise OpenRouterError(f"Could not find a job id in the response: {data}")
    return job_id


def poll_video_job(api_key: str, job_id: str, *, timeout_sec: int = 900, interval_sec: int = 8) -> str:
    """Poll until the job completes; return the final video URL."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        resp = requests.get(f"{OPENROUTER_BASE}/videos/{job_id}", headers=_headers(api_key), timeout=30)
        if resp.status_code >= 400:
            raise OpenRouterError(f"Status check failed ({resp.status_code}): {resp.text[:500]}")
        data = resp.json()
        status = data.get("status") or data.get("data", {}).get("status")
        if status in ("completed", "succeeded"):
            unsigned_urls = data.get("unsigned_urls") or []
            url = (
                (unsigned_urls[0] if unsigned_urls else None)
                or data.get("url")
                or data.get("video_url")
                or (data.get("output") or {}).get("url")
                or (data.get("data") or {}).get("url")
            )
            if not url:
                raise OpenRouterError(f"Job completed but no video URL found in response: {data}")
            return url
        if status in ("failed", "error"):
            raise OpenRouterError(f"Video generation failed: {data.get('error') or data}")
        time.sleep(interval_sec)
    raise OpenRouterError(f"Timed out waiting for video job {job_id}")


def download_file(url: str, dest_path: str, api_key: str | None = None) -> None:
    # OpenRouter's video content URLs (unsigned_urls) are API endpoints, not public
    # CDN links - they need the same Authorization header as everything else.
    headers = _headers(api_key) if api_key else {}
    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
