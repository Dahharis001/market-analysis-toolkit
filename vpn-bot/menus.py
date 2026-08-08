import re
from urllib.parse import quote

import config
from plans import PLANS, TRIAL_DAYS

_MD_SPECIAL_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!])")


def _escape_md(text):
    return _MD_SPECIAL_RE.sub(r"\\\1", text)


def _code(text):
    escaped = text.replace("\\", "\\\\").replace("`", "\\`")
    return "`" + escaped + "`"

MAIN_KB = {
    "keyboard": [
        [{"text": "🎁 Пробный доступ"}, {"text": "💳 Купить / продлить"}],
        [{"text": "👤 Мой профиль"}, {"text": "🤝 Партнёрка"}],
        [{"text": "❓ Поддержка"}],
        [{"text": "🔒 Конфиденциальность"}, {"text": "📃 Соглашение"}],
    ],
    "resize_keyboard": True,
}

SUPPORT_EXIT_KB = {
    "keyboard": [[{"text": "⬅️ Выйти из поддержки"}]],
    "resize_keyboard": True,
}

SUPPORT_SYSTEM_PROMPT = """Ты — ассистент поддержки Telegram-бота, который продаёт по подписке доступ к защищённому интернет-соединению.

СТРОГИЕ ЗАПРЕТЫ НА ЛЕКСИКУ. Никогда, ни в каком контексте, не употребляй слова и выражения: «VPN», «обход», «обходить», «блокировка», «заблокировано», «разблокировать», «цензура», «ограничение доступа», «запрещённые сайты», «DPI», «ТСПУ», «глушилка», «белый список», «санкции». Не используй их даже в ответах на прямые вопросы и даже если так написал пользователь.

Вместо этого говори: «защищённое соединение», «доступ», «стабильное подключение», «зарубежный сервер».

Если пользователь спрашивает, поможет ли сервис открыть какой-то конкретный сайт или сервис — не обсуждай доступность сайтов вообще. Ответь нейтрально: сервис предоставляет защищённое соединение через зарубежный сервер, а вопросы по конкретным ресурсам — вне компетенции поддержки.

Как устроен сервис:
- Бесплатный пробный доступ на 3 дня — кнопка «🎁 Пробный доступ», один раз на аккаунт.
- Платные тарифы: 1 месяц (150₽), 3 месяца (400₽), 12 месяцев (1200₽) — кнопка «💳 Купить / продлить».
- Оплата: СБП через Platega или криптовалютой (USDT/TON/BTC) через CryptoBot — выбор способа появляется после выбора тарифа.
- После оплаты или активации пробного периода бот присылает ссылку (vless://...) для подключения в приложении (v2rayNG, NekoBox, Hiddify).
- Подключение: скачать бесплатное приложение Hiddify (App Store/Google Play) → открыть → нажать «+» → вставить скопированную ссылку из буфера обмена → нажать кнопку подключения.
- Реферальная программа (раздел «🤝 Партнёрка»): приглашённому +7 дней сверх первого оплаченного тарифа, пригласившему +14 дней за каждого, кто оплатит. Начисляется автоматически сразу после оплаты приглашённого, деньги не выводятся — награда только днями. У кого остался баланс со старой схемы, тот может вывести его от 300₽ через администратора.
- Если пользователь потерял ссылку для подключения — она всегда доступна в разделе «👤 Мой профиль» по кнопке «🔑 Моя ссылка».
- Частые проблемы: не подключается — посоветуй проверить, что ссылка вставлена полностью, переустановить/обновить Hiddify, попробовать другую сеть (Wi-Fi/мобильный интернет). На Android и Windows подойдут v2rayNG, NekoBox, Hiddify; на iPhone — Happ, Streisand, v2RayTun.
- Политика конфиденциальности и пользовательское соглашение доступны кнопками в главном меню.
- Если не можешь помочь — предложи написать напрямую: @arsbay.

Отвечай кратко, по-русски, дружелюбно, только по теме сервиса. Если вопрос не по теме — вежливо откажись и предложи написать администратору (@arsbay)."""

# Safety net: the model can still slip, so anything it writes is checked before sending.
BANNED_PATTERNS = re.compile(
    # "не" guard keeps «необходимо» clean; "де" guard keeps our own brand «ДЕСАНКЦИЯ» clean
    r"vpn|(?<!не)обход|обойти|блокиров|заблокир|разблокир|цензур|"
    r"запрещённ|запрещенн|роскомнадзор|dpi|тспу|глушилк|белый\s+список|(?<!де)санкц",
    re.IGNORECASE,
)

SUPPORT_FALLBACK = (
    "Не могу ответить на этот вопрос. Сервис предоставляет доступ к защищённому "
    "интернет-соединению через зарубежный сервер.\n\n"
    "По вопросам подписки, оплаты и подключения — спрашивайте, помогу. "
    "По остальному напишите администратору: @arsbay"
)


def is_answer_safe(text):
    """False if the assistant's reply contains wording our payment provider prohibits."""
    return not BANNED_PATTERNS.search(text or "")


def region_inline_kb(action):
    """action is carried through the callback so we know what to do after the choice."""
    rows = [[{"text": p["label"], "callback_data": f"region:{action}:{code}"}]
            for code, p in config.PANELS.items()]
    return {"inline_keyboard": rows}


