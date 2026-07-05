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
    " Строго без людей: ни одного человека, лица, руки, силуэта или рабочего в кадре "
    "ни на одном этапе - только пустое помещение и материалы/инструменты сами по себе."
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
    """Ask a vision-capable chat model to reverse-engineer renovation stages from the final photo."""
    system = (
        "Ты — режиссёр и дизайнер интерьеров, который придумывает промпты для text/image-to-video "
        "генерации кинематографичного таймлапса ремонта. Всегда отвечай СТРОГО валидным JSON-массивом "
        "строк, без markdown-обёртки и без пояснений."
    )
    user_text = (
        f"На фото — готовый интерьер ванной комнаты (финальный результат ремонта). "
        f"Придумай ровно {num_stages} промптов на русском языке — по одному на каждый этап ремонта "
        f"именно этой ванной, от голых бетонных стен до состояния как на фото.\n\n"
        f"Требования к каждому промпту:\n"
        f"- Один и тот же неподвижный ракурс камеры, совпадающий с фото; без людей и без летающих "
        f"инструментов в кадре.\n"
        f"- Стиль: {style_notes}.\n"
        f"- Этапы идут в логичном порядке: черновая коробка -> инженерные коммуникации -> "
        f"гидроизоляция/стяжка/штукатурка -> облицовка стен и пола -> потолок и освещение -> "
        f"монтаж сантехники и мебели -> финальная уборка со включением света.\n"
        f"- Последний промпт должен точно описывать то, что видно на референсном фото, включая "
        f"освещение и положение всех предметов.\n"
        f"- Каждый промпт — самодостаточное описание для генератора фото и видео (2-4 предложения), "
        f"фотореализм, 4K.\n\n"
        f"Верни JSON-массив ровно из {num_stages} строк и ничего больше."
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
                        {"type": "text", "text": prompt + NO_PEOPLE_SUFFIX},
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
        "prompt": prompt + NO_PEOPLE_SUFFIX,
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
            url = (
                data.get("url")
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


def download_file(url: str, dest_path: str) -> None:
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
