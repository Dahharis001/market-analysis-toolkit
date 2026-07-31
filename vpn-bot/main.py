import asyncio
import logging

import aiohttp

import handlers
import payments
import subscription_server
from state import state
from telegram_api import TelegramClient
import xui_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


async def poll_updates(session, tg):
    if state.offset:
        log.info("resuming from offset %s", state.offset)
    while True:
        updates = await tg.get_updates(state.offset, timeout=30)
        for u in updates:
            state.offset = u["update_id"] + 1
            asyncio.create_task(handlers.handle_update(session, tg, u))
        if updates:
            state.save()


async def main():
    async with aiohttp.ClientSession() as session:
        tg = TelegramClient(session)
        log.info("bot starting, checking Telegram credentials...")
        me = await tg.get_me()
        handlers.BOT_USERNAME = me["username"]
        log.info("logged in as @%s", me["username"])

        sub_runner = await subscription_server.start_server()
        try:
            await asyncio.gather(
                poll_updates(session, tg),
                payments.poll_loop(session, tg),
            )
        finally:
            await sub_runner.cleanup()
            await xui_api.close_all()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
