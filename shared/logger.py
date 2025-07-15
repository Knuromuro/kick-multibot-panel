import logging
from pathlib import Path
from typing import Optional

import requests
import sentry_sdk

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "kickbot.log"), logging.StreamHandler()],
)

logger = logging.getLogger("kickbot")


def get_bot_logger(bot_id: int) -> logging.Logger:
    """Return a logger that writes to logs/bot_<id>.log."""
    name = f"bot_{bot_id}"
    bot_logger = logging.getLogger(name)
    if not bot_logger.handlers:
        fh = logging.FileHandler(LOG_DIR / f"bot_{bot_id}.log")
        bot_logger.addHandler(fh)
        bot_logger.setLevel(logging.INFO)
    return bot_logger


def init_logging(sentry_dsn: Optional[str] = None) -> None:
    """Initialize optional integrations like Sentry."""
    if sentry_dsn:
        sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=0.1)


def notify_webhook(url: str, message: str, params: Optional[dict] = None) -> None:
    """Send a message to a webhook URL."""
    try:
        if params:
            requests.post(url, data=params, timeout=5)
        else:
            requests.post(url, json={"text": message}, timeout=5)
    except Exception:  # noqa: broad-except
        logger.exception("Failed to post to webhook")
