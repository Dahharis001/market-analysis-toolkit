import asyncio
import functools
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
    Message,
)

import config
import openrouter_client as orc

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("universal-ai-bot")

cfg = config.load_config()
bot = Bot(cfg.telegram_bot_token)
dp = Dispatcher()

# key -> (button label, OpenRouter model slug). Edit/add entries here to change
# what shows up in the menus - nothing else in this file needs to change.
TEXT_MODELS = {
    "gpt5": ("GPT-5", "openai/gpt-5"),
    "claude": ("Claude Opus 4.8", "anthropic/claude-opus-4.8"),
    "gemini": ("Gemini 3 Pro", "google/gemini-3-pro"),
    "grok": ("Grok 4", "x-ai/grok-4"),
    "deepseek": ("DeepSeek V3.2", "deepseek/deepseek-v3.2"),
}
PHOTO_MODELS = {
    "nanobanana": ("Nano Banana", "google/gemini-2.5-flash-image"),
    "nanobanana2": ("Nano Banana 2", "google/gemini-3.1-flash-image"),
    "gptimage": ("GPT Image", "openai/gpt-image-1"),
    "flux": ("FLUX.2 Pro", "black-forest-labs/flux-2-pro"),
    "seedream": ("Seedream 4.5", "bytedance/seedream-4.5"),
}
VIDEO_MODELS = {
    "kling": ("Kling 3.0", "kwaivgi/kling-v3.0-std"),
    "veo": ("Veo 3.1", "google/veo-3.1"),
    "seedance": ("Seedance 2.0", "bytedance/seedance-2.0"),
    "hailuo": ("Hailuo 2.3", "minimax/hailuo-2.3"),
}

# mode -> (menu button label, model catalog for that mode)
MODES = {
    "text": ("💬 Текст", TEXT_MODELS),
    "photo": ("🖼 Фото", PHOTO_MODELS),
    "video": ("🎬 Видео", VIDEO_MODELS),
}

# In-memory per-user session. Fine for a single-process polling bot; would need
# real storage (Redis/db) if this bot is ever scaled to multiple workers.
# user_id -> {"mode": str, "model_label": str, "model_slug": str, "history": list[dict]}
_sessions: dict[int, dict] = {}


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=f"mode:{mode}")]
                          for mode, (label, _) in MODES.items()]
    )


def _model_keyboard(mode: str) -> InlineKeyboardMarkup:
    models = MODES[mode][1]
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"model:{mode}:{key}")]
        for key, (label, _) in models.items()
    ]
    buttons.append([InlineKeyboardButton(text="⬅ Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ Главное меню", callback_data="menu")]])


@dp.message(CommandStart())
async def start(message: Message) -> None:
    _sessions.pop(message.from_user.id, None)
    await message.answer(
        "Привет! Выберите раздел:\n\n"
        "💬 Текст — общение с любой языковой моделью\n"
        "🖼 Фото — генерация изображений (можно приложить своё фото, чтобы отредактировать)\n"
        "🎬 Видео — генерация видео (можно приложить фото - станет первым кадром)\n\n"
        "Каждый запрос расходует баланс на вашем OpenRouter-аккаунте.",
        reply_markup=_main_menu_keyboard(),
    )


@dp.callback_query(F.data == "menu")
async def show_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    _sessions.pop(callback.from_user.id, None)
    await callback.message.edit_text("Выберите раздел:", reply_markup=_main_menu_keyboard())


@dp.callback_query(F.data.startswith("mode:"))
async def choose_mode(callback: CallbackQuery) -> None:
    await callback.answer()
    mode = callback.data.split(":", 1)[1]
    label, _ = MODES[mode]
    await callback.message.edit_text(f"{label} — выберите модель:", reply_markup=_model_keyboard(mode))


