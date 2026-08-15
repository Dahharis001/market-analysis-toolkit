# Telegram Universal AI Bot

A menu-driven Telegram bot that gives access to several OpenRouter models across
three modes - text chat, photo generation, and video generation - picked with
inline buttons. Independent of `telegram-renovation-bot` in this repo: separate
process, separate bot token, separate `.env`, no shared state.

## How it works

1. `/start` shows the main menu: 💬 Текст / 🖼 Фото / 🎬 Видео.
2. Picking a mode shows that mode's model list (`TEXT_MODELS` / `PHOTO_MODELS` /
   `VIDEO_MODELS` in `bot.py`). Picking a model stores it in an in-memory
   per-user session and the bot waits for input.
3. From then on, every text message (or photo with a caption) is sent straight
   to the chosen model until the user taps "⬅ Главное меню":
   - **Text**: `openrouter_client.chat_completion` with a rolling per-user
     message history (multi-turn).
   - **Photo**: `openrouter_client.generate_image` - text-to-image, or
     image-to-image edit if a photo was attached.
   - **Video**: `openrouter_client.create_video_job` + `poll_video_job` +
     `download_file` - text-to-video, or image-to-video if a photo was
     attached (used as the first frame).

## Adding/removing models

Edit the `TEXT_MODELS` / `PHOTO_MODELS` / `VIDEO_MODELS` dicts at the top of
`bot.py` - each entry is `"key": ("Button label", "openrouter/model-slug")`.
Nothing else needs to change.

**Model slugs were not live-tested** (outbound access to openrouter.ai was
blocked while this was written) - if a model 404s with "No endpoints found for
X", look up the correct current slug at openrouter.ai/models and fix that one
dict entry. The sibling `telegram-renovation-bot` project hit and fixed this
exact issue for `google/gemini-2.5-flash-image` (the `-preview` suffix had to
be dropped once the model went GA) - same class of fix here if needed.

## Deploy on the same VPS as telegram-renovation-bot

```bash
cd ~/market-analysis-toolkit/telegram-universal-ai-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # different TELEGRAM_BOT_TOKEN than the renovation bot!
python bot.py   # manual test, Ctrl+C to stop
```

Then set up a separate systemd unit (e.g. `universal-ai-bot.service`) the same
way as `renovation-bot.service`, pointing `WorkingDirectory`/`ExecStart` at
this folder's `.venv`.
