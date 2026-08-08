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

    # Referral days owed to someone who had no subscription when they earned them are
    # handed over the first time they actually get one.
    if days > 0 and user.get("days_banked"):
        days += user["days_banked"]
        user["days_banked"] = 0

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


async def grant_bonus_days(chat_id, days):
    """Extends a user's subscription by bonus days. Someone who has never had a client
    yet gets the days banked instead, so the reward is never silently dropped."""
    user = state.ensure_user(chat_id)
    if not user["xui_email"]:
        user["days_banked"] = user.get("days_banked", 0) + days
        state.save()
        return False
    await activate_subscription(chat_id, days)
    return True


async def current_link(chat_id):
    """The link for an already-active subscription. None when there is nothing to show."""
    user = state.ensure_user(chat_id)
    if not user["xui_email"] or user["expiry_ms"] <= int(time.time() * 1000):
        return None
    panel = xui_api.for_region(user.get("region"))
    return await panel.share_link(user["xui_email"])


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
