import logging
import time

import xui_api
from plans import DAY_MS
from state import state

log = logging.getLogger("subscriptions")


async def activate_subscription(chat_id, days, region=None):
    """Extends (or creates) the user's VLESS client on the access server they picked.

    Switching region moves the subscription: the client is recreated on the new panel
    with the same expiry and removed from the old one.
    """
    user = state.ensure_user(chat_id)
    region = region or user.get("region")
    panel = xui_api.for_region(region)

    now_ms = int(time.time() * 1000)
    base = user["expiry_ms"] if user["expiry_ms"] > now_ms else now_ms
    new_expiry = base + days * DAY_MS

    email = user["xui_email"] or f"tg{chat_id}"
    moved_from = None
    if user["xui_email"] and user.get("region") != panel.region:
        moved_from = xui_api.for_region(user.get("region"))

    if user["xui_email"] and moved_from is None:
        link, client_uuid = await panel.update_client_expiry(email, new_expiry)
    else:
        link, client_uuid = await panel.add_client(email, new_expiry)

    if moved_from is not None:
        log.info("moved %s from %s to %s", email, moved_from.region, panel.region)
        await moved_from.delete_client(email)

    user["xui_email"] = email
    user["xui_uuid"] = client_uuid
    user["region"] = panel.region
    user["expiry_ms"] = new_expiry
    state.save()
    return link, new_expiry


async def move_to_region(chat_id, region):
    """Re-issues the existing subscription on another entry server, keeping the expiry."""
    user = state.ensure_user(chat_id)
    now_ms = int(time.time() * 1000)
    remaining_ms = max(user["expiry_ms"] - now_ms, 0)
    if not user["xui_email"] or remaining_ms == 0:
        return None
    # activate_subscription adds days on top of what is left, so add nothing
    user["expiry_ms"] = now_ms + remaining_ms
    link, _ = await activate_subscription(chat_id, 0, region=region)
    return link