REGION_QUESTION = (
    "Откуда вы будете подключаться?\n\n"
    "🇷🇺 Я в России — вход через российский сервер, работает на мобильных сетях\n"
    "🌍 Я за границей — прямое подключение к зарубежному серверу"
)


def region_name(code):
    panel = config.PANELS.get(code)
    return panel["label"] if panel else code


def plans_inline_kb():
    rows = [[{"text": p["label"], "callback_data": f"buy:{key}"}] for key, p in PLANS.items()]
    return {"inline_keyboard": rows}


def _ref_link(bot_username, chat_id):
    return f"https://t.me/{bot_username}?start=ref_{chat_id}"


SHARE_PITCH = (
    "Пользуюсь этим ботом для защищённого соединения — 3 дня бесплатно, "
    "дальше 150 ₽ в месяц. Заходи по ссылке, тебе дадут неделю сверху:"
)


def share_prompt(bot_username, chat_id):
    """Text + keyboard nudging the user to pass their link on. Sent right after a working
    connection is delivered, which is the only moment they are demonstrably happy."""
    link = _ref_link(bot_username, chat_id)
    text = (
        "Всё подключилось? Позовите друзей:\n\n"
        f"• другу — {config.REFERRAL_DAYS_INVITEE} дней сверх первого оплаченного тарифа\n"
        f"• вам — {config.REFERRAL_DAYS_INVITER} дней за каждого, кто оплатит\n\n"
        f"{link}"
    )
    share_url = (
        "https://t.me/share/url?url=" + quote(link, safe="")
        + "&text=" + quote(SHARE_PITCH, safe="")
    )
    return text, {"inline_keyboard": [[{"text": "📤 Поделиться", "url": share_url}]]}


WELCOME_TEXT = (
    "👋 Добро пожаловать!\n\n"
    f"Можно попробовать бесплатно {TRIAL_DAYS} дня кнопкой «🎁 Пробный доступ», "
    "или сразу выбрать тариф кнопкой «💳 Купить / продлить» — после оплаты вы сразу получите ссылку для подключения.\n\n"
    "Есть своя реферальная программа — приглашайте друзей и получайте % с их оплат (раздел «🤝 Партнёрка»)."
)


def connection_message(intro, link, sub_url=None):
    """Caption for the QR photo: the link sits in a code span, so tapping it copies the whole link."""
    return (
        f"{_escape_md(intro)}\n\n"
        f"{_escape_md('Отсканируйте QR в приложении (Happ, v2RayTun, v2rayNG, NekoBox, Hiddify) '
                      'или нажмите на ссылку ниже, чтобы скопировать её:')}\n\n"
        f"{_code(link)}"
    )


def profile_text(user):
    import time
    now_ms = int(time.time() * 1000)
    if user["expiry_ms"] > now_ms:
        days_left = (user["expiry_ms"] - now_ms) // (24 * 60 * 60 * 1000)
        status = f"✅ Активна, осталось {days_left} дн."
    else:
        status = "❌ Не активна"
    lines = [f"👤 Ваш профиль", "", f"Подписка: {status}"]
    if len(config.PANELS) > 1:
        lines.append(f"Сервер: {region_name(user.get('region'))}")
    return "\n".join(lines)


def profile_inline_kb(user):
    if not user.get("xui_email"):
        return None
    rows = [[{"text": "🔑 Моя ссылка", "callback_data": "my_link"}]]
    if len(config.PANELS) > 1:
        rows.append([{"text": "🌍 Сменить сервер", "callback_data": "switch_region"}])
    return {"inline_keyboard": rows}


def referral_text(bot_username, chat_id, user):
    lines = [
        "🤝 Партнёрская программа",
        "",
        f"• Другу — {config.REFERRAL_DAYS_INVITEE} дней сверх первого оплаченного тарифа",
        f"• Вам — {config.REFERRAL_DAYS_INVITER} дней за каждого, кто оплатит",
        "",
        "Начисляется автоматически, сразу после оплаты приглашённого.",
        "",
        "Ваша ссылка:",
        _ref_link(bot_username, chat_id),
        "",
        f"Оплатили по вашей ссылке: {user.get('ref_count', 0)}",
        f"Всего начислено дней: {user.get('ref_days', 0)}",
    ]
    if user.get("days_banked"):
        lines.append(f"Ждут активации: {user['days_banked']} дн. — добавятся, когда оформите доступ")
    if user.get("ref_balance", 0) > 0:
        lines += [
            "",
            f"Остаток старого денежного баланса: {user['ref_balance']:.2f} ₽ "
            f"(вывод от {config.MIN_WITHDRAWAL_RUB:.0f} ₽; новые начисления идут днями)",
        ]
    return "\n".join(lines)


def referral_inline_kb(bot_username, chat_id, user):
    _, keyboard = share_prompt(bot_username, chat_id)
    rows = list(keyboard["inline_keyboard"])
    if user.get("ref_balance", 0) > 0:
        rows.append([{"text": "💸 Вывести старый баланс", "callback_data": "withdraw"}])
    return {"inline_keyboard": rows}
