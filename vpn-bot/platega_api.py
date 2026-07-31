import asyncio
import logging

import aiohttp

import config

log = logging.getLogger("platega")

HEADERS = {
    "X-MerchantId": config.PLATEGA_MERCHANT_ID,
    "X-Secret": config.PLATEGA_SECRET,
    "Content-Type": "application/json",
}

MAX_TRIES = 4
RETRY_WAIT = 3.0

# https://docs.platega.io/ payment method IDs
METHOD_SBP = 2
METHOD_CARD = 11
METHOD_CRYPTO = 13


async def _request(session, method, url, *, json_body=None, timeout=30):
    last_exc = None
    for attempt in range(1, MAX_TRIES + 1):
        try:
            async with session.request(
                method, url, json=json_body, headers=HEADERS,
                proxy=config.OUTBOUND_PROXY, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as r:
                data = await r.json()
                if r.status >= 400:
                    last_exc = RuntimeError(f"HTTP {r.status}: {data}")
                else:
                    return data
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            last_exc = e
        log.warning("Platega %s attempt %d/%d failed: %s", url, attempt, MAX_TRIES, last_exc)
        if attempt < MAX_TRIES:
            await asyncio.sleep(RETRY_WAIT)
    raise RuntimeError(f"Platega запрос не удался: {last_exc}")


async def create_payment(session, amount_rub, description, chat_id, payment_method=METHOD_SBP):
    body = {
        "paymentMethod": payment_method,
        "paymentDetails": {"amount": int(amount_rub), "currency": "RUB"},
        "description": description,
        "return": "https://t.me",
        "failedUrl": "https://t.me",
        "payload": str(chat_id),
        "metadata": {"userId": str(chat_id), "userName": str(chat_id)},
    }
    return await _request(session, "POST", f"{config.PLATEGA_BASE}/transaction/process", json_body=body)


async def get_status(session, transaction_id):
    data = await _request(session, "GET", f"{config.PLATEGA_BASE}/transaction/{transaction_id}")
    return data.get("status")
