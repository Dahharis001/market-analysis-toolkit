import asyncio
import logging
import os
import tempfile

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, InputMediaPhoto, Message

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

MIN_STAGES, MAX_STAGES = 3, 30


@dp.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "Пришлите фото готовой ванной комнаты (референс — финальный результат ремонта).\n\n"
        f"В подписи к фото можно указать число этапов, например «12» "
        f"(по умолчанию {cfg.default_num_stages}, диапазон {MIN_STAGES}-{MAX_STAGES}).\n\n"
        "Сначала пришлю альбомом фото каждого этапа (сгенерированы ИИ), а затем — готовый "
        "видео-таймлапс ремонта от голых стен до вашего фото. "
        "Это может занять несколько минут и расходует баланс на вашем OpenRouter-аккаунте."
    )


@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    num_stages = cfg.default_num_stages
    if message.caption:
        digits = "".join(ch for ch in message.caption if ch.isdigit())
        if digits:
            num_stages = max(MIN_STAGES, min(MAX_STAGES, int(digits)))

    status_msg = await message.answer(f"Принял фото. Этапов: {num_stages}. Анализирую референс…")

    with tempfile.TemporaryDirectory() as tmp:
        photo = message.photo[-1]
        ref_path = os.path.join(tmp, "reference.jpg")
        await bot.download(photo, destination=ref_path)

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
                await message.answer_media_group(media[start:start + 10])
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
        await message.answer_video(FSInputFile(final_path), caption="Таймлапс ремонта готов")


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
