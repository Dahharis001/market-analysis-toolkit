import asyncio
import logging
import os
import shutil
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
    "luxury high-end interior: premium materials, high-quality finishing, hidden LED lighting, "
    "minimalism, expensive furniture and appliances, cinematic lighting - materials and furniture "
    "match whatever room type is seen in the photo"
)

STAGE_OPTIONS = (7, 10, 12, 15)

# In-memory state. Fine for a single-process polling bot; would need real storage
# (Redis/db) if this bot is ever scaled to multiple workers.
# user_id -> Telegram file_id of the reference photo, waiting for a stage-count pick.
_pending_photos: dict[int, str] = {}
# user_id -> {"work_dir", "ref_path", "stages", "stage_images"}, waiting for the user
# to approve (or ask to regenerate) the stage-photo album before video generation starts.
_pending_generations: dict[int, dict] = {}


def _stage_count_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=str(n), callback_data=f"stages:{n}") for n in STAGE_OPTIONS]
        ]
    )


def _approval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Начать видео", callback_data="approve_video")],
            [InlineKeyboardButton(text="Перегенерировать фото", callback_data="regen_photos")],
        ]
    )


def _make_progress_cb(status_msg: Message, loop: asyncio.AbstractEventLoop, label: str):
    def cb(i: int, total: int, phase: str = "") -> None:
        async def _edit():
            try:
                text = f"{label} {i}/{total}" + (f": {phase}…" if phase else "…")
                await status_msg.edit_text(text)
            except Exception:
                pass

        asyncio.run_coroutine_threadsafe(_edit(), loop)

    return cb


async def _send_stage_album(chat_id: int, stage_images: list[str]) -> None:
    try:
        media = [InputMediaPhoto(media=FSInputFile(p)) for p in stage_images]
        for start in range(0, len(media), 10):
            await bot.send_media_group(chat_id=chat_id, media=media[start:start + 10])
    except Exception:
        log.exception("failed to send stage image album")


@dp.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "Пришлите фото готовой комнаты — любой (ванная, спальня, кухня, гостиная и т.д.), "
        "это референс, финальный результат ремонта.\n\n"
        "Я спрошу, сколько этапов ремонта показать (7 / 10 / 12 / 15), затем:\n"
        "1) один ИИ распишет промпт для каждого этапа по вашему фото,\n"
        "2) по этим промптам сгенерируются фото каждого этапа (пришлю альбомом) - вы сможете "
        "перегенерировать их или дать добро,\n"
        "3) только после вашего подтверждения по этим фото соберётся видео-таймлапс.\n\n"
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
    status_msg = callback.message
    await status_msg.edit_text(f"Этапов: {num_stages}. Анализирую референс…")

    work_dir = tempfile.mkdtemp(prefix="renov_")
    ref_path = os.path.join(work_dir, "reference.jpg")
    await bot.download(file_id, destination=ref_path)

    try:
        image_data_uri = orc.image_to_data_uri(ref_path)
        stages = orc.generate_stage_prompts(
            cfg.openrouter_api_key, cfg.stage_prompt_model, image_data_uri, num_stages, STYLE_NOTES
        )
    except Exception as e:
        log.exception("stage prompt generation failed")
        await status_msg.edit_text(f"Не получилось разобрать этапы: {e}")
        shutil.rmtree(work_dir, ignore_errors=True)
        return

    await status_msg.edit_text(f"Этапы готовы ({len(stages)}). Генерирую фото каждого этапа…")

    loop = asyncio.get_running_loop()
    try:
        stage_images = await loop.run_in_executor(
            None, ip.generate_stage_images, cfg, ref_path, stages, work_dir,
            _make_progress_cb(status_msg, loop, "Фото"),
        )
    except Exception as e:
        log.exception("stage image generation failed")
        await status_msg.edit_text(f"Не получилось сгенерировать фото этапов: {e}")
        shutil.rmtree(work_dir, ignore_errors=True)
        return

    _pending_generations[user_id] = {
        "work_dir": work_dir,
        "ref_path": ref_path,
        "stages": stages,
        "stage_images": stage_images,
    }

    await _send_stage_album(status_msg.chat.id, stage_images)
    await status_msg.edit_text(
        "Фото этапов отправлены. Устраивает результат?", reply_markup=_approval_keyboard()
    )


@dp.callback_query(F.data == "regen_photos")
async def handle_regen_photos(callback: CallbackQuery) -> None:
    await callback.answer("Перегенерирую фото…")
    user_id = callback.from_user.id
    pending = _pending_generations.get(user_id)
    if not pending:
        await callback.message.edit_text("Сессия устарела, пришлите фото заново.")
        return

    status_msg = callback.message
    await status_msg.edit_text("Перегенерирую фото этапов…")

    loop = asyncio.get_running_loop()
    try:
        stage_images = await loop.run_in_executor(
            None, ip.generate_stage_images, cfg, pending["ref_path"], pending["stages"],
            pending["work_dir"], _make_progress_cb(status_msg, loop, "Фото"),
        )
    except Exception as e:
        log.exception("stage image regeneration failed")
        await status_msg.edit_text(f"Не получилось перегенерировать фото: {e}")
        return

    pending["stage_images"] = stage_images
    await _send_stage_album(status_msg.chat.id, stage_images)
    await status_msg.edit_text(
        "Новые фото отправлены. Устраивает результат?", reply_markup=_approval_keyboard()
    )


@dp.callback_query(F.data == "approve_video")
async def handle_approve_video(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    pending = _pending_generations.pop(user_id, None)
    if not pending:
        await callback.message.edit_text("Сессия устарела, пришлите фото заново.")
        return

    status_msg = callback.message
    work_dir = pending["work_dir"]
    await status_msg.edit_text("Генерирую видео — это может занять несколько минут…")

    loop = asyncio.get_running_loop()
    try:
        clips = await loop.run_in_executor(
            None, vp.generate_clips, cfg, pending["stages"], pending["stage_images"], work_dir,
            _make_progress_cb(status_msg, loop, "Видео"),
        )
        final_path = os.path.join(work_dir, "final.mp4")
        await loop.run_in_executor(None, vp.stitch_with_crossfade, clips, final_path)
    except Exception as e:
        log.exception("video pipeline failed")
        await status_msg.edit_text(f"Ошибка генерации видео: {e}")
        shutil.rmtree(work_dir, ignore_errors=True)
        return

    await status_msg.edit_text("Готово! Отправляю видео…")
    await bot.send_video(
        chat_id=status_msg.chat.id, video=FSInputFile(final_path), caption="Таймлапс ремонта готов"
    )
    shutil.rmtree(work_dir, ignore_errors=True)


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
