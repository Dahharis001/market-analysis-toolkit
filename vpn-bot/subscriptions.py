import logging
import time

from plans import DAY_MS
from state import state
from xui_api import xui

log = logging.getLogger("subscriptions")


async def activate_subscription(chat_id, days):
    """Extends (or creates) the user's VLESS client on the access server. Returns the share link."""
    user = state.ensure_user(chat_id)
    now_ms = int(time.time() * 1000)
    base = user["expiry_ms"] if user["expiry_ms"] > now_ms else now_ms
    new_expiry = base + days * DAY_MS

    if user["xui_email"]:
        link, client_uuid = await xui.update_client_expiry(user["xui_email"], new_expiry)
    else:
        email = f"tg{chat_id}"
        link, client_uuid = await xui.add_client(email, new_expiry)
        user["xui_email"] = email
    user["xui_uuid"] = client_uuid

    user["expiry_ms"] = new_expiry
    state.save()
    return link, new_expiry
