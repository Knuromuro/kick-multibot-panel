import os
import socket
import subprocess
import time

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait


def find_free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    addr, port = s.getsockname()
    s.close()
    return port


def wait_http(url, timeout=10):
    for _ in range(timeout * 10):
        try:
            r = requests.get(url, timeout=1)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"Server not reachable: {url}")


def start_server(port, db_path):
    env = os.environ.copy()
    env["TESTING"] = "1"
    env["DB_PATH"] = str(db_path)
    proc = subprocess.Popen(["python", "run.py", "--port", str(port)], env=env)
    wait_http(f"http://127.0.0.1:{port}/login")
    return proc


def stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_e2e_flow(tmp_path):
    port = find_free_port()
    db_path = tmp_path / "test.db"
    proc = start_server(port, db_path)
    try:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        driver = webdriver.Chrome(options=options)
        driver.get(f"http://127.0.0.1:{port}/login")
        driver.find_element(By.NAME, "username").send_keys("admin")
        driver.find_element(By.NAME, "password").send_keys("admin")
        driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        WebDriverWait(driver, 5).until(lambda d: "/dashboard" in d.current_url)
        driver.find_element(By.ID, "addGroupBtn").click()
        driver.find_element(By.ID, "g-name").send_keys("g1")
        driver.find_element(By.ID, "g-target").send_keys("chan")
        driver.find_element(By.ID, "g-interval").clear()
        driver.find_element(By.ID, "g-interval").send_keys("60")
        driver.find_element(By.CSS_SELECTOR, "#groupForm button").click()
        time.sleep(1)
        table = driver.find_element(By.ID, "groupList")
        assert "g1" in table.text
        driver.find_element(By.ID, "addAccountBtn").click()
        driver.find_element(By.ID, "a-user").send_keys("u")
        driver.find_element(By.ID, "a-pass").send_keys("p")
        driver.find_element(By.ID, "a-group").send_keys("1")
        driver.find_element(By.CSS_SELECTOR, "#accountForm button").click()
        time.sleep(1)
        atable = driver.find_element(By.ID, "accountTable")
        assert "u" in atable.text
    finally:
        driver.quit()
        stop_server(proc)
