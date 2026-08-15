import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    telegram_bot_token: str
    openrouter_api_key: str


def load_config() -> Config:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not token or not key:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and OPENROUTER_API_KEY must be set. "
            "Copy .env.example to .env and fill in your keys."
        )
    return Config(telegram_bot_token=token, openrouter_api_key=key)
