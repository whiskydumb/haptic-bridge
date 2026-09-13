from __future__ import annotations

import json
from typing import Any

import aiohttp

from haptic_bridge import __version__
from haptic_bridge.backends.base import BackendError

USER_AGENT = f"haptic-bridge/{__version__}"


class JsonHttp:
    def __init__(
        self,
        backend: str,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        self._backend = backend
        self._base_url = base_url.rstrip("/")
        self._headers = {"User-Agent": USER_AGENT, **(headers or {})}
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._session: aiohttp.ClientSession | None = None

    @property
    def is_open(self) -> bool:
        return self._session is not None

    async def open(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                base_url=self._base_url, headers=self._headers, timeout=self._timeout
            )

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def request(self, method: str, path: str, *, json_body: Any = None) -> tuple[int, Any]:
        await self.open()
        session = self._session
        if session is None:  # pragma: no cover - open() guarantees a session
            raise BackendError(self._backend, "http session is not open")
        try:
            async with session.request(method, path, json=json_body) as response:
                status = response.status
                text = await response.text()
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise BackendError(self._backend, f"{method} {path}: {exc}") from exc
        if not text:
            return status, None
        try:
            return status, json.loads(text)
        except json.JSONDecodeError:
            return status, text
