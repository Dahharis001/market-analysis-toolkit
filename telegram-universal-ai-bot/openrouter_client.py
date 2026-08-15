"""Thin generic client for OpenRouter's three APIs (chat, image, video) - no
renovation-specific logic here, just plain pass-through calls so bot.py can point
any of them at whatever model the user picked from the menu.

NOTE: outbound access to openrouter.ai is blocked from the sandbox this was
written in, so the video/image model slugs in bot.py's catalogs are taken from
public docs/announcements and were not smoke-tested live. If a model returns a
404 ("No endpoints found for X") or a schema error, check openrouter.ai/models
for the exact current slug and fix the one entry in bot.py - same class of issue
already hit and fixed in the sibling telegram-renovation-bot project.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import time

import requests

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


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


def save_data_uri(data_uri: str, out_path: str) -> None:
    _, b64 = data_uri.split(",", 1)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(b64))


def chat_completion(api_key: str, model: str, history: list[dict]) -> str:
    resp = requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers=_headers(api_key),
        json={"model": model, "messages": history},
        timeout=120,
    )
    if resp.status_code >= 400:
        raise OpenRouterError(f"Chat completion failed ({resp.status_code}): {resp.text[:500]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def generate_image(api_key: str, model: str, prompt: str, reference_data_uri: str | None = None) -> str:
    content: list[dict] = [{"type": "text", "text": prompt}]
    if reference_data_uri:
        content.append({"type": "image_url", "image_url": {"url": reference_data_uri}})

    resp = requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers=_headers(api_key),
        json={
            "model": model,
            "messages": [{"role": "user", "content": content}],
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
    api_key: str, model: str, prompt: str, *, image: str | None = None,
    duration: int = 5, aspect_ratio: str = "9:16",
) -> str:
    body = {"model": model, "prompt": prompt, "duration": duration, "aspect_ratio": aspect_ratio}
    if image:
        body["image"] = image

    resp = requests.post(f"{OPENROUTER_BASE}/videos", headers=_headers(api_key), json=body, timeout=60)
    if resp.status_code >= 400:
        raise OpenRouterError(f"Video job creation failed ({resp.status_code}): {resp.text[:800]}")
    data = resp.json()
    job_id = data.get("id") or data.get("job_id") or data.get("data", {}).get("id")
    if not job_id:
        raise OpenRouterError(f"Could not find a job id in the response: {data}")
    return job_id


def poll_video_job(api_key: str, job_id: str, *, timeout_sec: int = 900, interval_sec: int = 8) -> str:
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
    headers = _headers(api_key) if api_key else {}
    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
