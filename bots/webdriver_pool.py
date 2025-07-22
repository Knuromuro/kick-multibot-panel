from threading import Lock
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import os

_pool: list[webdriver.Chrome] = []
_lock = Lock()
MAX_DRIVERS = int(os.getenv("MAX_DRIVERS", "5"))


def init_driver(proxy: str | None = None) -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    if proxy:
        opts.add_argument(f"--proxy-server={proxy}")
    return webdriver.Chrome(options=opts)


def get_driver(proxy: str | None = None) -> webdriver.Chrome:
    with _lock:
        if _pool:
            return _pool.pop()
    return init_driver(proxy)


def release_driver(driver: webdriver.Chrome) -> None:
    with _lock:
        if len(_pool) < MAX_DRIVERS:
            _pool.append(driver)
        else:
            driver.quit()
