# Package Architecture

pyoas is organized as a uv workspace with four independently installable packages under the `pyoas.*` namespace (PEP 420 namespace packages).

## Package dependency graph

```
pyoas
    ↑
pyoas
    ↑
pyoas[fastapi]

pyoas
    ↑
pyoas[claude]
```

`pyoas[fastapi]` depends on `pyoas`, which depends on `pyoas`. `pyoas[claude]` depends only on `pyoas`.

## pyoas

Foundation package. All other packages depend on it.

**Provides:**

- `pyoas.core.config` — `Config` dataclass and `load_config()`
- `pyoas.core.parser` — `SpecParser`: load and validate OpenAPI specs
- `pyoas.core.resolver` — `resolve_refs()`: expand all `$ref` entries
- `pyoas.core.tags` — `extract_tags()`: group operations by tag
- `pyoas.core.renderer` — `Renderer`: Jinja2 with user-override support
- `pyoas.core.utils` — `to_snake_case()`, `derive_import_path()`, etc.
- `pyoas` CLI — all `pyoas` commands (dynamically imports model/router generators)

**Runtime dependencies:** pyyaml, openapi-spec-validator, jsonref, jinja2, ruff, typer

### Using pyoas standalone

```python
from pyoas.core.config import load_config
from pyoas.core.parser import SpecParser
from pyoas.core.resolver import resolve_refs
from pyoas.core.tags import extract_tags

config = load_config("pyoas.yaml")
parser = SpecParser(config.spec)
raw_spec = parser.load()
resolved_spec = resolve_refs(raw_spec, config.spec)
grouped = extract_tags(resolved_spec, config.default_tag)

for tag, operations in grouped.items():
    print(f"{tag}: {len(operations)} operations")
```

---

## pyoas

Pydantic v2 model generation.

**Provides:**

- `pyoas.models.ModelGenerator` — generates model files from a `Config`
- `pyoas.models.types.schema_to_python_type()` — converts an OpenAPI schema dict to a Python type annotation string

**Runtime dependencies:** pyoas

### Using pyoas standalone

```python
from pyoas.core.config import load_config
from pyoas.models import ModelGenerator

config = load_config("pyoas.yaml")
ModelGenerator(config).generate()
```

Limit to specific tags:

```python
ModelGenerator(config).generate(tag_filter=["pets", "users"])
```

Use `schema_to_python_type()` directly:

```python
from pyoas.models.types import schema_to_python_type

schema = {"type": "string", "format": "date-time"}
print(schema_to_python_type(schema))  # "datetime.datetime"

schema = {"type": "integer", "minimum": 0}
print(schema_to_python_type(schema))  # "int"
```

---

## pyoas[fastapi]

FastAPI router generation plus one-time scaffolding.

**Provides:**

- `pyoas.fastapi.RouterGenerator` — generates router files from a `Config`
- `pyoas.fastapi.ServiceScaffolder` — scaffolds service stub files
- `pyoas.fastapi.TestScaffolder` — scaffolds endpoint test files
- `pyoas.fastapi.ServiceTestScaffolder` — scaffolds service integration test files
- `pyoas.fastapi.DependencyScaffolder` — scaffolds dependency injection stubs

**Runtime dependencies:** pyoas, pyoas, polyfactory

### Using pyoas[fastapi] standalone

```python
from pyoas.core.config import load_config
from pyoas.fastapi import RouterGenerator, ServiceScaffolder

config = load_config("pyoas.yaml")
RouterGenerator(config).generate()
ServiceScaffolder(config).scaffold()
```

---

## pyoas[claude]

Claude Code skill generation. Optional, separate install.

**Provides:**

- `pyoas.claude.SkillScaffolder` — generates Claude Code skill files

**Runtime dependencies:** pyoas, typer

### Using pyoas[claude] standalone

```python
from pyoas.core.config import load_config
from pyoas.claude import SkillScaffolder

config = load_config("pyoas.yaml")
SkillScaffolder(config).scaffold()
```

---

## Installing individual packages

If you only need models (no FastAPI dependency):

```shell
uv add pyoas
```

If you only need the spec parsing / rendering primitives:

```shell
uv add pyoas
```

The `pyoas` CLI is always available once `pyoas` is installed.

---

## Namespace package layout

All packages share the `pyoas` namespace (PEP 420):

```
pyoas/
  core/    → pyoas
  models/  → pyoas
  fastapi/ → pyoas[fastapi]
  claude/  → pyoas[claude]
```

Each package has its own `src/pyoas/<name>/` directory with no `__init__.py` at the `pyoas/` level, allowing them to be installed independently without conflict.
