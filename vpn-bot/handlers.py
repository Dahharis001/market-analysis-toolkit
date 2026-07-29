import logging

import config
import menus
import platega_api
from plans import PLANS
from state import state

log = logging.getLogger("handlers")

BOT_USERNAME = None  # set by main.py after getMe


async def handle_update(session, tg, update):
    try:
        if "message" in update:
            await _handle_message(session, tg, update["message"])
        elif "callback_query" in update:
            await _handle_callback(session, tg, update["callback_query"])
    except Exception:
        log.exception("failed to handle update %s", update.get("update_id"))


async def _handle_message(session, tg, message):
    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    if text.startswith("/start"):
        referrer = None
        parts = text.split(maxsplit=1)
        if len(parts) == 2 and parts[1].startswith("ref_"):
            try:
                candidate = int(parts[1][4:])
                if candidate != chat_id:
                    referrer = candidate
            except ValueError:
                pass
        state.ensure_user(chat_id, referrer=referrer)
        state.save()
        await tg.send_message(chat_id, menus.WELCOME_TEXT, reply_markup=menus.MAIN_KB)
        return

    if text == "💳 Купить / продлить":
        await tg.send_message(chat_id, "Выберите тариф:", reply_markup=menus.plans_inline_kb())
        return

    if text == "👤 Мой профиль":
        user = state.ensure_user(chat_id)
        await tg.send_message(chat_id, menus.profile_text(user))
        return

    if text == "🤝 Партнёрка":
        user = state.ensure_user(chat_id)
        await tg.send_message(
            chat_id,
            menus.referral_text(BOT_USERNAME, chat_id, user, config.MIN_WITHDRAWAL_RUB, config.REFERRAL_PERCENT),
            reply_markup=menus.withdraw_inline_kb(),
        )
        return

    await tg.send_message(chat_id, "Не понял команду. Используйте кнопки меню.", reply_markup=menus.MAIN_KB)


async def _handle_callback(session, tg, callback_query):
    data = callback_query.get("data", "")
    chat_id = callback_query["message"]["chat"]["id"]

    if data.startswith("buy:"):
        plan_id = data.split(":", 1)[1]
        plan = PLANS.get(plan_id)
        if not plan:
            await tg.answer_callback_query(callback_query["id"], "Тариф не найден")
            return
        result = await platega_api.create_payment(
            session, plan["price"], f"Подписка VPN: {plan['label']}", chat_id
        )
        state.pending_payments[result["transactionId"]] = {"chat_id": chat_id, "plan_id": plan_id}
        state.save()
        await tg.answer_callback_query(callback_query["id"])
        await tg.send_message(
            chat_id,
            f"Оплатите тариф «{plan['label']}» по ссылке ниже. После оплаты доступ выдастся автоматически:\n\n{result['redirect']}",
        )
        return

    if data == "withdraw":
        user = state.ensure_user(chat_id)
        if user["ref_balance"] < config.MIN_WITHDRAWAL_RUB:
            await tg.answer_callback_query(
                callback_query["id"],
                f"Минимум для вывода {config.MIN_WITHDRAWAL_RUB:.0f} ₽, у вас {user['ref_balance']:.2f} ₽",
            )
            return
        amount = user["ref_balance"]
        user["ref_balance"] = 0.0
        state.save()
        await tg.answer_callback_query(callback_query["id"], "Заявка на вывод отправлена")
        await tg.send_message(chat_id, f"✅ Заявка на вывод {amount:.2f} ₽ отправлена, деньги придут вручную от администратора.")
        for admin_id in config.ADMIN_CHAT_IDS:
            await tg.send_message(
                admin_id,
                f"💸 Запрос на вывод от пользователя {chat_id}: {amount:.2f} ₽. Свяжитесь с ним для реквизитов и переведите вручную.",
            )
        return
