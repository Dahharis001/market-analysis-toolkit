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

XUI_PANEL_URL = os.environ["XUI_PANEL_URL"].rstrip("/")
XUI_USERNAME = os.environ["XUI_USERNAME"]
XUI_PASSWORD = os.environ["XUI_PASSWORD"]
XUI_INBOUND_ID = int(os.environ["XUI_INBOUND_ID"])
XUI_SERVER_HOST = os.environ["XUI_SERVER_HOST"]
XUI_VERIFY_SSL = os.environ.get("XUI_VERIFY_SSL", "true").lower() not in ("0", "false", "no")

REFERRAL_PERCENT = float(os.environ.get("REFERRAL_PERCENT", "20"))
MIN_WITHDRAWAL_RUB = float(os.environ.get("MIN_WITHDRAWAL_RUB", "300"))

SUB_SERVER_PORT = int(os.environ.get("SUB_SERVER_PORT", "8080"))
SUB_BASE_URL = os.environ.get("SUB_BASE_URL", f"http://{os.environ.get('XUI_SERVER_HOST', '')}:{SUB_SERVER_PORT}")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, os.environ.get("STATE_PATH", "state.json"))

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
