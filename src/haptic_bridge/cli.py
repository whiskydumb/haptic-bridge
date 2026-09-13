from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from haptic_bridge.config import TOKEN_ENV
from haptic_bridge.events import EventKind

URL_ENV = "HAPTIC_BRIDGE_URL"
DEFAULT_URL = "http://127.0.0.1:8787"
REQUEST_TIMEOUT_S = 3.0


class DaemonUnreachableError(Exception): ...


class DaemonError(Exception): ...


class Client:
    def __init__(self, base_url: str, token: str | None) -> None:
        parts = urlsplit(base_url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError(f"daemon url must be http(s)://host[:port], got {base_url!r}")
        self._base = base_url.rstrip("/")
        self._token = token

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", path, body if body is not None else {})

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path, None)

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self._base + path, data=data, method=method)  # noqa: S310
        request.add_header("Content-Type", "application/json")
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:  # noqa: S310
                raw: bytes = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise DaemonError(f"{exc.code} {exc.reason}: {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DaemonUnreachableError(f"daemon unreachable at {self._base}: {exc}") from exc
        parsed: dict[str, Any] = json.loads(raw or b"{}")
        return parsed


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.func
    return handler(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="haptic-bridge",
        description="agent lifecycle events -> haptic feedback on physical devices",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get(URL_ENV, DEFAULT_URL),
        help=f"daemon base url (env {URL_ENV}, default {DEFAULT_URL})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the daemon")
    serve.add_argument("--config", type=Path, default=None, help="path to haptic-bridge.toml")
    serve.add_argument("--json-logs", action="store_true", help="json log lines instead of console")
    serve.set_defaults(func=_cmd_serve)

    emit = sub.add_parser("emit", help="send an event by hand")
    emit.add_argument("kind", choices=[kind.value for kind in EventKind])
    emit.add_argument("--source", default="manual")
    emit.add_argument("--message")
    emit.add_argument("--pattern", help="explicit pattern name; required for kind=custom")
    emit.set_defaults(func=_cmd_emit)

    hook = sub.add_parser("hook", help="forward a hook payload from stdin (command-type hooks)")
    hook.add_argument("source", choices=["claude", "codex"])
    hook.set_defaults(func=_cmd_hook)

    notify = sub.add_parser("codex-notify", help="target for codex `notify`; payload is last argv")
    notify.add_argument("payload", nargs=argparse.REMAINDER)
    notify.set_defaults(func=_cmd_codex_notify)

    mcp = sub.add_parser("mcp", help="serve the mcp tool layer over stdio (needs the mcp extra)")
    mcp.set_defaults(func=_cmd_mcp)

    simple_commands = (("halt", "POST"), ("resume", "POST"), ("devices", "GET"), ("health", "GET"))
    for name, method in simple_commands:
        simple = sub.add_parser(name, help=f"{method} /{name}")
        simple.set_defaults(func=_cmd_simple, endpoint=name, method=method)
    return parser


def _client(args: argparse.Namespace) -> Client:
    return Client(args.url, os.environ.get(TOKEN_ENV))


def _run(call: Callable[[], dict[str, Any]], *, best_effort: bool) -> int:
    try:
        result = call()
    except (DaemonUnreachableError, DaemonError, ValueError) as exc:
        print(f"haptic-bridge: {exc}", file=sys.stderr)
        return 0 if best_effort else 1
    print(json.dumps(result))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from haptic_bridge.daemon import run_daemon

    try:
        return run_daemon(args.config, json_logs=args.json_logs)
    except (FileNotFoundError, ValueError) as exc:
        print(f"haptic-bridge: configuration error: {exc}", file=sys.stderr)
        return 2


def _cmd_mcp(args: argparse.Namespace) -> int:
    try:
        from haptic_bridge.mcp_server import run_mcp
    except ImportError:
        print(
            "haptic-bridge: mcp extra is not installed; run: uv sync --extra mcp", file=sys.stderr
        )
        return 2
    return run_mcp(args.url, os.environ.get(TOKEN_ENV))


def _cmd_emit(args: argparse.Namespace) -> int:
    body = {
        "kind": args.kind,
        "source": args.source,
        "message": args.message,
        "pattern": args.pattern,
    }
    payload = {key: value for key, value in body.items() if value is not None}
    return _run(lambda: _client(args).post("/event", payload), best_effort=False)


def _cmd_hook(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        print(f"haptic-bridge: hook payload is not json: {exc}", file=sys.stderr)
        return 0
    if not isinstance(payload, dict):
        print("haptic-bridge: hook payload must be a json object", file=sys.stderr)
        return 0
    return _run(lambda: _client(args).post(f"/hook/{args.source}", payload), best_effort=True)


def _cmd_codex_notify(args: argparse.Namespace) -> int:
    if not args.payload:
        print("haptic-bridge: codex-notify: no payload argument", file=sys.stderr)
        return 0
    try:
        payload = json.loads(args.payload[-1])
    except json.JSONDecodeError as exc:
        print(f"haptic-bridge: codex-notify: payload is not json: {exc}", file=sys.stderr)
        return 0
    if not isinstance(payload, dict):
        print("haptic-bridge: codex-notify: payload must be a json object", file=sys.stderr)
        return 0
    return _run(lambda: _client(args).post("/hook/codex", payload), best_effort=True)


def _cmd_simple(args: argparse.Namespace) -> int:
    client = _client(args)
    path = f"/{args.endpoint}"
    call = (lambda: client.get(path)) if args.method == "GET" else (lambda: client.post(path))
    return _run(call, best_effort=False)
