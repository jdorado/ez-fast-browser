"""Private long-lived service for fast-browser sessions and receipts."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from runtime import BrowserSession, DesktopCompanion, DesktopSession, RuntimeErrorSafe, origin, receipt, run_goal, session_snapshot


STATE = Path("/state")
CONFIG = STATE / "config.json"
RECEIPTS = STATE / "receipts"
SOCKET = Path("/ipc/fast-browser.sock")
SESSIONS: dict[str, BrowserSession] = {}


def read_config() -> dict[str, Any]:
    try:
        value = json.loads(CONFIG.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise RuntimeErrorSafe("Fast Browser configuration is unreadable.") from None
    if not isinstance(value, dict):
        raise RuntimeErrorSafe("Fast Browser configuration is invalid.")
    return value


def configured_origins(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 12 or not all(isinstance(item, str) for item in value):
        raise RuntimeErrorSafe("loggedInOrigins must be a non-empty list of up to twelve explicit origins.")
    normalized = sorted({origin(item) for item in value})
    if any(item not in value for item in normalized):
        raise RuntimeErrorSafe("loggedInOrigins entries must be bare origins without paths, queries, or fragments.")
    return normalized


def configure(value: Any) -> dict[str, Any]:
    allowed = {"typesafeApiKey", "typesafeModel", "textApiKey", "textModel", "textBaseUrl", "desktopCompanionToken", "loggedInOrigins"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise RuntimeErrorSafe("Configuration accepts only TypeSafe and text-helper settings.")
    if not isinstance(value.get("typesafeApiKey"), str) or not value["typesafeApiKey"].strip():
        raise RuntimeErrorSafe("typesafeApiKey is required.")
    for key in ("typesafeModel", "textApiKey", "textModel", "textBaseUrl", "desktopCompanionToken"):
        if key in value and (not isinstance(value[key], str) or not value[key].strip()):
            raise RuntimeErrorSafe(f"{key} must be a non-empty string when supplied.")
    if "loggedInOrigins" in value:
        value = {**value, "loggedInOrigins": configured_origins(value["loggedInOrigins"])}
    if ("desktopCompanionToken" in value) != ("loggedInOrigins" in value):
        raise RuntimeErrorSafe("desktopCompanionToken and loggedInOrigins must be configured together.")
    STATE.mkdir(mode=0o700, exist_ok=True)
    temp = CONFIG.with_suffix(".tmp")
    temp.write_text(json.dumps(value, separators=(",", ":")))
    os.chmod(temp, 0o600)
    temp.replace(CONFIG)
    return {"configured": True, "typesafe": True, "textHelper": bool(value.get("textApiKey")), "loggedInConfigured": bool(value.get("desktopCompanionToken"))}


def doctor() -> dict[str, Any]:
    config = read_config()
    chromium = shutil.which("chromium")
    version = None
    if chromium:
        try:
            version = subprocess.check_output([chromium, "--version"], text=True, timeout=5).strip()
        except (OSError, subprocess.SubprocessError):
            chromium = None
    companion = DesktopCompanion(config["desktopCompanionToken"]) if config.get("desktopCompanionToken") else None
    desktop_ready = bool(companion and config.get("loggedInOrigins") and companion.healthy())
    return {
        "configured": bool(config.get("typesafeApiKey")),
        "typesafe": bool(config.get("typesafeApiKey")),
        "textHelper": bool(config.get("textApiKey")),
        "isolated": {"ready": bool(chromium and config.get("typesafeApiKey")), "chromium": version},
        "loggedIn": {
            "ready": desktop_ready,
            "origins": config.get("loggedInOrigins", []),
            "reason": None if desktop_ready else "Desktop companion is not bound or its Chrome remote-debugging consent is unavailable.",
        },
        "activeSessions": len(SESSIONS),
    }


def save_receipt(value: dict[str, Any]) -> None:
    RECEIPTS.mkdir(mode=0o700, exist_ok=True)
    path = RECEIPTS / f"{value['session']}.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, separators=(",", ":")))
    os.chmod(temp, 0o600)
    temp.replace(path)


def uncertain_after_action(browser: BrowserSession) -> dict[str, Any]:
    """Record a mutating action whose final observation could not be trusted."""
    final = receipt(
        browser,
        "uncertain",
        detail="An action may have executed, but its post-action observation failed.",
    )
    save_receipt(final)
    SESSIONS.pop(browser.session_id, None)
    browser.close()
    return {"receipt": final, "sessionClosed": True}


def stopped_after_confirmed_action(browser: BrowserSession) -> dict[str, Any]:
    """Close after a later planning failure, without labelling a read-back action uncertain."""
    final = receipt(
        browser,
        "blocked",
        detail="A later planning step was unavailable after the prior browser action was read back.",
    )
    save_receipt(final)
    SESSIONS.pop(browser.session_id, None)
    browser.close()
    return {"receipt": final, "sessionClosed": True}


def safe_failure(browser: BrowserSession) -> dict[str, Any]:
    if browser.history and browser.history[-1].get("page_changed") is None:
        return uncertain_after_action(browser)
    return stopped_after_confirmed_action(browser)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    mode = payload.get("mode")
    if mode not in {"isolated", "logged-in"}:
        raise RuntimeErrorSafe("mode must be isolated or logged-in.")
    config = read_config()
    if not config.get("typesafeApiKey"):
        raise RuntimeErrorSafe("Run configure before starting a browser session.")
    browser = BrowserSession.start(payload["session"], payload["url"]) if mode == "isolated" else DesktopSession.start(payload["session"], payload["url"], config)
    SESSIONS[browser.session_id] = browser
    try:
        result = run_goal(config, browser, payload["goal"])
    except Exception:
        if browser.history:
            return safe_failure(browser)
        browser.close()
        SESSIONS.pop(browser.session_id, None)
        raise
    save_receipt(result)
    return {"receipt": result, "snapshot": session_snapshot(browser)}


def continue_run(payload: dict[str, Any]) -> dict[str, Any]:
    browser = SESSIONS.get(payload["session"])
    if not browser:
        raise RuntimeErrorSafe("Session is unavailable. Start a new session; no browser state was recovered.")
    try:
        result = run_goal(read_config(), browser, payload["goal"])
    except Exception:
        if browser.history:
            return safe_failure(browser)
        raise
    save_receipt(result)
    return {"receipt": result, "snapshot": session_snapshot(browser)}


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    browser = SESSIONS.get(payload["session"])
    if not browser or not browser.pending:
        raise RuntimeErrorSafe("No pending proposal exists for this session.")
    pending = browser.pending
    if payload.get("proposal") != pending["proposal"] or pending["fingerprint"] != browser.page.get("fingerprint") or not browser.fresh(browser.page):
        browser.pending = None
        raise RuntimeErrorSafe("Proposal is stale or mismatched; no browser action was executed.")
    browser.pending = None
    try:
        result = run_goal(read_config(), browser, pending["goal"], approved=True)
    except Exception:
        if browser.history:
            return safe_failure(browser)
        raise
    save_receipt(result)
    return {"receipt": result, "snapshot": session_snapshot(browser)}


def close(payload: dict[str, Any]) -> dict[str, Any]:
    browser = SESSIONS.pop(payload["session"], None)
    if not browser:
        return {"closed": False, "detail": "Session was already unavailable."}
    final = receipt(browser, "closed")
    save_receipt(final)
    browser.close()
    return {"closed": True, "receipt": final}


def dispatch(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"command", "args"} or not isinstance(payload["args"], dict):
        raise RuntimeErrorSafe("Invalid plugin request.")
    command, args = payload["command"], payload["args"]
    if command == "doctor":
        return doctor()
    if command == "configure":
        return configure(args.get("config"))
    if command == "run":
        if set(args) != {"mode", "session", "url", "goal"} or not all(isinstance(args[key], str) for key in args):
            raise RuntimeErrorSafe("Invalid run request.")
        return run(args)
    if command == "continue":
        if set(args) != {"session", "goal"} or not all(isinstance(args[key], str) for key in args):
            raise RuntimeErrorSafe("Invalid continue request.")
        return continue_run(args)
    if command == "snapshot":
        if set(args) != {"session"} or not isinstance(args["session"], str):
            raise RuntimeErrorSafe("Invalid snapshot request.")
        browser = SESSIONS.get(args["session"])
        if not browser:
            raise RuntimeErrorSafe("Session is unavailable.")
        browser.page = browser.observe()
        return session_snapshot(browser)
    if command == "execute":
        if set(args) != {"session", "proposal"} or not all(isinstance(args[key], str) for key in args):
            raise RuntimeErrorSafe("Invalid execute request.")
        return execute(args)
    if command == "close":
        if set(args) != {"session"} or not isinstance(args["session"], str):
            raise RuntimeErrorSafe("Invalid close request.")
        return close(args)
    raise RuntimeErrorSafe("Unknown fast-browser command.")


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        line = await reader.readline()
        payload = json.loads(line)
        result = dispatch(payload)
        response = {"ok": True, "result": result}
    except (RuntimeErrorSafe, KeyError, TypeError, ValueError) as exc:
        response = {"ok": False, "error": str(exc)}
    except Exception:
        response = {"ok": False, "error": "Fast Browser failed before a safe result could be returned."}
    writer.write(json.dumps(response, separators=(",", ":")).encode() + b"\n")
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def serve() -> None:
    SOCKET.parent.mkdir(mode=0o700, exist_ok=True)
    SOCKET.unlink(missing_ok=True)
    server = await asyncio.start_unix_server(handle, path=str(SOCKET))
    os.chmod(SOCKET, 0o600)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args()
    if args.health:
        if SOCKET.exists():
            print("ready")
            return
        raise SystemExit("Fast Browser socket is not ready")
    asyncio.run(serve())


if __name__ == "__main__":
    main()
