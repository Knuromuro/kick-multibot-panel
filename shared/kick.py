import requests

LOGIN_URL = "https://kick.com/api/v1/login"


def login(email: str, password: str) -> str:
    """Return auth_token for the given Kick credentials."""
    session = requests.Session()
    resp = session.post(
        LOGIN_URL,
        json={"email": email, "password": password},
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()
    token = session.cookies.get("auth_token") or resp.json().get("token")
    if not token:
        raise RuntimeError("auth_token not found in response")
    return token
