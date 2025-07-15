import argparse
import json
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

from shared.logger import logger
from shared.cache import cache
from .webdriver_pool import get_driver, release_driver

DATA_FILE = Path(__file__).resolve().parent.parent / "data.json"


def load_config():
    cached = cache.get("config")
    if cached:
        return cached
    with open(DATA_FILE) as f:
        data = json.load(f)
    cache.set("config", data, timeout=60)
    return data


BASE_URL = "https://kick.com"


def login(driver: webdriver.Chrome, email: str, password: str) -> None:
    """Perform Kick.com login with retries."""
    for attempt in range(3):
        try:
            driver.get(BASE_URL)
            wait = WebDriverWait(driver, 5)
            login_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "#login-button, button.login")
                )
            )
            login_btn.click()

            email_el = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input#email"))
            )
            pwd_el = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input#password"))
            )
            submit_btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#submit-button"))
            )

            email_el.clear()
            email_el.send_keys(email)
            pwd_el.clear()
            pwd_el.send_keys(password)
            submit_btn.click()

            try:
                accept = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "#accept-cookies"))
                )
                accept.click()
            except Exception:
                pass
            logger.info("login successful for %s", email)
            return
        except Exception as exc:
            logger.warning(
                "login attempt %s failed for %s: %s", attempt + 1, email, exc
            )
            time.sleep(2)
    raise RuntimeError("login failed for %s" % email)


def run_account(account: dict):
    driver = get_driver(account.get("proxy"))
    try:
        logger.info("Logging in %s", account["email"])
        login(driver, account["email"], account["password"])

        msg_file = Path("messages") / f"{account['id']}.txt"
        messages = []
        if msg_file.exists():
            with open(msg_file) as f:
                messages = [line.strip() for line in f if line.strip()]
        if not messages:
            messages = ["Hello from KickBot"]

        for msg in messages:
            logger.info("Would send message for %s: %s", account["email"], msg)
            # Placeholder for real message sending
            time.sleep(1)
    finally:
        release_driver(driver)


def main(group: str | None = None):
    config = load_config()
    accounts = {acc["id"]: acc for acc in config["accounts"]}
    account_ids = []
    if group:
        grp = next((g for g in config["groups"] if g["name"] == group), None)
        if not grp:
            raise ValueError(f"Group {group} not found")
        account_ids = grp["accounts"]
    else:
        account_ids = list(accounts)

    for aid in account_ids:
        acc = accounts.get(aid)
        if acc:
            run_account(acc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", help="Group name to run")
    args = parser.parse_args()
    main(args.group)
