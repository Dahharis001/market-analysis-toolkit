from plans import PLANS, TRIAL_DAYS

MAIN_KB = {
    "keyboard": [
        [{"text": "🎁 Пробный доступ"}, {"text": "💳 Купить / продлить"}],
        [{"text": "👤 Мой профиль"}, {"text": "🤝 Партнёрка"}],
    ],
    "resize_keyboard": True,
}


def plans_inline_kb():
    rows = [[{"text": p["label"], "callback_data": f"buy:{key}"}] for key, p in PLANS.items()]
    return {"inline_keyboard": rows}


def withdraw_inline_kb():
    return {"inline_keyboard": [[{"text": "💸 Запросить вывод", "callback_data": "withdraw"}]]}


WELCOME_TEXT = (
    "👋 Добро пожаловать!\n\n"
    f"Можно попробовать бесплатно {TRIAL_DAYS} дня кнопкой «🎁 Пробный доступ», "
    "или сразу выбрать тариф кнопкой «💳 Купить / продлить» — после оплаты вы сразу получите ссылку для подключения.\n\n"
    "Есть своя реферальная программа — приглашайте друзей и получайте % с их оплат (раздел «🤝 Партнёрка»)."
)


def connection_message(intro, link, sub_url):
    return (
        f"{intro}\n\n"
        f"1) Простая ссылка (любое приложение — v2rayNG, NekoBox, Hiddify):\n{link}\n\n"
        f"2) Ссылка-подписка с автообходом российских сайтов (только для Hiddify/sing-box — "
        f"добавьте как «Sing-box подписку»):\n{sub_url}"
    )


def profile_text(user):
    import time
    now_ms = int(time.time() * 1000)
    if user["expiry_ms"] > now_ms:
        days_left = (user["expiry_ms"] - now_ms) // (24 * 60 * 60 * 1000)
        status = f"✅ Активна, осталось {days_left} дн."
    else:
        status = "❌ Не активна"
    return f"👤 Ваш профиль\n\nПодписка: {status}"


def referral_text(bot_username, chat_id, user, min_withdrawal, percent):
    link = f"https://t.me/{bot_username}?start=ref_{chat_id}"
    return (
        "🤝 Партнёрская программа\n\n"
        f"Ваша ссылка для приглашений:\n{link}\n\n"
        f"Вы получаете {percent:.0f}% от каждой оплаты приглашённого пользователя.\n\n"
        f"Приглашено оплативших: {user['ref_count']}\n"
        f"Баланс: {user['ref_balance']:.2f} ₽\n"
        f"Минимум для вывода: {min_withdrawal:.0f} ₽"
    )
