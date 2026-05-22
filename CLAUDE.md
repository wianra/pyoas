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

## Tooling

uv · ruff (E, F, I, UP; line-length 88) · mypy · pytest (`--import-mode=importlib`) · syrupy (snapshot testing)

## Generated Output Contract

- Generated files are **fully replaced** on each run (no merge logic).
- User code lives in `src/services/` — scaffolded once, never overwritten by default.
- Tag name → folder name (snake_case). Operations with no tag → `default_tag`.
- Schemas referenced by one tag go to `{tag_dirname}.py`; schemas referenced by multiple tags go to `shared.py`.

## Test Fixtures

Shared OpenAPI specs live in `tests/fixtures/` and are referenced by all test modules via `conftest.py`.

## Generator Smoke Test

`tests/integration/test_generated_output_smoke.py` runs on every `uv run pytest` (no `--run-integration` flag needed). It generates `tests/fixtures/smoke_spec.yaml` into a tmp directory once per session and asserts the output passes `compileall`, `ruff --select=E,F --ignore=E501`, an importlib walk of every module, and a subprocess `pytest` against the scaffolded test tree with `MagicMock` services.

When adding a new scaffolder feature, extend `smoke_spec.yaml` with the smallest possible operation that exercises the new code path — don't add a new check here. The B-15..B-22 burst all shared one root cause: snapshot tests accepted broken output because they never ran it. The smoke spec is the regression net.

## Skills

- `/commit` — conventional commit with correct prefix
- `/release` — cut a new version via Commitizen + push to PyPI
- `/check` — run tests, lint, and type-check
