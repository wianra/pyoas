# Package Architecture

pyoas is a single Python package (`pyoas`) with optional extras for FastAPI and Claude Code integration.

## Install options

```shell
# Models + routers + scaffolding (recommended for most projects)
uv add pyoas[fastapi]

# Models only (no FastAPI dependency)
uv add pyoas

# Claude Code skill generation (can be combined with either of the above)
uv add "pyoas[fastapi,claude]"
```

## What each install provides

### `pyoas` (base)

The base package includes everything needed for Pydantic model generation.

**Provides:**

- `pyoas.core.config` — `Config` dataclass and `load_config()`
- `pyoas.core.parser` — `SpecParser`: load and validate OpenAPI specs
- `pyoas.core.resolver` — `resolve_refs()`: expand all `$ref` entries
- `pyoas.core.tags` — `extract_tags()`: group operations by tag
- `pyoas.core.renderer` — `Renderer`: Jinja2 with user-override support
- `pyoas.core.utils` — `to_snake_case()`, `derive_import_path()`, etc.
- `pyoas.models.ModelGenerator` — generate Pydantic v2 model files
- `pyoas` CLI — all `pyoas` commands

**Runtime dependencies:** pyyaml, openapi-spec-validator, jsonref, jinja2, ruff, typer, watchdog

```python
from pyoas.core.config import load_config
from pyoas.models import ModelGenerator

config = load_config("pyoas.yaml")
ModelGenerator(config).generate()
```

---

### `pyoas[fastapi]`

Extends the base package with FastAPI router generation and one-time scaffolding.

**Additional provides:**

- `pyoas.fastapi.RouterGenerator` — generate FastAPI router files
- `pyoas.fastapi.ServiceScaffolder` — scaffold service stub files
- `pyoas.fastapi.TestScaffolder` — scaffold endpoint test files
- `pyoas.fastapi.ServiceTestScaffolder` — scaffold service integration test files
- `pyoas.fastapi.DependencyScaffolder` — scaffold dependency injection stubs

**Additional runtime dependencies:** fastapi, polyfactory

```python
from pyoas.core.config import load_config
from pyoas.fastapi import RouterGenerator, ServiceScaffolder

config = load_config("pyoas.yaml")
RouterGenerator(config).generate()
ServiceScaffolder(config).scaffold()
```

---

### `pyoas[claude]`

Extends the base package with Claude Code skill file generation.

**Additional provides:**

- `pyoas.claude.SkillScaffolder` — generate `.claude/commands/*.md` skill files

**Additional runtime dependencies:** none

```python
from pyoas.core.config import load_config
from pyoas.claude import SkillScaffolder

config = load_config("pyoas.yaml")
SkillScaffolder(config).scaffold()
```

---

## Source layout

All modules live under a single `src/pyoas/` tree:

```
src/pyoas/
  core/    # config, parser, resolver, tags, renderer, utils, cli
  models/  # ModelGenerator, schema renderer, type mapping
  fastapi/ # RouterGenerator, scaffolders, params
  claude/  # SkillScaffolder
```