@dp.callback_query(F.data.startswith("model:"))
async def choose_model(callback: CallbackQuery) -> None:
    await callback.answer()
    _, mode, key = callback.data.split(":", 2)
    label, slug = MODES[mode][1][key]
    _sessions[callback.from_user.id] = {
        "mode": mode, "model_label": label, "model_slug": slug, "history": [],
    }

    if mode == "text":
        hint = f"Модель выбрана: {label}\n\nПросто напишите сообщение — я отвечу."
    elif mode == "photo":
        hint = (
            f"Модель выбрана: {label}\n\nОпишите текстом, что нарисовать. Можно приложить своё "
            f"фото к сообщению (текст — в подписи), чтобы отредактировать его."
        )
    else:
        hint = (
            f"Модель выбрана: {label}\n\nОпишите текстом, что должно происходить в видео. Можно "
            f"приложить фото (текст — в подписи) — оно станет первым кадром."
        )

    await callback.message.edit_text(hint, reply_markup=_back_keyboard())


@dp.message(F.text | F.photo)
async def handle_input(message: Message) -> None:
    session = _sessions.get(message.from_user.id)
    if not session:
        await message.answer("Сначала выберите раздел и модель.", reply_markup=_main_menu_keyboard())
        return

    prompt = message.caption if message.photo else message.text
    if not prompt:
        await message.answer("Пришлите текстовый запрос (в подписи к фото или отдельным сообщением).")
        return

    mode = session["mode"]
    if mode == "text":
        await _handle_text(message, session, prompt)
    elif mode == "photo":
        await _handle_photo(message, session, prompt)
    else:
        await _handle_video(message, session, prompt)


async def _handle_text(message: Message, session: dict, prompt: str) -> None:
    session["history"].append({"role": "user", "content": prompt})
    status = await message.answer("Думаю…")
    loop = asyncio.get_running_loop()
    try:
        reply = await loop.run_in_executor(
            None, orc.chat_completion, cfg.openrouter_api_key, session["model_slug"], session["history"]
        )
    except Exception as e:
        log.exception("chat completion failed")
        session["history"].pop()
        await status.edit_text(f"Ошибка: {e}")
        return
    session["history"].append({"role": "assistant", "content": reply})
    await status.edit_text(reply)


async def _handle_photo(message: Message, session: dict, prompt: str) -> None:
    status = await message.answer("Генерирую фото…")
    loop = asyncio.get_running_loop()

    with tempfile.TemporaryDirectory() as tmp:
        ref_data_uri = None
        if message.photo:
            ref_path = os.path.join(tmp, "input.jpg")
            await bot.download(message.photo[-1], destination=ref_path)
            ref_data_uri = orc.image_to_data_uri(ref_path)

        try:
            image_data_uri = await loop.run_in_executor(
                None,
                functools.partial(
                    orc.generate_image, cfg.openrouter_api_key, session["model_slug"], prompt, ref_data_uri
                ),
            )
        except Exception as e:
            log.exception("image generation failed")
            await status.edit_text(f"Ошибка: {e}")
            return

        out_path = os.path.join(tmp, "out.png")
        orc.save_data_uri(image_data_uri, out_path)
        await status.delete()
        await message.answer_photo(FSInputFile(out_path))


async def _handle_video(message: Message, session: dict, prompt: str) -> None:
    status = await message.answer("Генерирую видео — это может занять несколько минут…")
    loop = asyncio.get_running_loop()

    with tempfile.TemporaryDirectory() as tmp:
        image_data_uri = None
        if message.photo:
            ref_path = os.path.join(tmp, "input.jpg")
            await bot.download(message.photo[-1], destination=ref_path)
            image_data_uri = orc.image_to_data_uri(ref_path)

        try:
            job_id = await loop.run_in_executor(
                None,
                functools.partial(
                    orc.create_video_job, cfg.openrouter_api_key, session["model_slug"], prompt,
                    image=image_data_uri,
                ),
            )
            video_url = await loop.run_in_executor(
                None, orc.poll_video_job, cfg.openrouter_api_key, job_id
            )
            video_path = os.path.join(tmp, "video.mp4")
            await loop.run_in_executor(
                None,
                functools.partial(orc.download_file, video_url, video_path, api_key=cfg.openrouter_api_key),
            )
        except Exception as e:
            log.exception("video generation failed")
            await status.edit_text(f"Ошибка: {e}")
            return

        await status.edit_text("Готово! Отправляю видео…")
        await message.answer_video(FSInputFile(video_path))


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
