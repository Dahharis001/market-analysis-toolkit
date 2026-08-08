import asyncio
import logging

import config
import handlers  # for BOT_USERNAME, set by main after getMe; handlers does not import us
import menus
import platega_api
import cryptobot_api
import qr
import subscriptions
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
    user = state.ensure_user(chat_id)

    # The referral pays out once, on the invited user's first purchase — a trial cannot
    # trigger it, so free accounts cannot be farmed for days.
    inviter_id = user.get("referrer")
    first_purchase = bool(inviter_id) and not user.get("ref_rewarded")
    bonus_days = config.REFERRAL_DAYS_INVITEE if first_purchase else 0

    link, expiry_ms = await activate_subscription(chat_id, plan["days"] + bonus_days)
    del state.pending_payments[transaction_id]
    if first_purchase:
        user["ref_rewarded"] = True
    state.save()

    intro = "✅ Оплата получена! Подписка активна."
    if bonus_days:
        intro += f" И ещё {bonus_days} дней сверху — за то, что пришли по ссылке друга."
    await tg.send_photo_bytes(
        chat_id,
        qr.make_qr_png(link),
        caption=menus.connection_message(intro, link),
        parse_mode="MarkdownV2",
    )
    await handlers._offer_sharing(tg, chat_id)

    if first_purchase:
        await _reward_inviter(tg, inviter_id)


async def _reward_inviter(tg, inviter_id):
    days = config.REFERRAL_DAYS_INVITER
    try:
        applied = await subscriptions.grant_bonus_days(inviter_id, days)
    except Exception:
        log.exception("could not grant referral days to %s", inviter_id)
        return
    state.count_referral(inviter_id, days)
    state.save()
    tail = (
        "Дни уже добавлены к вашей подписке."
        if applied
        else "Дни закреплены за вами и добавятся, как только вы оформите доступ."
    )
    await tg.send_message(inviter_id, f"🎉 Ваш приглашённый оплатил подписку — вам +{days} дней. {tail}")
