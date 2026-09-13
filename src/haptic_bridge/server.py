from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import structlog
from aiohttp import web
from aiohttp.typedefs import Handler
from pydantic import BaseModel, Field, ValidationError
from structlog.typing import FilteringBoundLogger

from haptic_bridge import __version__
from haptic_bridge.engine import HapticEngine
from haptic_bridge.events import EventKind, HapticEvent
from haptic_bridge.sources import claude, codex

log: FilteringBoundLogger = structlog.get_logger(__name__)

ENGINE_KEY = web.AppKey("engine", HapticEngine)
TOKEN_KEY = web.AppKey[str | None]("auth_token")

Parser = Callable[[dict[str, Any]], HapticEvent | None]


class EventRequest(BaseModel):
    kind: EventKind
    source: str = Field(default="manual", min_length=1, max_length=64)
    message: str | None = Field(default=None, max_length=500)
    pattern: str | None = Field(default=None, max_length=64)


def create_app(engine: HapticEngine, *, auth_token: str | None = None) -> web.Application:
    app = web.Application(middlewares=[_bearer_auth])
    app[ENGINE_KEY] = engine
    app[TOKEN_KEY] = auth_token
    app.add_routes(
        [
            web.post("/hook/claude", _hook_claude),
            web.post("/hook/codex", _hook_codex),
            web.post("/event", _event),
            web.post("/halt", _halt),
            web.post("/resume", _resume),
            web.get("/health", _health),
            web.get("/devices", _devices),
        ]
    )
    app.on_startup.append(_start_engine)
    app.on_cleanup.append(_close_engine)
    return app


async def _start_engine(app: web.Application) -> None:
    await app[ENGINE_KEY].start()


async def _close_engine(app: web.Application) -> None:
    await app[ENGINE_KEY].close()


@web.middleware
async def _bearer_auth(request: web.Request, handler: Handler) -> web.StreamResponse:
    expected = request.app[TOKEN_KEY]
    if expected is None:
        return await handler(request)
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token, expected):
        raise web.HTTPUnauthorized(text="missing or invalid bearer token")
    return await handler(request)


async def _read_json_object(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(text=f"invalid json: {exc.msg}") from exc
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected a json object")
    return body


async def _dispatch_hook(request: web.Request, parse: Parser) -> web.Response:
    payload = await _read_json_object(request)
    event = parse(payload)
    if event is None:
        log.debug("hook.ignored", hook_event=payload.get("hook_event_name") or payload.get("type"))
    else:
        await request.app[ENGINE_KEY].handle(event)
    return web.json_response({})


async def _hook_claude(request: web.Request) -> web.Response:
    return await _dispatch_hook(request, claude.parse)


async def _hook_codex(request: web.Request) -> web.Response:
    return await _dispatch_hook(request, codex.parse)


async def _event(request: web.Request) -> web.Response:
    payload = await _read_json_object(request)
    try:
        body = EventRequest.model_validate(payload)
    except ValidationError as exc:
        raise web.HTTPBadRequest(
            text=exc.json(include_url=False), content_type="application/json"
        ) from exc
    event = HapticEvent(
        kind=body.kind, source=body.source, message=body.message, pattern=body.pattern
    )
    dispatch = await request.app[ENGINE_KEY].handle(event)
    return web.json_response(asdict(dispatch))


async def _halt(request: web.Request) -> web.Response:
    await request.app[ENGINE_KEY].halt()
    return web.json_response({"enabled": False})


async def _resume(request: web.Request) -> web.Response:
    request.app[ENGINE_KEY].resume()
    return web.json_response({"enabled": True})


async def _health(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]
    return web.json_response(
        {
            "status": "ok",
            "version": __version__,
            "enabled": engine.enabled,
            "backends": engine.backend_names,
            "patterns": engine.pattern_names,
        }
    )


async def _devices(request: web.Request) -> web.Response:
    devices = await request.app[ENGINE_KEY].devices()
    return web.json_response({"devices": [asdict(device) for device in devices]})
