"""Host-only bridge for one agent-owned background Chrome tab at a time."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import signal
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Any

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

from runtime import SNAPSHOT_JS, RuntimeErrorSafe, autocomplete_wait_expression, fingerprint, origin


MAX_REQUEST_BYTES = 1_000_000
MAX_TEXT_LENGTH = 2_000


class CompanionError(RuntimeError):
    """An input or Chrome state error that executed no unknown action."""


def require_string(value: Any, name: str, *, maximum: int = 2_000) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise CompanionError(f"{name} must be a non-empty string.")
    return value


class LocalTab:
    def __init__(self, session_id: str, allowed_origins: tuple[str, ...], target: str, protocol_session: str):
        self.session_id = session_id
        self.allowed_origins = allowed_origins
        self.target = target
        self.protocol_session = protocol_session
        self.page: dict[str, Any] = {}

    @classmethod
    def start(cls, session_id: str, url: str, allowed_origins: tuple[str, ...]) -> "LocalTab":
        if origin(url) not in allowed_origins:
            raise CompanionError("The requested URL is outside this companion's allowlist.")
        ensure_daemon()
        target = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
        protocol_session = cdp("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
        tab = cls(session_id, allowed_origins, target, protocol_session)
        try:
            tab.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)
            tab.call("Emulation.setFocusEmulationEnabled", enabled=True)
            tab.call("Page.navigate", url=url)
            tab.wait_complete()
            tab.page = tab.observe()
            return tab
        except Exception:
            tab.close()
            raise

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        try:
            return cdp(method, session_id=self.protocol_session, **params)
        except RuntimeError as exc:
            raise CompanionError("Chrome rejected the bounded companion operation.") from exc

    def evaluate(self, expression: str) -> Any:
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        if response.get("exceptionDetails"):
            raise CompanionError("The page changed during a guarded companion operation.")
        return response.get("result", {}).get("value")

    def wait_complete(self) -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if self.evaluate("document.readyState") == "complete":
                    return
            except CompanionError:
                pass
            time.sleep(0.05)

    def observe(self) -> dict[str, Any]:
        page = self.evaluate(SNAPSHOT_JS)
        if not isinstance(page, dict):
            raise CompanionError("The Chrome page could not be observed safely.")
        try:
            current_origin = origin(page["url"])
        except (KeyError, RuntimeErrorSafe) as exc:
            raise CompanionError("The Chrome page has no safe observable origin.") from exc
        if current_origin not in self.allowed_origins:
            raise CompanionError("Chrome navigated outside the explicit allowlist; no further action was taken.")
        page["fingerprint"] = fingerprint(page)
        return page

    def fresh(self, marker: Any) -> bool:
        if not isinstance(marker, str):
            return False
        return self.evaluate("window.__ezFastBrowser?.marker || null") == marker

    def act(self, marker: Any, action: Any, text: Any) -> None:
        if not self.fresh(marker):
            raise CompanionError("The Chrome page changed after the decision; no action was taken.")
        if not isinstance(action, dict):
            raise CompanionError("The companion action is invalid.")
        kind = action.get("kind")
        if kind == "wait":
            time.sleep(0.15)
            return
        if kind == "scroll":
            direction = action.get("direction")
            if not isinstance(direction, int) or abs(direction) > 1_600:
                raise CompanionError("The companion scroll action is invalid.")
            self.call("Input.dispatchMouseEvent", type="mouseWheel", x=560, y=650, deltaX=0, deltaY=direction)
            time.sleep(0.1)
            return
        if kind not in {"click", "fill", "select"} or not isinstance(action.get("node"), int):
            raise CompanionError("The companion action did not reference an observed element.")
        if kind == "fill" and (not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_LENGTH):
            raise CompanionError("No bounded text value was supplied; nothing was typed.")
        target = self.evaluate("""(action => {
          const e = window.__ezFastBrowser?.nodes.get(action.node);
          if (!e?.isConnected || e.matches(':disabled, [aria-disabled=\"true\"], [inert]')) return null;
          const r = e.getBoundingClientRect(), style = getComputedStyle(e), x = r.x + r.width / 2, y = r.y + r.height / 2;
          if (!r.width || !r.height || x < 0 || y < 0 || x >= innerWidth || y >= innerHeight || style.visibility === 'hidden' || style.display === 'none') return null;
          if (action.kind === 'fill' && (e.readOnly || e.getAttribute('aria-readonly') === 'true')) return null;
          if (action.kind === 'select') {
            if (e.tagName !== 'SELECT' || ![...e.options].some(o => o.value === action.value && !o.disabled)) return null;
            e.value = action.value;
            e.dispatchEvent(new Event('input', {bubbles: true}));
            e.dispatchEvent(new Event('change', {bubbles: true}));
            return {x, y};
          }
          return e.contains(document.elementFromPoint(x, y)) ? {x, y} : null;
        })""" + "(" + json.dumps(action, separators=(",", ":")) + ")")
        if not isinstance(target, dict):
            raise CompanionError("The observed Chrome target changed or is covered; no action was taken.")
        if kind != "select":
            for event in ("mousePressed", "mouseReleased"):
                self.call("Input.dispatchMouseEvent", type=event, x=target["x"], y=target["y"], button="left", clickCount=1)
        if kind == "fill":
            self.call("Input.dispatchKeyEvent", type="keyDown", key="a", code="KeyA", modifiers=4, commands=["selectAll"])
            self.call("Input.dispatchKeyEvent", type="keyUp", key="a", code="KeyA", modifiers=4)
            self.call("Input.insertText", text=text)
            try:
                self.call("Runtime.evaluate", expression=autocomplete_wait_expression(action["node"]), awaitPromise=True, returnByValue=True)
            except CompanionError:
                pass
        time.sleep(0.1)

    def close(self) -> None:
        if not self.target:
            return
        try:
            cdp("Target.closeTarget", targetId=self.target)
        except RuntimeError:
            pass
        self.target = ""


class Companion:
    def __init__(self, token: str):
        self.token = token
        self.sessions: dict[str, LocalTab] = {}
        self.lock = threading.RLock()

    def dispatch(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) != {"token", "command", "args"} or not isinstance(payload["args"], dict):
            raise CompanionError("Invalid companion request.")
        supplied = payload["token"]
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, self.token):
            raise CompanionError("Companion authentication failed.")
        command, args = payload["command"], payload["args"]
        with self.lock:
            if command == "health" and not args:
                return {"ready": True}
            if command == "start" and set(args) == {"session", "url", "origins"}:
                session_id = require_string(args["session"], "session", maximum=128)
                if session_id in self.sessions:
                    raise CompanionError("This local Chrome session already exists.")
                if not isinstance(args["origins"], list) or not args["origins"] or not all(isinstance(item, str) and origin(item) == item for item in args["origins"]):
                    raise CompanionError("Invalid local Chrome allowlist.")
                tab = LocalTab.start(session_id, require_string(args["url"], "url"), tuple(args["origins"]))
                self.sessions[session_id] = tab
                return {"page": tab.page}
            if command in {"observe", "fresh", "act", "close"}:
                session_id = require_string(args.get("session"), "session", maximum=128)
                tab = self.sessions.get(session_id)
                if not tab:
                    raise CompanionError("The local Chrome session is unavailable.")
                if command == "observe" and set(args) == {"session"}:
                    tab.page = tab.observe()
                    return {"page": tab.page}
                if command == "fresh" and set(args) == {"session", "marker"}:
                    return {"fresh": tab.fresh(args["marker"])}
                if command == "act" and set(args) == {"session", "marker", "action", "text"}:
                    tab.act(args["marker"], args["action"], args["text"])
                    return {"executed": True}
                if command == "close" and set(args) == {"session"}:
                    self.sessions.pop(session_id, None)
                    tab.close()
                    return {"closed": True}
            raise CompanionError("Unknown or invalid companion command.")

    def close(self) -> None:
        with self.lock:
            for tab in self.sessions.values():
                tab.close()
            self.sessions.clear()


class RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
            if not raw or len(raw) > MAX_REQUEST_BYTES:
                raise CompanionError("Invalid companion request size.")
            result = self.server.companion.dispatch(json.loads(raw))  # type: ignore[attr-defined]
            response = {"ok": True, "result": result}
        except (CompanionError, RuntimeErrorSafe, ValueError, TypeError, KeyError) as exc:
            response = {"ok": False, "error": str(exc)}
        except Exception:
            response = {"ok": False, "error": "The local Chrome companion failed safely."}
        self.wfile.write(json.dumps(response, separators=(",", ":")).encode() + b"\n")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], companion: Companion):
        super().__init__(address, RequestHandler)
        self.companion = companion


def read_token(path: Path) -> str:
    try:
        mode = path.stat().st_mode & 0o777
        token = path.read_text().strip()
    except OSError as exc:
        raise SystemExit(f"Could not read companion token: {exc}") from None
    if mode & 0o077 or len(token) < 32:
        raise SystemExit("Companion token must be private and at least 32 characters.")
    return token


def initialize_token(path: Path) -> None:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as token_file:
            token_file.write(secrets.token_urlsafe(48) + "\n")
    except FileExistsError:
        raise SystemExit("Companion token already exists; refusing to replace it.") from None
    except OSError as exc:
        raise SystemExit(f"Could not initialize companion token: {exc}") from None
    print("Companion token initialized.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--initialize-token", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9230)
    args = parser.parse_args()
    if args.host != "127.0.0.1" or not 1024 <= args.port <= 65535:
        raise SystemExit("Companion must listen on one unprivileged loopback port.")
    token_path = Path(args.token_file)
    if args.initialize_token:
        initialize_token(token_path)
        return
    companion = Companion(read_token(token_path))
    server = Server((args.host, args.port), companion)
    def shutdown(*_: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        companion.close()
        server.server_close()


if __name__ == "__main__":
    main()
