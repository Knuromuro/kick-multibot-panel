import logging
from pathlib import Path

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
