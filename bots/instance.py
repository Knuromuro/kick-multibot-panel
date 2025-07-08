import asyncio
import os
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
import websockets

from shared.logger import get_bot_logger

WS_URI = os.getenv("KICK_WS_URI", "wss://chat.kick.com/channel/{target}")

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
        opts.add_argument('--start-maximized')
        if self.account.proxy:
            opts.add_argument(f'--proxy-server={self.account.proxy}')
        self.driver = webdriver.Chrome(options=opts)

    async def connect(self):
        if self.ws and not self.ws.closed:
            return
        url = WS_URI.format(target=self.group.target)
        for _ in range(3):
            try:
                self.ws = await websockets.connect(url, ping_interval=20, ping_timeout=20)
                return
            except Exception as exc:
                self.log.warning('connect error: %s', exc)
                await asyncio.sleep(5)
        raise ConnectionError('Unable to connect')

    def login(self):
        if self.driver is None:
            self._init_driver()
        d = self.driver
        d.get('https://kick.com/login')
        try:
            accept = d.find_element(By.CSS_SELECTOR, '[aria-label="Accept cookies"]')
            accept.click()
        except Exception:
            pass
        # try several selectors for username and password
        def find_input(cands):
            for c in cands:
                els = d.find_elements(By.CSS_SELECTOR, c)
                if els:
                    return els[0]
            return None
        user = find_input(['input[name=emailOrUsername]', 'input[type=email]', 'input[placeholder*=mail]'])
        pwd = find_input(['input[name=password]', 'input[type=password]'])
        login_btn = find_input(['button[data-testid="login"]', 'button[type=submit]'])
        if user and pwd:
            user.send_keys(self.account.username)
            pwd.send_keys(self.account.password)
            if login_btn:
                login_btn.click()
            else:
                pwd.send_keys(Keys.RETURN)

    async def send_message(self, message: str):
        for attempt in range(2):
            try:
                await self.connect()
                async with self._lock:
                    await self.ws.send(message)
                self.log.info('sent message: %s', message)
                return
            except Exception as exc:
                self.log.warning('send error: %s', exc)
                await self.restart()
        raise ConnectionError('send failed after reconnect')

    async def status_check(self):
        await self.connect()
        return not self.ws.closed

    async def restart(self):
        if self.ws:
            await self.ws.close()
        await self.connect()

    def screenshot(self, folder='screenshots'):
        Path(folder).mkdir(exist_ok=True)
        path = Path(folder) / f'{self.account.id}.png'
        if self.driver:
            self.driver.save_screenshot(str(path))
            self.log.info('saved screenshot %s', path)
        return str(path)

