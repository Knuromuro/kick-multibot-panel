import json
import time
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DATA_FILE = Path(__file__).resolve().parent.parent / "data.json"
CHANNEL_URL = "https://kick.com/trainwreckstv"


def load_accounts() -> list[dict]:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("accounts", [])


def init_driver(proxy: Optional[str] = None) -> webdriver.Chrome:
    opts = Options()
    # headful browser but disable automation banners
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    if proxy:
        opts.add_argument(f"--proxy-server={proxy}")
    driver = webdriver.Chrome(options=opts)
    driver.maximize_window()
    return driver


def login_and_send(account: dict, message: str) -> None:
    driver = init_driver(account.get("proxy"))
    try:
        print(f"[+] Logging in {account['email']}")
        driver.get("https://kick.com")
        wait = WebDriverWait(driver, 10)
        login_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#login-button, button.login"))
        )
        login_btn.click()

        email_el = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[name=emailOrUsername]")
            )
        )
        pwd_el = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[name=password]"))
        )
        submit_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='login']"))
        )

        email_el.clear()
        email_el.send_keys(account["email"])
        pwd_el.clear()
        pwd_el.send_keys(account["password"])
        submit_btn.click()

        # accept cookies if prompted
        try:
            accept = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "button[aria-label='Accept cookies']")
                )
            )
            accept.click()
        except Exception:
            pass

        # wait for avatar or dashboard element
        wait.until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "img[alt='User Avatar'], div[data-testid='user-avatar']",
                )
            )
        )
        print("[+] Login successful")

        driver.get(CHANNEL_URL)
        chat_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "textarea"))
        )
        chat_box.click()
        chat_box.send_keys(message)
        chat_box.send_keys(Keys.ENTER)
        print("[+] Message sent")
        time.sleep(2)
    except Exception as exc:
        print(f"[!] Error for {account['email']}: {exc}")
    finally:
        driver.quit()


def run_all_accounts() -> None:
    accounts = load_accounts()
    for acc in accounts:
        msg_file = Path("messages") / f"{acc['id']}.txt"
        message = "Hello from KickBot"
        if msg_file.exists():
            message = msg_file.read_text().strip() or message
        login_and_send(acc, message)


if __name__ == "__main__":
    run_all_accounts()
