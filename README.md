# pyoas

Generate Pydantic v2 models and FastAPI routers from an OpenAPI spec. Organized as a uv workspace with independent, installable packages.

## Packages

| Package | Purpose |
|---|---|
| `pyoas` | Foundation: spec loading, ref resolution, tag extraction, Jinja2 rendering, CLI |
| `pyoas` | Pydantic v2 model generation from OpenAPI schemas |
| `pyoas[fastapi]` | FastAPI router + service stub generation + test scaffolding |
| `pyoas[claude]` | Claude Code skill generation (optional) |

`pyoas[fastapi]` depends on `pyoas`; both depend on `pyoas`. `pyoas[claude]` depends on `pyoas`.

## Quick start

```shell
# Install
uv add pyoas[fastapi]

# Create a minimal config
cat > pyoas.yaml << 'EOF'
spec: openapi.yaml
output:
  models: src/generated/models
  routers: src/generated/routers
EOF

# Generate Pydantic models and FastAPI routers
uv run pyoas generate

# Optionally scaffold service stubs and test files
uv run pyoas scaffold services
```

A more complete config with all optional features:

```yaml
spec: openapi.yaml
output:
  models: src/generated/models
  routers: src/generated/routers
services:
  generate: true
  output: src/services
  import_path: myapp.services  # Python import path for service module
tests:
  generate: true
  output: tests/generated
  not_found_exception: "HTTPException(status_code=404, detail='Not found')"
skills:
  generate: true  # requires pyoas[claude]
```

Then:

```shell
uv run pyoas generate   # models + routers + service stubs + tests + skills
```

## Configuration reference (`pyoas.yaml`)

### `spec`

Path to the OpenAPI 3.0/3.1 spec file (YAML or JSON). Resolved relative to the config file. **Required.**

### `output`

| Key | Default | Description |
|---|---|---|
| `models` | `src/generated/models` | Output directory for generated model files |
| `routers` | `src/generated/routers` | Output directory for generated router files |
| `models_import` | _(derived)_ | Python import path for models; derived from `models` path if omitted |
| `routers_import` | _(derived)_ | Python import path for routers; derived from `routers` path if omitted |
| `source_root` | `src` | Filesystem prefix stripped when deriving Python import paths |

### `default_tag`

Default: `"default"`. Operations with no tag are grouped under this name.

### `model_config`

| Key | Default | Description |
|---|---|---|
| `extra` | `"ignore"` | Pydantic `extra` setting for response/shared models |
| `request_extra` | `"forbid"` | Pydantic `extra` setting for request-only models |
| `frozen` | `false` | Makes generated models immutable |
| `populate_by_name` | `true` | Allow populating fields by Python name as well as alias |

### `fields`

| Key | Default | Description |
|---|---|---|
| `snake_case` | `true` | Convert camelCase field names to snake_case with an alias |
| `enums_as_literals` | `true` | Render small enums as `Literal[...]` instead of `Enum` subclasses |

### `format`

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Run `ruff format` on generated files after writing |

### `templates`

| Key | Default | Description |
|---|---|---|
| `models` | `null` | Path to a directory of custom Jinja2 templates overriding model templates |
| `routers` | `null` | Path to a directory of custom Jinja2 templates overriding router templates |

### `services`

| Key | Default | Description |
|---|---|---|
| `generate` | `false` | Scaffold service stub files |
| `output` | `src/services` | Output directory for service files |
| `overwrite` | `false` | Overwrite existing service files on re-run |
| `import_path` | `""` | Python import path used by routers to import the service (e.g. `myapp.services`) |

### `tests`

| Key | Default | Description |
|---|---|---|
| `generate` | `false` | Scaffold pytest test stub files |
| `output` | `tests/generated` | Output directory for test files |
| `overwrite` | `false` | Overwrite existing test files on re-run (default: append new test classes only) |
| `not_found_exception` | `null` | Exception expression used in `test_not_found` stubs (e.g. `HTTPException(status_code=404)`) |

### `skills`

Requires `pyoas[claude]` to be installed.

| Key | Default | Description |
|---|---|---|
| `generate` | `false` | Generate Claude Code skill files |
| `output` | `.claude/commands` | Output directory for skill files |
| `overwrite` | `false` | Overwrite existing skill files on re-run |

## Generated output

### Models (`pyoas`)

One file per tag: `{models_output}/{tag}/models.py`. Schemas referenced by multiple tags go to `{models_output}/shared/models.py`.

```
src/generated/models/
  __init__.py
  pets/
    models.py      # Pet, PetCreate, PetList, ...
  shared/
    models.py      # schemas used by more than one tag
```

### Routers (`pyoas[fastapi]`)

One file per tag: `{routers_output}/{tag}/router.py`. An `__init__.py` at the root re-exports all routers.

```
src/generated/routers/
  __init__.py      # from .pets import router as pets_router; ...
  pets/
    router.py      # APIRouter with typed endpoint stubs
```

### Service stubs

One file per tag: `{services_output}/{tag}.py`. Scaffolded once; never overwritten by default.

```
src/services/
  pets.py          # PetsService class with async method stubs
```

### Test scaffolding

One test file per tag plus a shared `conftest.py` with model factories.

```
tests/generated/
  conftest.py      # make_pet(), make_pet_list(), ...
  test_pets.py     # TestListPets, TestCreatePet, TestGetPet, ...
```

Each test class covers one endpoint and includes:
- `test_endpoint_exists` — verifies the route returns something other than 404/405
- Validation tests for required fields, numeric bounds, string constraints, enum violations
- `test_not_found` — verifies 404 when the service raises the configured exception
- `test_success` — happy-path stub (auto-implemented for GET/DELETE, stubbed for others)

## CLI reference

```shell
pyoas models        # generate Pydantic models only
pyoas fastapi       # generate FastAPI routers only
pyoas generate      # generate models + routers (+ services/tests/skills if configured)
pyoas scaffold services  # scaffold service stubs (skips existing files)
```

All commands accept:
- `--config PATH` — path to config file (default: `pyoas.yaml`)
- `--tags TAG1,TAG2` — limit generation to specific tags
- `--clean` — purge output directory before generating

## Claude Code integration (`pyoas[claude]`)

Install `pyoas[claude]` and set `skills.generate: true` in your config. Running `pyoas generate` will write Claude Code skill files to `.claude/commands/`:

| Skill | Invocation | Purpose |
|---|---|---|
| `implement-tests.md` | `/implement-tests tests/generated/test_pets.py` | Implement all `pytest.skip("implement me")` stubs in a test file |
| `add-test-case.md` | `/add-test-case tests/generated/test_pets.py "scenario"` | Add a new test method for the described scenario |
| `review-generated.md` | `/review-generated` | Cross-reference generated code against the OpenAPI spec and flag issues |

## Development

```shell
# Install all workspace packages in editable mode
uv sync --all-packages

# Run all tests
uv run pytest

# Run tests for a single package
uv run pytest packages/pyoas[fastapi]/

# Update snapshots
uv run pytest packages/pyoas[fastapi]/ --snapshot-update

# Lint and type-check
uv run ruff check packages/
uv run mypy packages/
```
