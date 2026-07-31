import asyncio
import logging

import aiohttp

import config

log = logging.getLogger("cryptobot")

HEADERS = {"Crypto-Pay-API-Token": config.CRYPTOBOT_TOKEN}
MAX_TRIES = 4
RETRY_WAIT = 3.0


async def _request(session, method, url, *, params=None, json_body=None, timeout=30):
    last_exc = None
    for attempt in range(1, MAX_TRIES + 1):
        try:
            async with session.request(
                method, url, params=params, json=json_body, headers=HEADERS,
                proxy=config.OUTBOUND_PROXY, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as r:
                data = await r.json()
                if not data.get("ok"):
                    last_exc = RuntimeError(str(data)[:300])
                else:
                    return data["result"]
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            last_exc = e
        log.warning("CryptoBot %s attempt %d/%d failed: %s", url, attempt, MAX_TRIES, last_exc)
        if attempt < MAX_TRIES:
            await asyncio.sleep(RETRY_WAIT)
    raise RuntimeError(f"CryptoBot запрос не удался: {last_exc}")


async def create_invoice(session, amount_rub, description, chat_id, plan_id):
    body = {
        "currency_type": "fiat",
        "fiat": "RUB",
        "amount": str(amount_rub),
        "accepted_assets": "USDT,TON,BTC",
        "description": description,
        "payload": f"{chat_id}:{plan_id}",
    }
    return await _request(session, "POST", f"{config.CRYPTOBOT_BASE}/createInvoice", json_body=body)


async def get_invoices(session, invoice_ids):
    if not invoice_ids:
        return []
    result = await _request(session, "GET", f"{config.CRYPTOBOT_BASE}/getInvoices", params={"invoice_ids": ",".join(str(i) for i in invoice_ids)})
    return result.get("items", [])


async def get_invoice(session, invoice_id):
    invoices = await get_invoices(session, [invoice_id])
    return invoices[0] if invoices else None