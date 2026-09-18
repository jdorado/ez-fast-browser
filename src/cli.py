"""One-shot Ez command client for the private Fast Browser socket."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import uuid
from pathlib import Path
from typing import Any


SOCKET = "/ipc/fast-browser.sock"
VERSION = "0.1.0-beta.8"


def request(command: str, args: dict[str, Any]) -> dict[str, Any]:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(35)
        client.connect(SOCKET)
        client.sendall(json.dumps({"command": command, "args": args}, separators=(",", ":")).encode() + b"\n")
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
    except OSError as exc:
        raise SystemExit(f"Fast Browser service is unavailable: {exc}") from None
    finally:
        client.close()
    try:
        response = json.loads(b"".join(chunks))
    except ValueError:
        raise SystemExit("Fast Browser service returned invalid JSON") from None
    if not response.get("ok"):
        raise SystemExit(response.get("error", "Fast Browser request failed"))
    return response["result"]


def goal(value: str) -> str:
    if value == "-":
        return sys.stdin.read().strip()
    path = Path(value)
    try:
        return path.read_text().strip()
    except OSError as exc:
        raise SystemExit(f"Could not read goal file: {exc}") from None


def main() -> None:
    parser = argparse.ArgumentParser(prog="ez fast-browser")
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("doctor")
    sub.add_parser("configure")
    run = sub.add_parser("run")
    run.add_argument("--mode", required=True, choices=("isolated", "logged-in"))
    run.add_argument("--url", required=True)
    run.add_argument("--goal-file", required=True)
    cont = sub.add_parser("continue")
    cont.add_argument("--session", required=True)
    cont.add_argument("--goal-file", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--session", required=True)
    execute = sub.add_parser("execute")
    execute.add_argument("--session", required=True)
    execute.add_argument("--proposal", required=True)
    close = sub.add_parser("close")
    close.add_argument("--session", required=True)
    args = parser.parse_args()
    if args.version:
        print(VERSION)
        return
    if args.command == "doctor":
        output = request("doctor", {})
    elif args.command == "configure":
        try:
            output = request("configure", {"config": json.load(sys.stdin)})
        except ValueError:
            raise SystemExit("configure expects one JSON object on stdin") from None
    elif args.command == "run":
        text = goal(args.goal_file)
        if not text:
            raise SystemExit("Goal file is empty")
        output = request("run", {"mode": args.mode, "session": uuid.uuid4().hex, "url": args.url, "goal": text})
    elif args.command == "continue":
        text = goal(args.goal_file)
        if not text:
            raise SystemExit("Goal file is empty")
        output = request("continue", {"session": args.session, "goal": text})
    elif args.command == "snapshot":
        output = request("snapshot", {"session": args.session})
    elif args.command == "execute":
        output = request("execute", {"session": args.session, "proposal": args.proposal})
    elif args.command == "close":
        output = request("close", {"session": args.session})
    else:
        parser.print_help()
        raise SystemExit(2)
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
