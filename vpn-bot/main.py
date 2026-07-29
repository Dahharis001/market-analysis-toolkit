import asyncio
import logging

import aiohttp

import handlers
import payments
from state import state
from telegram_api import TelegramClient
from xui_api import xui

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

        try:
            await asyncio.gather(
                poll_updates(session, tg),
                payments.poll_loop(session, tg),
            )
        finally:
            await xui.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
