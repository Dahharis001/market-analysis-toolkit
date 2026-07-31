import asyncio
import logging

import config
import menus
import platega_api
import cryptobot_api
import qr
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
        provider = pending.get("provider", "platega")
        try:
            if provider == "platega":
                status = await platega_api.get_status(session, transaction_id)
                if status == "CONFIRMED":
                    await _on_paid(tg, transaction_id, pending)
                elif status in ("CANCELED", "CHARGEBACKED"):
                    del state.pending_payments[transaction_id]
                    state.save()
                    await tg.send_message(pending["chat_id"], "❌ Платёж не прошёл или отменён. Попробуйте снова через меню оплаты.")
            else:  # cryptobot
                invoice = await cryptobot_api.get_invoice(session, transaction_id)
                if not invoice:
                    # invoice not found, maybe expired, remove
                    del state.pending_payments[transaction_id]
                    state.save()
                    continue
                status = invoice.get("status")
                if status == "paid":
                    await _on_paid(tg, transaction_id, pending)
                elif status in ("expired", "cancelled"):
                    del state.pending_payments[transaction_id]
                    state.save()
                    await tg.send_message(pending["chat_id"], "❌ Счёт не оплачен или истёк. Попробуйте снова через меню оплаты.")
        except Exception:
            log.exception("status check failed for %s", transaction_id)
            continue


async def _on_paid(tg, transaction_id, pending):
    chat_id = pending["chat_id"]
    plan = PLANS[pending["plan_id"]]

    link, expiry_ms = await activate_subscription(chat_id, plan["days"])
    del state.pending_payments[transaction_id]
    state.save()

    await tg.send_photo_bytes(
        chat_id,
        qr.make_qr_png(link),
        caption=menus.connection_message("✅ Оплата получена! Подписка активна.", link),
        parse_mode="MarkdownV2",
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
