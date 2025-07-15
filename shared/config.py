import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me")
    DB_PATH: str = os.getenv("DB_PATH", "bots.db")
    REDIS_URL: str | None = os.getenv("REDIS_URL")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "jwt-secret")
    WORKERS: int = int(os.getenv("WORKERS", "50"))
    MAX_INSTANCES: int = int(os.getenv("MAX_INSTANCES", "50"))
    TOTP_SECRET: str | None = os.getenv("TOTP_SECRET")
    KICK_WS_URI: str = os.getenv("KICK_WS_URI", "wss://chat.kick.com")
    SENTRY_DSN: str | None = os.getenv("SENTRY_DSN")
    SLACK_WEBHOOK: str | None = os.getenv("SLACK_WEBHOOK")
    TELEGRAM_TOKEN: str | None = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID: str | None = os.getenv("TELEGRAM_CHAT_ID")


def load_config() -> Config:
    return Config()
