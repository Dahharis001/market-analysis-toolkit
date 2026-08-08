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

RETRY_DELAY = 5


async def poll_updates(session, tg):
    if state.offset:
        log.info("resuming from offset %s", state.offset)
    while True:
        try:
            updates = await tg.get_updates(state.offset, timeout=30)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A blip on the outbound proxy used to take the whole process down and let
            # systemd restart it; retrying in place keeps the payment loop alive instead.
            log.exception("getUpdates failed, retrying in %ss", RETRY_DELAY)
            await asyncio.sleep(RETRY_DELAY)
            continue
        for u in updates:
            state.offset = u["update_id"] + 1
            asyncio.create_task(handlers.handle_update(session, tg, u))
        if updates:
            state.save()


async def main():
    async with aiohttp.ClientSession() as session:
        tg = TelegramClient(session)
        log.info("bot starting, checking Telegram credentials...")
        # On a reboot systemd can start us before the local outbound proxy is listening,
        # so getMe is retried rather than allowed to kill the process.
        while True:
            try:
                me = await tg.get_me()
                break
            except Exception:
                log.exception("getMe failed (proxy not up yet?), retrying in %ss", RETRY_DELAY)
                await asyncio.sleep(RETRY_DELAY)
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
