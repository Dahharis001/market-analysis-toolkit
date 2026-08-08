import os

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _load_env(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env(_ENV_PATH)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_IDS = [int(x) for x in os.environ.get("ADMIN_CHAT_IDS", "").split(",") if x.strip()]

PLATEGA_MERCHANT_ID = os.environ["PLATEGA_MERCHANT_ID"]
PLATEGA_SECRET = os.environ["PLATEGA_SECRET"]
PLATEGA_BASE = "https://app.platega.io"
# Platega adds its fee on top of the requested sum, so we request less and the
# customer ends up paying exactly the price shown in the bot.
PLATEGA_FEE_PERCENT = float(os.environ.get("PLATEGA_FEE_PERCENT", "8"))
CRYPTOBOT_TOKEN = os.environ["CRYPTOBOT_TOKEN"]
CRYPTOBOT_BASE = "https://pay.crypt.bot/api"

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
SUPPORT_MODEL = os.environ.get("SUPPORT_MODEL", "deepseek/deepseek-chat")

XUI_VERIFY_SSL = os.environ.get("XUI_VERIFY_SSL", "true").lower() not in ("0", "false", "no")

# Two entry points. "ru" is the domestic entry that relays abroad — reachable from
# Russian networks. "eu" is a direct foreign entry for users outside Russia.
PANELS = {
    "ru": {
        "label": "🇷🇺 Я в России",
        "url": os.environ["XUI_PANEL_URL"].rstrip("/"),
        "username": os.environ["XUI_USERNAME"],
        "password": os.environ["XUI_PASSWORD"],
        "inbound_id": int(os.environ["XUI_INBOUND_ID"]),
        "host": os.environ["XUI_SERVER_HOST"],
    }
}

if os.environ.get("XUI_EU_PANEL_URL"):
    PANELS["eu"] = {
        "label": "🌍 Я за границей",
        "url": os.environ["XUI_EU_PANEL_URL"].rstrip("/"),
        "username": os.environ["XUI_EU_USERNAME"],
        "password": os.environ["XUI_EU_PASSWORD"],
        "inbound_id": int(os.environ["XUI_EU_INBOUND_ID"]),
        "host": os.environ["XUI_EU_SERVER_HOST"],
    }

DEFAULT_REGION = "ru"

# kept for backwards compatibility with older single-panel code paths
XUI_PANEL_URL = PANELS["ru"]["url"]
XUI_SERVER_HOST = PANELS["ru"]["host"]

# Referrals pay in days, not cash: an extra user costs us server capacity we have already
# paid for, so a day is worth far more to the referrer than it costs us — and there are no
# payouts to arrange. Both sides are rewarded, on the invited user's first payment.
REFERRAL_DAYS_INVITER = int(os.environ.get("REFERRAL_DAYS_INVITER", "14"))
REFERRAL_DAYS_INVITEE = int(os.environ.get("REFERRAL_DAYS_INVITEE", "7"))

# Legacy cash balances earned under the old percentage scheme stay withdrawable.
REFERRAL_PERCENT = float(os.environ.get("REFERRAL_PERCENT", "20"))
MIN_WITHDRAWAL_RUB = float(os.environ.get("MIN_WITHDRAWAL_RUB", "300"))

SUB_SERVER_PORT = int(os.environ.get("SUB_SERVER_PORT", "8080"))
SUB_BASE_URL = os.environ.get("SUB_BASE_URL", f"http://{os.environ.get('XUI_SERVER_HOST', '')}:{SUB_SERVER_PORT}")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, os.environ.get("STATE_PATH", "state.json"))

# Telegram/OpenRouter/CryptoBot are unreliable from a Russian datacenter, so external
# calls go through a local proxy that exits abroad. Empty = talk to them directly.
OUTBOUND_PROXY = os.environ.get("OUTBOUND_PROXY") or None

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
