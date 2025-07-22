import argparse
import asyncio
import json
import os
import time
import websockets

MAX_RETRIES = 3
KICK_URI = os.getenv("KICK_WS_URI", "wss://chat.kick.com")


async def connect(token: str):
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            ws = await websockets.connect(
                KICK_URI,
                extra_headers=headers,
                ping_interval=20,
                ping_timeout=20,
            )
            return ws
        except Exception as exc:
            print(f"connect attempt {attempt} failed: {exc}")
            await asyncio.sleep(2)
    raise RuntimeError("Unable to connect to Kick")


async def send_loop(channel: str, message: str, interval: int, token: str):
    ws = await connect(token)
    payload = json.dumps({"channel": channel, "message": message})
    while True:
        try:
            await ws.send(payload)
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} sent to {channel}")
        except Exception as exc:
            print(f"send error: {exc}")
            ws = await connect(token)
            await ws.send(payload)
        await asyncio.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Simple Kick chat bot")
    parser.add_argument("--channel", required=True, help="Kick channel name")
    parser.add_argument("--message", required=True, help="Message to send")
    parser.add_argument(
        "--interval", type=int, default=600, help="Send interval in seconds"
    )
    parser.add_argument("--token", required=True, help="Kick auth_token")
    args = parser.parse_args()

    try:
        asyncio.run(send_loop(args.channel, args.message, args.interval, args.token))
    except KeyboardInterrupt:
        print("Bot stopped")


if __name__ == "__main__":
    main()
