import asyncio
import logging
import os
import tempfile

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

import config
import image_pipeline as ip
import openrouter_client as orc
import video_pipeline as vp

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("renovation-bot")

cfg = config.load_config()
bot = Bot(cfg.telegram_bot_token)
dp = Dispatcher()

STYLE_NOTES = (
    "люксовый дорогой интерьер: крупноформатный графитовый керамогранит, чёрный матовый потолок, "
    "скрытая LED-подсветка, минимализм, премиальная сантехника без ручек, кинематографичный свет"
)

STAGE_OPTIONS = (7, 10, 12, 15)

# In-memory: user_id -> Telegram file_id of the reference photo they just sent,
# waiting for them to pick a stage count. Fine for a single-process polling bot;
# would need real storage (Redis/db) if this bot is ever scaled to multiple workers.
_pending_photos: dict[int, str] = {}


def _stage_count_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=str(n), callback_data=f"stages:{n}") for n in STAGE_OPTIONS]
        ]
    )


@dp.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "Пришлите фото готовой ванной комнаты (референс — финальный результат ремонта).\n\n"
        "Я спрошу, сколько этапов ремонта показать (7 / 10 / 12 / 15), затем:\n"
        "1) один ИИ распишет промпт для каждого этапа по вашему фото,\n"
        "2) по этим промптам сгенерируются фото каждого этапа (пришлю альбомом),\n"
        "3) по этим фото соберётся один плавный видео-таймлапс.\n\n"
        "Это может занять несколько минут и расходует баланс на вашем OpenRouter-аккаунте."
    )


@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    _pending_photos[message.from_user.id] = message.photo[-1].file_id
    await message.answer("Сколько этапов ремонта сделать?", reply_markup=_stage_count_keyboard())


@dp.callback_query(F.data.startswith("stages:"))
async def handle_stage_choice(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    file_id = _pending_photos.pop(user_id, None)
    if not file_id:
        await callback.message.edit_text("Фото не найдено, пришлите его заново.")
        return

    num_stages = int(callback.data.split(":", 1)[1])
    await callback.message.edit_text(f"Этапов: {num_stages}. Анализирую референс…")
    status_msg = callback.message

    with tempfile.TemporaryDirectory() as tmp:
        ref_path = os.path.join(tmp, "reference.jpg")
        await bot.download(file_id, destination=ref_path)

        try:
            image_data_uri = orc.image_to_data_uri(ref_path)
            stages = orc.generate_stage_prompts(
                cfg.openrouter_api_key, cfg.stage_prompt_model, image_data_uri, num_stages, STYLE_NOTES
            )
        except Exception as e:
            log.exception("stage prompt generation failed")
            await status_msg.edit_text(f"Не получилось разобрать этапы: {e}")
            return

        await status_msg.edit_text(f"Этапы готовы ({len(stages)}). Генерирую фото каждого этапа…")

        loop = asyncio.get_running_loop()

        def make_progress_cb(label: str):
            def cb(i: int, total: int, phase: str = "") -> None:
                async def _edit():
                    try:
                        text = f"{label} {i}/{total}" + (f": {phase}…" if phase else "…")
                        await status_msg.edit_text(text)
                    except Exception:
                        pass

                asyncio.run_coroutine_threadsafe(_edit(), loop)

            return cb

        try:
            stage_images = await loop.run_in_executor(
                None, ip.generate_stage_images, cfg, ref_path, stages, tmp, make_progress_cb("Фото")
            )
        except Exception as e:
            log.exception("stage image generation failed")
            await status_msg.edit_text(f"Не получилось сгенерировать фото этапов: {e}")
            return

        try:
            media = [InputMediaPhoto(media=FSInputFile(p)) for p in stage_images]
            for start in range(0, len(media), 10):
                await bot.send_media_group(chat_id=status_msg.chat.id, media=media[start:start + 10])
        except Exception:
            log.exception("failed to send stage image album")

        await status_msg.edit_text("Фото этапов отправлены. Генерирую видео — это может занять несколько минут…")

        try:
            clips = await loop.run_in_executor(
                None, vp.generate_clips, cfg, stages, stage_images, tmp, make_progress_cb("Видео")
            )
            final_path = os.path.join(tmp, "final.mp4")
            await loop.run_in_executor(None, vp.stitch_with_crossfade, clips, final_path)
        except Exception as e:
            log.exception("video pipeline failed")
            await status_msg.edit_text(f"Ошибка генерации видео: {e}")
            return

        await status_msg.edit_text("Готово! Отправляю видео…")
        await bot.send_video(
            chat_id=status_msg.chat.id, video=FSInputFile(final_path), caption="Таймлапс ремонта готов"
        )


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
