# Installation

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Install with uv

For most projects you want the full stack — models, routers, and scaffolding:

```shell
uv add pyoas[fastapi]
```

This pulls in `pyoas` and `pyoas` automatically.

### Minimal installs

Install only what you need:

```shell
# Models only (no FastAPI dependency)
uv add pyoas

# Core only (spec loading, CLI, rendering primitives)
uv add pyoas
```

### Claude Code skills (optional)

```shell
uv add pyoas[claude]
```

## Install with pip

```shell
pip install "pyoas[fastapi]"
```

## Verify

```shell
pyoas --version
pyoas --help
```

## Development install

To work on pyoas itself, clone the repo and sync all workspace packages:

```shell
git clone https://github.com/wianra/specgen.git
cd pyoas
uv sync --all-packages
```

Run tests:

```shell
uv run pytest
```
