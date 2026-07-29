import asyncio
import logging

import aiohttp

import config

log = logging.getLogger("openrouter")

MAX_TRIES = 3
RETRY_WAIT = 3.0

HEADERS = {"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"}


class GenerationError(Exception):
    pass


async def _request(session, json_body, timeout=30):
    last_exc = None
    url = f"{config.OPENROUTER_BASE}/chat/completions"
    for attempt in range(1, MAX_TRIES + 1):
        try:
            async with session.post(
                url, json=json_body, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as r:
                data = await r.json()
                if r.status >= 400:
                    last_exc = GenerationError(f"HTTP {r.status}: {str(data)[:300]}")
                else:
                    return data
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            last_exc = e
        log.warning("OpenRouter attempt %d/%d failed: %s", attempt, MAX_TRIES, last_exc)
        if attempt < MAX_TRIES:
            await asyncio.sleep(RETRY_WAIT)
    raise GenerationError(f"OpenRouter запрос не удался: {last_exc}")


def _extract_text(data):
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        content = ""
    if "</think>" in content:
        content = content.split("</think>")[-1]
    return content.strip()


async def chat(session, system_prompt, user_message, model=None):
    body = {
        "model": model or config.SUPPORT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }
    data = await _request(session, body, timeout=30)
    return _extract_text(data)
