set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

default:
    @just --list

# install runtime + dev dependencies, including the dualsense extra
sync:
    uv sync --all-extras

# run the daemon with ./haptic-bridge.toml
serve:
    uv run haptic-bridge serve

# lint, format check, type check
lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy

# auto-fix lint and formatting
fmt:
    uv run ruff check --fix .
    uv run ruff format .

# everything ci would run
check: lint

# fire one event at the running daemon, e.g. `just emit permission`
emit kind="done":
    uv run haptic-bridge emit {{kind}}
