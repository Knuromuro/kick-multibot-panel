import os
import socket
import subprocess
import time
import pytest

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options


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
    driver = None
    try:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        try:
            driver = webdriver.Chrome(options=options)
        except Exception:
            pytest.skip("Chrome not available")
        # obtain tokens via API and store them in localStorage
        r = requests.post(
            f"http://127.0.0.1:{port}/auth/token",
            json={"username": "admin", "password": "admin"},
            timeout=5,
        )
        tokens = r.json()
        driver.get(f"http://127.0.0.1:{port}/login")
        driver.execute_script(
            "localStorage.setItem('accessToken', arguments[0]);"
            "localStorage.setItem('refreshToken', arguments[1]);",
            tokens["access_token"],
            tokens["refresh_token"],
        )
        driver.get(f"http://127.0.0.1:{port}/dashboard")
        headers = {
            "Authorization": f"Bearer {tokens['access_token']}",
            "Content-Type": "application/json",
        }
        r = requests.post(
            f"http://127.0.0.1:{port}/dashboard/api/groups",
            json={"name": "g1", "target": "chan", "interval": 60},
            headers=headers,
            timeout=5,
        )
        assert r.status_code == 201
        gid = r.json()["id"]
        r = requests.post(
            f"http://127.0.0.1:{port}/dashboard/api/accounts",
            json={"username": "u", "password": "p", "group_id": gid},
            headers=headers,
            timeout=5,
        )
        assert r.status_code == 201
    finally:
        if driver:
            driver.quit()
        stop_server(proc)
