import asyncio
import logging
import os
import tempfile

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message

import config
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
        "Я сгенерирую таймлапс ремонта от голых стен до вашего фото и пришлю готовое видео. "
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

        await status_msg.edit_text(
            f"Этапы готовы ({len(stages)}). Генерирую видео — это может занять несколько минут…"
        )

        loop = asyncio.get_running_loop()

        def progress_cb(i: int, total: int, phase: str) -> None:
            async def _edit():
                try:
                    await status_msg.edit_text(f"Этап {i}/{total}: {phase}…")
                except Exception:
                    pass

            asyncio.run_coroutine_threadsafe(_edit(), loop)

        try:
            clips = await loop.run_in_executor(
                None, vp.generate_clips, cfg, ref_path, stages, tmp, progress_cb
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
