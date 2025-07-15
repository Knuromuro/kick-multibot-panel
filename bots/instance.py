import asyncio
import os
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import websockets

from shared.logger import get_bot_logger

WS_URI = os.getenv("KICK_WS_URI", "wss://chat.kick.com/channel/{target}")
BASE_URL = "https://kick.com"


class BotInstance:
    """Represents a single Kick bot account."""

    def __init__(self, account, group):
        self.account = account
        self.group = group
        self.driver: Optional[webdriver.Chrome] = None
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.log = get_bot_logger(account.id)
        self._lock = asyncio.Lock()

    def _init_driver(self):
        opts = Options()
        opts.add_argument("--headless")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--start-maximized")
        if self.account.proxy:
            opts.add_argument(f"--proxy-server={self.account.proxy}")
        self.driver = webdriver.Chrome(options=opts)

    async def connect(self):
        if self.ws and not self.ws.closed:
            return
        url = WS_URI.format(target=self.group.target)
        for _ in range(3):
            try:
                self.ws = await websockets.connect(
                    url, ping_interval=20, ping_timeout=20
                )
                return
            except Exception as exc:
                self.log.warning("connect error: %s", exc)
                await asyncio.sleep(5)
        raise ConnectionError("Unable to connect")

    def login(self):
        if self.driver is None:
            self._init_driver()
        d = self.driver
        d.delete_all_cookies()
        try:
            d.execute_script("window.localStorage.clear();")
        except Exception:
            pass
        for attempt in range(3):
            try:
                d.get(BASE_URL)
                wait = WebDriverWait(d, 5)
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
                email_el.send_keys(self.account.username)
                pwd_el.clear()
                pwd_el.send_keys(self.account.password)
                submit_btn.click()

                try:
                    accept = WebDriverWait(d, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "#accept-cookies"))
                    )
                    accept.click()
                except Exception:
                    pass
                self.log.info("login successful")
                return
            except Exception as exc:
                self.log.warning("login attempt %s failed: %s", attempt + 1, exc)
                time.sleep(2)
        self.log.error("login failed after retries")
        raise RuntimeError("login failed")

    async def send_message(self, message: str):
        for attempt in range(2):
            try:
                await self.connect()
                async with self._lock:
                    await self.ws.send(message)
                self.log.info("sent message: %s", message)
                return
            except Exception as exc:
                self.log.warning("send error: %s", exc)
                await self.restart()
        raise ConnectionError("send failed after reconnect")

    async def status_check(self):
        await self.connect()
        return not self.ws.closed

    async def restart(self):
        if self.ws:
            await self.ws.close()
        await self.connect()

    def screenshot(self, folder="screenshots"):
        Path(folder).mkdir(exist_ok=True)
        path = Path(folder) / f"{self.account.id}.png"
        if self.driver:
            self.driver.save_screenshot(str(path))
            self.log.info("saved screenshot %s", path)
        return str(path)
