import argparse
import json
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

from shared.logger import logger

DATA_FILE = Path(__file__).resolve().parent.parent / 'data.json'


def load_config():
    with open(DATA_FILE) as f:
        return json.load(f)


def init_driver(proxy: str | None = None):
    opts = Options()
    opts.add_argument('--start-maximized')
    if proxy:
        opts.add_argument(f'--proxy-server={proxy}')
    driver = webdriver.Chrome(options=opts)
    return driver


def run_account(account: dict):
    driver = init_driver(account.get('proxy'))
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
        driver.quit()


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
