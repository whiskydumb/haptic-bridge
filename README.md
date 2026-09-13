# haptic-bridge

Local daemon that turns coding-agent lifecycle events (Claude Code, Codex CLI) into haptic
feedback on physical devices: "needs permission", "asks a question", "finished the turn".

```
Claude Code - hooks (http) ────┐
Codex CLI   - notify / hooks ──┤
any MCP client - haptic_pulse ─┤
manual - POST /event ──────────┤
                                ▼
            haptic-bridge  http://127.0.0.1:8787
            event → pattern mapping, cooldown, intensity cap, kill switch
                                │
          ┌──────────┬──────────┼──────────┬──────────┐
        mock     dualsense   openshock   lovense   (buttplug: planned)
```

## setup

```bash
uv sync --all-extras
cp haptic-bridge.example.toml haptic-bridge.toml
uv run haptic-bridge serve
```

`haptic-bridge.toml` is git-ignored because it may carry tokens. Without a config file the
daemon runs with built-in defaults and the `mock` backend only. `just` lists the project tasks.

## agents

### claude code

Add `http` hooks to `~/.claude/settings.json` (every project) or to `.claude/settings.json`
of a single project, then restart Claude Code:

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "permission_prompt|idle_prompt|agent_needs_input|elicitation_dialog",
        "hooks": [{ "type": "http", "url": "http://127.0.0.1:8787/hook/claude", "timeout": 2 }]
      }
    ],
    "Stop": [
      { "hooks": [{ "type": "http", "url": "http://127.0.0.1:8787/hook/claude", "timeout": 2 }] }
    ]
  }
}
```

HTTP hooks post the hook payload as JSON and block until the daemon answers, so the daemon
replies immediately and plays the pattern in the background.

### codex cli

`notify` fires once per completed turn and passes the payload as the last argv element.
Install the CLI on PATH (`uv tool install .` from this directory), then:

```toml
# ~/.codex/config.toml
notify = ["haptic-bridge", "codex-notify"]
```

Codex lifecycle hooks (`[features] hooks = true`) can pipe their stdin payload through
`haptic-bridge hook codex` for `Stop` and `PermissionRequest`.

### mcp (optional)

`haptic-bridge mcp` serves three tools over stdio: `haptic_pulse(pattern, message)`,
`haptic_status()`, `haptic_halt()`. They only forward to the running daemon. This is the
path for chat clients without hooks (ChatGPT, Claude Desktop) and for deliberate feedback
such as "tests passed". `.mcp.json` registers it for Claude Code in this project.

## backends

| name        | device                              | needs                                              |
|-------------|-------------------------------------|----------------------------------------------------|
| `mock`      | none, logs pulses                   | nothing                                            |
| `dualsense` | PS5 controller over USB             | extra `dualsense`                                  |
| `openshock` | OpenShock hub + shocker via cloud   | `OPENSHOCK_TOKEN` from openshock.app account       |
| `lovense`   | Lovense toy via Lovense Remote app  | app in Game Mode with LAN enabled, same network    |

OpenShock defaults to `Vibrate`; `Shock` is refused unless `allow_shock = true`. Every backend
sends a stop when a pattern is cut short by a newer event or by `halt`.

## cli

```bash
uv run haptic-bridge emit done            # play the pattern mapped to "done"
uv run haptic-bridge emit custom --pattern permission
uv run haptic-bridge halt                 # kill switch: stop devices, ignore events
uv run haptic-bridge resume
uv run haptic-bridge devices
uv run haptic-bridge health
```

Environment: `HAPTIC_BRIDGE_URL` (default `http://127.0.0.1:8787`), `HAPTIC_BRIDGE_TOKEN`,
`HAPTIC_BRIDGE_CONFIG`, `OPENSHOCK_TOKEN`.

## http api

| method | path            | body                                   |
|--------|-----------------|----------------------------------------|
| POST   | `/hook/claude`  | raw Claude Code hook payload           |
| POST   | `/hook/codex`   | raw Codex notify or hook payload       |
| POST   | `/event`        | `{kind, source?, message?, pattern?}`  |
| POST   | `/halt`         |                                        |
| POST   | `/resume`       |                                        |
| GET    | `/health`       |                                        |
| GET    | `/devices`      |                                        |

When `auth_token` is configured every route requires `Authorization: Bearer <token>`.

## development

```bash
just check        # ruff + mypy
```

## license

MIT