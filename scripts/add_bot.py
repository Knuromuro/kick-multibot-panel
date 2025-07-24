import argparse
import requests


def main():
    parser = argparse.ArgumentParser(
        description="Create a bot via the Kick Multibot API"
    )
    parser.add_argument(
        "--host", default="http://localhost:5000", help="Backend server URL"
    )
    parser.add_argument("--channel", required=True, help="Kick channel name")
    parser.add_argument("--message", required=True, help="Message to send")
    parser.add_argument(
        "--interval", type=int, default=600, help="Send interval in seconds"
    )
    parser.add_argument("--token", required=True, help="Kick auth_token")
    parser.add_argument(
        "--inactive", action="store_true", help="Create bot as inactive"
    )
    args = parser.parse_args()

    data = {
        "channel": args.channel,
        "message": args.message,
        "interval": args.interval,
        "token": args.token,
        "active": not args.inactive,
    }

    resp = requests.post(f"{args.host}/bots", json=data)
    resp.raise_for_status()
    bot_id = resp.json().get("id")
    print(f"Created bot with ID {bot_id}")


if __name__ == "__main__":
    main()
