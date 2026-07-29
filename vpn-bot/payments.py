import asyncio
import logging

import config
import platega_api
from plans import PLANS
from state import state
from subscriptions import activate_subscription

log = logging.getLogger("payments")

POLL_INTERVAL = 10


async def poll_loop(session, tg):
    while True:
        try:
            await _check_once(session, tg)
        except Exception:
            log.exception("payments poll iteration failed")
        await asyncio.sleep(POLL_INTERVAL)


async def _check_once(session, tg):
    if not state.pending_payments:
        return
    for transaction_id in list(state.pending_payments.keys()):
        pending = state.pending_payments[transaction_id]
        try:
            status = await platega_api.get_status(session, transaction_id)
        except Exception:
            log.exception("status check failed for %s", transaction_id)
            continue

        if status == "CONFIRMED":
            await _on_paid(tg, transaction_id, pending)
        elif status in ("CANCELED", "CHARGEBACKED"):
            del state.pending_payments[transaction_id]
            state.save()
            await tg.send_message(pending["chat_id"], "❌ Платёж не прошёл или отменён. Попробуйте снова через меню оплаты.")


async def _on_paid(tg, transaction_id, pending):
    chat_id = pending["chat_id"]
    plan = PLANS[pending["plan_id"]]

    link, expiry_ms = await activate_subscription(chat_id, plan["days"])
    del state.pending_payments[transaction_id]
    state.save()

    await tg.send_message(
        chat_id,
        f"✅ Оплата получена! Подписка активна.\n\n"
        f"Ваша ссылка для подключения (импортируйте в приложение — Hiddify/v2rayNG/NekoBox):\n"
        f"{link}",
    )

    referrer_id = state.users.get(chat_id, {}).get("referrer")
    if referrer_id:
        bonus = round(plan["price"] * config.REFERRAL_PERCENT / 100, 2)
        state.credit_referral(referrer_id, bonus)
        state.save()
        await tg.send_message(
            referrer_id,
            f"💰 Ваш реферал оплатил подписку. Начислено {bonus} ₽ на реферальный баланс.",
        )
