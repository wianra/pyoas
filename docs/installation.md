# Installation

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Install with uv

For most projects you want the full stack — models, routers, and scaffolding:

```shell
uv add pyoas[fastapi]
```

### Models only (no FastAPI dependency)

```shell
uv add pyoas
```

### Claude Code skills (optional)

Can be combined with either install above:

```shell
uv add "pyoas[fastapi,claude]"
```

## Install with pip

```shell
pip install "pyoas[fastapi]"
```

## Verify

```shell
pyoas --help
```

## Development install

To work on pyoas itself, clone the repo and install with all extras:

```shell
git clone https://github.com/wianra/pyoas.git
cd pyoas
uv sync --extra fastapi --extra claude
```

Run tests:

```shell
uv run pytest
```
