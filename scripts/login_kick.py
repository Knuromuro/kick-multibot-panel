import argparse
import requests

LOGIN_URL = "https://kick.com/api/v1/login"


def login(email: str, password: str) -> str:
    """Attempt to log in and return auth_token."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Login to Kick and print auth_token")
    parser.add_argument("--email", required=True, help="Kick account email")
    parser.add_argument("--password", required=True, help="Kick account password")
    args = parser.parse_args()
    token = login(args.email, args.password)
    print(token)


if __name__ == "__main__":
    main()
