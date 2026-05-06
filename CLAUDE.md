# pyoas

## Overview

Python 3.12+ single-package project (`pyoas`) with optional extras. Generates Pydantic v2 models and FastAPI routers from OpenAPI 3.0/3.1 specs, organized by operation tag.

## Packages

| Package | Purpose |
|---|---|
| `pyoas` | Spec loading, ref resolution, tag extraction, Jinja2 rendering, Pydantic v2 model generation, CLI |
| `pyoas[fastapi]` | FastAPI router generation + service stubs + test scaffolding |
| `pyoas[claude]` | Claude Code skill generation (optional) |

`pyoas[fastapi]` and `pyoas[claude]` both extend the base `pyoas` package.

## Key Data Flow

```
OpenAPI spec (YAML/JSON)
  → SpecParser.load()          # validate + cache
  → resolve_refs()             # expand all $refs (keep raw too)
  → extract_tags()             # group operations by first tag
  → ModelGenerator.generate()  # → src/generated/models/{tag_dirname}.py
  → RouterGenerator.generate() # → src/generated/routers/{tag_dirname}.py
```

The **raw** (unresolved) spec is kept alongside the resolved spec because $ref names are needed for identifying component schemas.

## Config (`pyoas.yaml`)

```yaml
spec: openapi.yaml
output:
  models: src/generated/models
  routers: src/generated/routers
default_tag: default
model_config:
  extra: ignore
  request_extra: forbid
  frozen: false
  populate_by_name: true
fields:
  snake_case: true
  enums_as_literals: true
format:
  enabled: true   # runs ruff format post-generation
templates:
  models: null    # user override dir; null = use package defaults
  routers: null
services:
  generate: false
  output: src/services
  overwrite: false
  import_path: ""
  drift_log: null   # path to append drift warnings; null = console only
tests:
  generate: false
  output: tests/generated
  overwrite: false
  not_found_exception: null
skills:
  generate: false
  output: .claude/commands
  overwrite: false
  services_pattern: none  # none | repository | domain
```

## Tooling

- **uv**: dependency management (`uv run`, `uv add`, `uv sync`)
- **ruff**: linting (E, F, I, UP; line-length 88) and formatting
- **mypy**: type checking
- **pytest**: testing with `--import-mode=importlib`
- **syrupy**: snapshot testing for generated code

## Running Tests

```bash
uv run pytest                   # all tests
uv run pytest tests/fastapi/    # single area
uv run ruff check src/
uv run mypy src/
```

## Generated Output Contract

- Generated files are **fully replaced** on each run (no merge logic).
- User code lives in `src/services/` — scaffolded once, never overwritten by default.
- Tag name → folder name (snake_case). Operations with no tag → `default_tag`.
- Schemas referenced by one tag go to `{tag_dirname}.py`; schemas referenced by multiple tags go to `shared.py`.

## Test Fixtures

Shared OpenAPI specs live in `tests/fixtures/` and are referenced by all test modules via `conftest.py`.

## Releases

Versioning is managed by Commitizen (`uv run cz bump`). **Always use conventional commit messages** so the version bump is determined automatically:

| Prefix | Bump |
|---|---|
| `fix:` | patch — `0.2.0 → 0.2.1` |
| `feat:` | minor — `0.2.0 → 0.3.0` |
| `feat!:` or `BREAKING CHANGE:` footer | major — `0.2.0 → 1.0.0` |

To release:
```bash
uv run cz bump          # bumps pyproject.toml, tags, updates CHANGELOG.md
git push origin main --follow-tags   # triggers publish.yml → PyPI
```
