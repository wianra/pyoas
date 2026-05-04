# Configuration reference

pyoas is configured by a `pyoas.yaml` file (default name). Pass a different path with `--config`.

## Minimal config

```yaml
spec: openapi.yaml
output:
  models: src/generated/models
  routers: src/generated/routers
```

## Full config with all options

```yaml
spec: openapi.yaml
output:
  models: src/generated/models
  routers: src/generated/routers
  models_import: null        # derived from models path if omitted
  routers_import: null       # derived from routers path if omitted
  source_root: src           # stripped when deriving import paths

default_tag: default         # tag for operations with no tag

model_config:
  extra: ignore
  request_extra: forbid
  frozen: false
  populate_by_name: true
  include_unreferenced: false

fields:
  snake_case: true
  enums_as_literals: true

format:
  enabled: true              # run ruff format after generation

templates:
  models: null               # path to custom Jinja2 template dir
  routers: null

services:
  generate: false
  output: src/services
  overwrite: false
  import_path: ""
  drift_log: null

tests:
  generate: false
  output: tests/generated
  overwrite: false
  not_found_exception: null

skills:
  generate: false            # requires pyoas[claude]
  output: .claude/commands
  overwrite: false
  services_pattern: none     # none | repository | domain

router:
  response_model_exclude_none: false
  response_model_exclude_unset: false

dependencies:
  generate: false
  output: src/dependencies
  overwrite: false
  import_path: ""
```

---

## `spec`

**Required.** Path to the OpenAPI 3.0 or 3.1 spec file. Resolved relative to the config file. YAML and JSON are both accepted.

```yaml
spec: openapi.yaml
spec: specs/v2/openapi.json
```

---

## `output`

Controls where generated files are written and how import paths are derived.

| Key | Default | Description |
|---|---|---|
| `models` | `src/generated/models` | Output directory for generated model files |
| `routers` | `src/generated/routers` | Output directory for generated router files |
| `models_import` | _(derived)_ | Python import path for models; derived from `models` if omitted |
| `routers_import` | _(derived)_ | Python import path for routers; derived from `routers` if omitted |
| `source_root` | `src` | Filesystem prefix stripped when deriving import paths |

**Import path derivation example:**

```yaml
output:
  models: src/generated/models   # → models_import = "generated.models"
  source_root: src
```

Override manually if your layout is non-standard:

```yaml
output:
  models: app/gen/models
  models_import: myapp.gen.models
```

---

## `default_tag`

Default: `"default"`. Operations that have no `tags` field are grouped under this tag name.

```yaml
default_tag: misc
```

---

## `model_config`

Controls Pydantic model configuration in generated code.

| Key | Default | Description |
|---|---|---|
| `extra` | `"ignore"` | Pydantic `extra` for response/shared models |
| `request_extra` | `"forbid"` | Pydantic `extra` for request-only models |
| `frozen` | `false` | Generates `frozen=True` models (immutable) |
| `populate_by_name` | `true` | Allows populating fields by Python name and by alias |
| `include_unreferenced` | `false` | Generate schemas not referenced by any operation |

**`extra` values:** `"ignore"` (default), `"forbid"`, `"allow"`

pyoas classifies each schema as *request-only* (never appears in a response) or *response/shared*. Request-only schemas default to `extra="forbid"` for strict validation.

---

## `fields`

| Key | Default | Description |
|---|---|---|
| `snake_case` | `true` | Convert camelCase field names to snake_case and add `alias` |
| `enums_as_literals` | `true` | Render string/int enums as `Literal[...]` instead of `StrEnum`/`IntEnum` |

**`snake_case` example:**

```python
# With snake_case: true
class Pet(BaseModel):
    pet_id: int = Field(alias="petId")
    created_at: datetime = Field(alias="createdAt")

# With snake_case: false
class Pet(BaseModel):
    petId: int
    createdAt: datetime
```

**`enums_as_literals` example:**

```python
# enums_as_literals: true (default)
status: Literal["available", "pending", "sold"] | None = None

# enums_as_literals: false
class PetStatus(StrEnum):
    available = "available"
    pending = "pending"
    sold = "sold"
```

---

## `format`

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Run `ruff format` on all generated files after writing |

Disable during development to see raw template output:

```yaml
format:
  enabled: false
```

---

## `templates`

Override the built-in Jinja2 templates with your own.

| Key | Default | Description |
|---|---|---|
| `models` | `null` | Directory containing custom model templates |
| `routers` | `null` | Directory containing custom router templates |

See the [Custom Templates guide](guides/custom-templates.md) for details.

---

## `services`

One-time service stub scaffolding. Files are written once and never overwritten by default.

| Key | Default | Description |
|---|---|---|
| `generate` | `false` | Scaffold service files when running `pyoas generate` |
| `output` | `src/services` | Output directory for service files |
| `overwrite` | `false` | Overwrite existing service files on re-run |
| `import_path` | `""` | Python import path routers use to import the service (e.g. `myapp.services`) |
| `drift_log` | `null` | Path to append drift warnings; `null` logs to console only |

**`import_path` matters** — routers import the service class using this path. If empty, service imports are omitted from generated routers.

```yaml
services:
  generate: true
  import_path: src.services   # or myapp.services
```

---

## `tests`

Pytest test stub scaffolding. New test classes are appended to existing files; they are not overwritten.

| Key | Default | Description |
|---|---|---|
| `generate` | `false` | Scaffold test files when running `pyoas generate` |
| `output` | `tests/generated` | Output directory for test files |
| `overwrite` | `false` | Overwrite existing test files on re-run |
| `not_found_exception` | `null` | Exception expression for `test_not_found` stubs |

**`not_found_exception` example:**

```yaml
tests:
  not_found_exception: "HTTPException(status_code=404, detail='Not found')"
```

This generates `test_not_found` stubs that mock the service to raise this exception and assert a 404 response.

---

## `skills`

Claude Code skill generation. Requires `pyoas[claude]` to be installed.

| Key | Default | Description |
|---|---|---|
| `generate` | `false` | Generate skill files when running `pyoas generate` |
| `output` | `.claude/commands` | Output directory for skill files |
| `overwrite` | `false` | Overwrite existing skill files on re-run |
| `services_pattern` | `"none"` | Service pattern hint for generated skills: `none`, `repository`, `domain` |

---

## `router`

Controls FastAPI response model serialization options.

| Key | Default | Description |
|---|---|---|
| `response_model_exclude_none` | `false` | Add `response_model_exclude_none=True` to all endpoints |
| `response_model_exclude_unset` | `false` | Add `response_model_exclude_unset=True` to all endpoints |

---

## `dependencies`

Scaffold a dependency injection stub (e.g. auth context).

| Key | Default | Description |
|---|---|---|
| `generate` | `false` | Scaffold dependency files |
| `output` | `src/dependencies` | Output directory |
| `overwrite` | `false` | Overwrite existing files |
| `import_path` | `""` | Python import path for the dependencies module |

See the [Dependency Injection guide](guides/dependencies.md) for details.
