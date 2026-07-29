import logging

from aiohttp import web

import config
import singbox_profile
from state import state
from xui_api import xui

log = logging.getLogger("subserver")


async def handle_sub(request):
    token = request.match_info["token"]
    chat_id, user = state.find_by_sub_token(token)
    if not user or not user.get("xui_uuid"):
        return web.json_response({"error": "not found"}, status=404)

    reality_info = await xui.get_reality_info()
    profile = singbox_profile.build_config(reality_info, user["xui_uuid"], remark=f"access-{chat_id}")
    return web.json_response(profile)


def build_app():
    app = web.Application()
    app.router.add_get("/sub/{token}", handle_sub)
    return app


async def start_server():
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.SUB_SERVER_PORT)
    await site.start()
    log.info("subscription server listening on :%s", config.SUB_SERVER_PORT)
    return runner
