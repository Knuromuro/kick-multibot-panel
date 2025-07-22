"""Entry point for the KickBot dashboard and API server with pid handling."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import time
import sys
from pathlib import Path

from backend import create_app, socketio


PID_FILE = Path("run.pid")


def is_running(pid: int) -> bool:
    """Return True if a process with *pid* is running."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def kill_previous() -> None:
    """Terminate any previously running server using the pid file."""
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text())
            if is_running(old_pid):
                print(f"Stopping previous server with pid {old_pid}")
                os.kill(old_pid, signal.SIGTERM)
                for _ in range(20):
                    if not is_running(old_pid):
                        break
                    time.sleep(0.1)
        except Exception as exc:  # noqa: broad-except
            print(f"Failed to stop previous process: {exc}")
        finally:
            PID_FILE.unlink(missing_ok=True)


def write_pid() -> None:
    PID_FILE.write_text(str(os.getpid()))


def cleanup() -> None:
    PID_FILE.unlink(missing_ok=True)


def handle_signal(signum, frame) -> None:  # noqa: D401, ANN001
    """Signal handler to stop the server cleanly."""
    print("Shutting down server...")
    cleanup()
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run KickBot server")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "5000")))
    args = parser.parse_args()

    debug = os.getenv("DEBUG", "true").lower() == "true"

    kill_previous()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Ensure port can be rebound immediately
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((args.host, args.port))
        except OSError as exc:
            if exc.errno == 98:  # Address already in use
                print(f"Port {args.port} in use, falling back to random port")
                args.port = 0
            else:
                raise

    app = create_app()
    write_pid()
    try:
        socketio.run(
            app,
            host=args.host,
            port=args.port,
            debug=debug,
            use_reloader=False,
            allow_unsafe_werkzeug=True,
        )
    finally:
        cleanup()


if __name__ == "__main__":
    main()
