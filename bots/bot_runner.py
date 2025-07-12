import argparse
import json
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from threading import Lock

from shared.logger import logger
from shared.cache import cache

DATA_FILE = Path(__file__).resolve().parent.parent / 'data.json'


def load_config():
    cached = cache.get('config')
    if cached:
        return cached
    with open(DATA_FILE) as f:
        data = json.load(f)
    cache.set('config', data, timeout=60)
    return data


_pool: list[webdriver.Chrome] = []
_lock = Lock()


def init_driver(proxy: str | None = None):
    opts = Options()
    opts.add_argument('--headless')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--disable-extensions')
    opts.add_argument('--start-maximized')
    if proxy:
        opts.add_argument(f'--proxy-server={proxy}')
    return webdriver.Chrome(options=opts)


def get_driver(proxy: str | None = None) -> webdriver.Chrome:
    with _lock:
        if _pool:
            return _pool.pop()
    return init_driver(proxy)


def release_driver(driver: webdriver.Chrome) -> None:
    with _lock:
        _pool.append(driver)


def run_account(account: dict):
    driver = get_driver(account.get('proxy'))
    try:
        logger.info('Logging in %s', account['email'])
        driver.get('https://kick.com/login')
        time.sleep(2)
        driver.find_element(By.NAME, 'email').send_keys(account['email'])
        driver.find_element(By.NAME, 'password').send_keys(account['password'])
        driver.find_element(By.NAME, 'password').send_keys(Keys.RETURN)
        time.sleep(5)  # wait for login

        msg_file = Path('messages') / f"{account['id']}.txt"
        messages = []
        if msg_file.exists():
            with open(msg_file) as f:
                messages = [line.strip() for line in f if line.strip()]
        if not messages:
            messages = ['Hello from KickBot']

        for msg in messages:
            logger.info('Would send message for %s: %s', account['email'], msg)
            # Placeholder for real message sending
            time.sleep(1)
    finally:
        release_driver(driver)


def main(group: str | None = None):
    config = load_config()
    accounts = {acc['id']: acc for acc in config['accounts']}
    account_ids = []
    if group:
        grp = next((g for g in config['groups'] if g['name'] == group), None)
        if not grp:
            raise ValueError(f'Group {group} not found')
        account_ids = grp['accounts']
    else:
        account_ids = list(accounts)

    for aid in account_ids:
        acc = accounts.get(aid)
        if acc:
            run_account(acc)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--group', help='Group name to run')
    args = parser.parse_args()
    main(args.group)
