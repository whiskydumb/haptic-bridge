from __future__ import annotations

from pathlib import Path

import structlog
from aiohttp import web
from structlog.typing import FilteringBoundLogger

from haptic_bridge.backends.registry import build_backends
from haptic_bridge.config import load_config
from haptic_bridge.engine import HapticEngine
from haptic_bridge.log import configure_logging
from haptic_bridge.server import create_app

log: FilteringBoundLogger = structlog.get_logger(__name__)


def run_daemon(config_path: Path | None, *, json_logs: bool = False) -> int:
    configure_logging(json=json_logs)
    config = load_config(config_path)
    backends = build_backends(config.backends)
    engine = HapticEngine(config.engine, config.patterns, config.events, backends)
    token = config.resolved_token()
    app = create_app(engine, auth_token=token)
    log.info(
        "daemon.listening",
        host=config.server.host,
        port=config.server.port,
        backends=engine.backend_names,
        auth="bearer" if token else "none",
    )
    web.run_app(app, host=config.server.host, port=config.server.port, print=None, access_log=None)
    return 0
