import logging
import os
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / 'logs'
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'kickbot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('kickbot')
