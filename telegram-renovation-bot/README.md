# Telegram Renovation Timelapse Bot

Sends a user's finished-bathroom photo to a vision LLM (via OpenRouter) to write N
renovation-stage prompts, generates a video clip per stage (via OpenRouter's video
generation API), chains them together with first/last-frame image conditioning so the
room stays visually continuous, and stitches everything into one crossfaded timelapse
that ends on a frame matching the user's original photo.

## How it works

1. User sends a photo to the bot, optionally with a number in the caption (e.g. `12`)
   to control how many renovation stages to generate (default set by
   `DEFAULT_NUM_STAGES`, 3-30 allowed).
2. `openrouter_client.generate_stage_prompts` sends the photo + instructions to a
   vision-capable chat model, gets back a JSON array of stage prompts (bare concrete
   shell -> plumbing/electrical -> waterproofing/screed/plaster -> tiling -> ceiling &
   lighting -> fixtures & furniture -> final cleanup with lights on).
3. `video_pipeline.generate_clips` submits one video generation job per stage:
   - Each stage (after the first) is conditioned on the **last frame of the previous
     clip** (extracted locally with `ffmpeg`), so the geometry doesn't jump between
     stages.
   - The **final** stage is additionally conditioned on the user's real reference
     photo as its last-frame target, so the ending matches exactly.
4. `video_pipeline.stitch_with_crossfade` concatenates all clips with a short
   crossfade (`ffmpeg xfade`) into `final.mp4`, which gets sent back to the user.

## Setup

```bash
cd telegram-renovation-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: paste your real TELEGRAM_BOT_TOKEN and OPENROUTER_API_KEY
```

You also need `ffmpeg`/`ffprobe` on PATH (`apt install ffmpeg` / `brew install ffmpeg`).

Run it:

```bash
python bot.py
```

This runs as a long-lived polling process - it needs to keep running somewhere with
steady internet access (your own machine, a VPS, a small Docker container, etc.). It
is **not** meant to run inside an ephemeral cloud dev sandbox.

## Before you run a big batch: test with 1-2 stages first

This code was written in a sandbox where outbound access to `openrouter.ai` was
blocked by network policy, so the video generation request/response field names
(`image`, `last_frame_image`, `duration`, `aspect_ratio`, `resolution`,
`generate_audio` in `openrouter_client.py`) could not be smoke-tested against the
live API - they're taken from OpenRouter's public docs/announcement, but OpenRouter
could use slightly different names. **Send yourself a test photo with caption `3`
first.** If a request is rejected, the bot will show you the full error body from
OpenRouter in the status message - it will tell you exactly which field OpenRouter
didn't like, and the fix is a one-line rename in `create_video_job()` in
`openrouter_client.py`.

## Cost control

Video generation is billed per second of output, per clip, on your OpenRouter
balance. `kwaivgi/kling-v3.0-std` (the model this bot uses) is ~$0.10/sec, so
7 stages x 8s ≈ $5.6, 15 stages x 8s ≈ $12.

Check current pricing at https://openrouter.ai/collections/video-models before a
big run, and consider adding your own per-user rate limiting / an allowlist of
Telegram user IDs in `bot.py` before exposing this bot publicly, since every photo
someone sends spends your OpenRouter balance.

## Security

- `.env` is git-ignored (see repo root `.gitignore`) - never commit real tokens.
- If your Telegram bot token or OpenRouter key were ever pasted into a chat, ticket,
  or shared document, treat them as compromised: regenerate the bot token with
  `/revoke` in @BotFather and roll the OpenRouter key from your OpenRouter dashboard.
