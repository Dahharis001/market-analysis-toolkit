import asyncio
import logging

import aiohttp

import config

log = logging.getLogger("telegram")


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def _post_json(self, method, payload, timeout=30):
        url = f"{config.TELEGRAM_API}/{method}"
        async with self.session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            data = await r.json()
            if not data.get("ok"):
                raise TelegramError(f"{method} failed: {data}")
            return data["result"]

    async def get_me(self):
        return await self._post_json("getMe", {}, timeout=15)

    async def get_updates(self, offset, timeout=30):
        url = f"{config.TELEGRAM_API}/getUpdates"
        params = {"offset": offset, "timeout": timeout}
        try:
            async with self.session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=timeout + 10)
            ) as r:
                data = await r.json()
                if not data.get("ok"):
                    log.warning("getUpdates failed: %s", data)
                    return []
                return data["result"]
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            log.warning("getUpdates network error: %s", e)
            return []

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        return await self._post_json("sendMessage", payload)

    async def answer_callback_query(self, callback_query_id, text=None):
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return await self._post_json("answerCallbackQuery", payload)

    async def send_photo_bytes(self, chat_id, image_bytes, caption=None, filename="qr.png", parse_mode=None):
        url = f"{config.TELEGRAM_API}/sendPhoto"
        data = aiohttp.FormData()
        data.add_field("chat_id", str(chat_id))
        if caption:
            data.add_field("caption", caption)
        if parse_mode:
            data.add_field("parse_mode", parse_mode)
        data.add_field("photo", image_bytes, filename=filename, content_type="image/png")
        async with self.session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=60)) as r:
            result = await r.json()
        if not result.get("ok"):
            raise TelegramError(f"sendPhoto (upload) failed: {result}")
        return result["result"]
