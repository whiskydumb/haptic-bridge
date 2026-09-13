from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from haptic_bridge.cli import Client, DaemonError, DaemonUnreachableError

INSTRUCTIONS = (
    "haptic-bridge drives the user's physical haptic devices. use haptic_pulse only for "
    "moments the user would want to feel (a long task finished, a question needs them); "
    "the daemon already covers permission prompts and end-of-turn on its own."
)


class HapticTools:
    def __init__(self, client: Client) -> None:
        self._client = client

    def haptic_pulse(self, pattern: str = "done", message: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"kind": "custom", "source": "mcp", "pattern": pattern}
        if message:
            body["message"] = message[:500]
        return self._guard(lambda: self._client.post("/event", body))

    def haptic_status(self) -> dict[str, Any]:
        return self._guard(lambda: {**self._client.get("/health"), **self._client.get("/devices")})

    def haptic_halt(self) -> dict[str, Any]:
        return self._guard(lambda: self._client.post("/halt"))

    @staticmethod
    def _guard(call: Any) -> dict[str, Any]:
        try:
            result: dict[str, Any] = call()
        except (DaemonUnreachableError, DaemonError) as exc:
            return {"error": str(exc)}
        return result


def build_server(client: Client) -> MCPServer[None]:
    tools = HapticTools(client)
    server: MCPServer[None] = MCPServer("haptic-bridge", instructions=INSTRUCTIONS)
    server.tool()(tools.haptic_pulse)
    server.tool()(tools.haptic_status)
    server.tool()(tools.haptic_halt)
    return server


def run_mcp(base_url: str, token: str | None) -> int:
    build_server(Client(base_url, token)).run(transport="stdio")
    return 0
