import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    telegram_bot_token: str
    openrouter_api_key: str
    video_model: str
    image_model: str
    stage_prompt_model: str
    default_num_stages: int
    clip_duration_sec: int
    generate_audio: bool
    aspect_ratio: str
    resolution: str


def load_config() -> Config:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not token or not key:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and OPENROUTER_API_KEY must be set. "
            "Copy .env.example to .env and fill in your keys."
        )
    return Config(
        telegram_bot_token=token,
        openrouter_api_key=key,
        video_model=os.environ.get("VIDEO_MODEL", "kwaivgi/kling-v3.0-std"),
        image_model=os.environ.get("IMAGE_MODEL", "google/gemini-2.5-flash-image-preview"),
        stage_prompt_model=os.environ.get("STAGE_PROMPT_MODEL", "openai/gpt-4o"),
        default_num_stages=int(os.environ.get("DEFAULT_NUM_STAGES", "7")),
        clip_duration_sec=int(os.environ.get("CLIP_DURATION_SEC", "8")),
        generate_audio=os.environ.get("GENERATE_AUDIO", "false").lower() == "true",
        aspect_ratio=os.environ.get("ASPECT_RATIO", "9:16"),
        resolution=os.environ.get("RESOLUTION", "1080p"),
    )
