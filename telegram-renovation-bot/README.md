# Telegram Renovation Timelapse Bot

Sends a user's finished-bathroom photo to a vision LLM (via OpenRouter) to write N
renovation-stage prompts, renders one AI still image per stage (image-to-image edit,
anchored on the reference photo), sends that album to the user, then generates a video
clip per stage keyframed between consecutive stage images, and stitches everything
into one crossfaded timelapse that ends on a frame matching the user's original photo.

## How it works

1. User sends a photo to the bot, optionally with a number in the caption (e.g. `12`)
   to control how many renovation stages to generate (default set by
   `DEFAULT_NUM_STAGES`, 3-30 allowed).
2. `openrouter_client.generate_stage_prompts` sends the photo + instructions to a
   vision-capable chat model, gets back a JSON array of stage prompts (bare concrete
   shell -> plumbing/electrical -> waterproofing/screed/plaster -> tiling -> ceiling &
   lighting -> fixtures & furniture -> final cleanup with lights on).
3. `image_pipeline.generate_stage_images` renders one AI still photo per stage
   (`openrouter_client.generate_stage_image`, an image-edit call anchored on the
   reference photo so the camera angle/room geometry stay consistent). The last
   "stage image" is always the user's real photo, unmodified. All of these are sent
   to the user as a Telegram photo album before any video is generated, so they can
   see the direction before it costs video money.
4. `video_pipeline.generate_clips` submits one video generation job per stage,
   keyframed with `image` = previous stage's still and `last_frame_image` = this
   stage's still - i.e. each clip animates from one AI-designed keyframe to the
   next, rather than drifting off whatever the previous clip happened to render.
5. `video_pipeline.stitch_with_crossfade` concatenates all clips with a short
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
blocked by network policy, so neither the image generation call
(`generate_stage_image` - request uses `modalities: ["image","text"]`, response is
read from `message.images[0].image_url.url`) nor the video generation fields
(`image`, `last_frame_image`, `duration`, `aspect_ratio`, `resolution`,
`generate_audio` in `create_video_job`) could be smoke-tested against the live API.
They're taken from OpenRouter's public docs/announcement, but OpenRouter could use
slightly different names. **Send yourself a test photo with caption `3` first.** If
a request is rejected, the bot shows you the full error body from OpenRouter in the
status message - it will tell you exactly which field it didn't like, and the fix is
a one-line rename in `openrouter_client.py`.

## Cost control

Both APIs bill per call on your OpenRouter balance:

- **Images**: one `IMAGE_MODEL` call per stage except the last (N-1 calls total).
  Gemini 2.5 Flash Image is cheap per image (well under $0.10 typically) - check
  current pricing at https://openrouter.ai/collections/image-models.
- **Video**: billed per second of output, per clip. `kwaivgi/kling-v3.0-std` (the
  model this bot uses) is ~$0.10/sec, so 7 stages x 8s ≈ $5.6, 15 stages x 8s ≈ $12.
  Check current pricing at https://openrouter.ai/collections/video-models.

Consider adding your own per-user rate limiting / an allowlist of Telegram user IDs
in `bot.py` before exposing this bot publicly, since every photo someone sends
spends your OpenRouter balance.

## Security

- `.env` is git-ignored (see repo root `.gitignore`) - never commit real tokens.
- If your Telegram bot token or OpenRouter key were ever pasted into a chat, ticket,
  or shared document, treat them as compromised: regenerate the bot token with
  `/revoke` in @BotFather and roll the OpenRouter key from your OpenRouter dashboard.
