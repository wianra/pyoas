# pyoas — Implementation Plan (post v0.1.1)

Status legend: `[ ]` open · `[~]` in progress · `[x]` done

---

## Tier 1 — Correctness patches

These break real-world specs and should ship as patch releases. Each item is
self-contained and can be addressed in isolation.

---

### T1-A · Circular refs — emit `from __future__ import annotations`

**Problem.** `resolver/__init__.py` breaks cycles by re-emitting the raw
`{"$ref": "..."}` string into the resolved dict. `types.py:schema_to_python_type()`
picks this up via the second-chance fallback (`for ref_holder in (raw_schema, schema)`)
and returns the class name. This means a self-referencing model (e.g. `TreeNode` with
`children: list[TreeNode]`) produces a field annotation that references a name not yet
defined at parse time → `NameError` at import.

**Fix.**
1. In `ModelGenerator.generate()` (`src/pyoas/models/generator.py`), after classifying
   schemas, detect whether any schema in the output file contains a circular ref by
   checking `_find_referenced_schemas()` against itself transitively.
2. Pass a `has_circular: bool` flag into the Jinja2 model template context.
3. In `src/pyoas/models/templates/model.py.jinja2`, emit
   `from __future__ import annotations` as the first line when `has_circular` is true.
4. Add a fixture `tests/fixtures/circular_ref.yaml` with a `TreeNode` schema and a
   corresponding snapshot test.

**Files touched:** `models/generator.py`, `models/context.py`,
`models/templates/model.py.jinja2`, new fixture + test.

**Tests:** snapshot test for generated file, assert the future import appears.

- [x] Add `circular_ref.yaml` fixture
- [x] Detect circular membership in `generator.py`
- [x] Thread `has_circular` through context
- [x] Emit future import in template (already unconditional — no change needed)
- [x] Snapshot test

---

### T1-B · `allOf` in `types.py` — inheritance, not union

**Problem.** `types.py:_base_type()` line 155–165: `allOf` is rendered as
`" | ".join(parts)`. In the vast majority of real-world specs, `allOf` means
"this schema inherits from these" (Pydantic model inheritance). The schema
renderer (`schema_renderer.py`) already handles `allOf` correctly for *model class*
rendering, but when the *type mapper* encounters an `allOf` reference (e.g. a field
whose type is `allOf: [{$ref: Animal}, {properties: ...}]`) it produces `Animal |
{inline}` instead of `Animal`.

**Fix.**
- In `types.py:_base_type()`, when `allOf` has **exactly one** `$ref` entry and the
  rest are inline objects with no additional `$ref` (i.e. additive properties only),
  return the `$ref` name alone — the schema renderer will handle the merged class.
- When `allOf` has multiple `$ref` entries (multiple inheritance), keep the union but
  add a comment in the generated model via the template.
- When `allOf` has zero `$ref` entries (pure property merging), return `dict[str, Any]`
  with a `# merged inline` comment.

**Files touched:** `models/types.py` (`_base_type`).

**Tests:** add test cases in `tests/models/test_types.py` covering
`allOf + $ref + inline`, `allOf + two $refs`, `allOf + inline only`.

- [x] Implement single-ref `allOf` shortcut
- [x] Keep multi-ref union
- [x] Inline-only fallback
- [x] Test cases

---

### T1-C · Plain-text and octet-stream request bodies

**Problem.** `params.py:build_function_params()` lines 361–383: any content type
that is not `application/json`, `multipart/form-data`, or
`application/x-www-form-urlencoded` falls into an else branch that emits
`Annotated[bytes, Body()]` with `# TODO: {unknown_type} request body` in the
description. `text/plain` should be `str`; `application/octet-stream` should be
`bytes` (correct but without the TODO comment); `image/*` and other binary types
should be `bytes`.

**Fix.** Add a small content-type → Python type lookup before the generic else:

```python
_CONTENT_TYPE_BODY_MAP = {
    "text/plain": "str",
    "text/html": "str",
    "text/csv": "str",
    "application/octet-stream": "bytes",
    "application/pdf": "bytes",
}
```

Emit the mapped type with no TODO comment. Keep `bytes` as ultimate fallback but
remove the TODO from the description field (it shows up as a comment in the router).

**Files touched:** `fastapi/params.py`.

**Tests:** add param-builder test cases with `text/plain` and
`application/octet-stream` content types; assert correct types and no TODO string
in description.

- [x] Add `_CONTENT_TYPE_BODY_MAP`
- [x] Apply mapping before else branch
- [x] Strip TODO from fallback description
- [x] Tests

---

### T1-D · Discriminator `mapping` support

**Problem.** `types.py:_base_type()` lines 182–189: discriminator is read but only
`propertyName` is used. OpenAPI allows a `mapping` dict
(`discriminatorValue → $ref`) that overrides the default convention
(propertyName value == schema name). When `mapping` is present and a spec uses
non-default values, Pydantic's discriminated union will fail to match at runtime.

**Fix.**
- In `types.py:_base_type()`, when `discriminator.mapping` is present, reorder
  the `parts` list to match the mapping order and annotate each part with
  `Literal["..."]` field on the discriminator property so Pydantic can resolve it.
- This requires generating a separate `Annotated` form per variant rather than a
  flat union. The cleanest approach: emit
  `Annotated[Union[VariantA, VariantB], Field(discriminator="kind")]` using
  `typing.Union` explicitly (Pydantic v2 accepts both).
- Pass the `mapping` dict into the template context so the model template can
  optionally emit a `__get_validators__` or `model_validator` comment block.

**Files touched:** `models/types.py`, `models/schema_renderer.py`,
`models/templates/model.py.jinja2`.

**Tests:** add `tests/fixtures/discriminated_mapping.yaml` with explicit mapping;
snapshot test.

- [x] Read `discriminator.mapping` in type mapper
- [x] Emit correct annotated union
- [x] Template context update
- [x] Fixture + snapshot test (updated existing `discriminated.yaml` snapshot)

---

## Tier 2 — Coverage (minor releases, target 0.2.x)

---

### T2-A · OAS 3.1 `$defs` support

**Problem.** OAS 3.1 allows schemas to define `$defs` inline (JSON Schema
2020-12 convention). These are distinct from `components/schemas` and are not
currently resolved or collected by the classifier or generator.

**Fix.**
- In `resolver/__init__.py`, extend ref resolution to follow `$defs` keys at any
  nesting level (not just `#/components/schemas/`).
- In `models/classifier.py`, collect schemas from `$defs` blocks and treat them as
  tag-local schemas (since they live inside a specific schema).
- In `models/context.py`, render `$defs`-sourced schemas as inner classes or
  module-level classes depending on whether they are referenced by more than one
  parent.

**Files touched:** `core/resolver/__init__.py`, `models/classifier.py`,
`models/context.py`.

- [x] Resolve `$defs` references
- [x] Collect `$defs` schemas in classifier
- [x] Render as inner or module-level classes
- [x] Fixture `tests/fixtures/inline_defs_3.1.yaml` + snapshot

---

### T2-B · Webhook generation (promote from experimental to stable)

**Problem.** OAS 3.1 webhooks are extracted by `tags/__init__.py` (the
`extract_tags` function has a `webhooks` code path) but the router generator
never calls it, and there is no config path to enable it.

**Fix.**
1. Add `webhooks.generate: bool = False` to `Config` / `pyoas.yaml` schema
   (`core/config.py`).
2. In `fastapi/generator.py`, after the main tag loop, check
   `config.webhooks.generate` and generate a `webhooks/router.py` for each
   webhook group using the same router template.
3. Update the `__init__.py` re-export template to include webhook routers when
   present.
4. Add `pyoas scaffold webhooks` CLI sub-command.
5. Document in README.

**Files touched:** `core/config.py`, `fastapi/generator.py`,
`fastapi/templates/init.py.jinja2`, `core/cli.py`.

- [x] Config option
- [x] Generator wiring
- [x] `__init__.py` re-export
- [x] CLI sub-command
- [x] Tests with `tests/fixtures/webhooks_3.1.yaml`

---

### T2-C · Security scope annotation in auth stubs

**Problem.** `deps_scaffold.py` generates auth dependency stubs but ignores
`scopes` on the security requirement object. A route that requires
`["read:pets", "write:pets"]` gets the same generic auth stub as one with no
scopes, making it impossible to implement RBAC from the generated code alone.

**Fix.**
- In `fastapi/generator.py`, when extracting security requirements per operation,
  also collect required scopes.
- Pass scopes into the router template per endpoint (already available as part of
  the security descriptor).
- In `fastapi/templates/router.py.jinja2`, emit a comment block listing required
  scopes above each endpoint:
  `# Required scopes: read:pets, write:pets`.
- In `deps_scaffold.py`, add a `required_scopes: list[str]` parameter to the
  generated `get_auth_context()` call and emit a `# TODO: validate scopes` stub.

**Files touched:** `fastapi/generator.py`, `fastapi/deps_scaffold.py`,
`fastapi/templates/router.py.jinja2`, `fastapi/templates/dependency_auth.py.jinja2`.

- [x] Collect scopes per operation in generator
- [x] Router template scope comments
- [x] Auth stub scope parameter
- [x] Tests with `tests/fixtures/secured_scoped.yaml`

---

### T2-D · `uniqueItems` → `set` with serialization fix

**Problem.** `types.py` correctly maps `uniqueItems: true` to `set[T]`, but
Pydantic v2 does not serialize `set` to JSON by default (it raises a
`PydanticSerializationError`). Models with set fields will fail at
`model.model_dump(mode="json")`.

**Fix.**
- In `models/templates/model.py.jinja2`, when any field uses `set[...]`,
  add a `model_serializer` or use `Annotated[set[T], PlainSerializer(list)]`
  so the set serializes to a JSON array.
- Alternatively, emit `list[T]` with a `model_validator(mode="before")` that
  deduplicates — simpler and avoids the custom serializer.
- Add config option `fields.unique_items_as_set: bool = True` to let users
  opt into the original behavior.

**Files touched:** `models/types.py`, `models/templates/model.py.jinja2`,
`core/config.py`.

- [x] Config flag
- [x] Type mapper update
- [x] Template serializer handling
- [x] Test with `uniqueItems` fixture

---

### T2-E · `prefixItems` completeness (OAS 3.1 fixed-length tuples)

**Problem.** `types.py:_base_type()` lines 143–152 handle `prefixItems` but
only when `prefixItems` is the sole keyword. OAS 3.1 allows
`prefixItems + items` (fixed prefix + variable remainder), which should map to
`tuple[T1, T2, *tuple[R, ...]]` (Python 3.11+ variadic tuple) or fall back to
`tuple[T1, T2, Any, ...]` for 3.12 targets.

**Fix.** After building the prefix type list, check if `items` also exists.
If so, append `Unpack[tuple[items_type, ...]]` or the simpler
`*tuple[items_type, ...]` notation. Gate behind a
`sys.version_info >= (3, 11)` comment or always use the 3.12 compatible form
`tuple[T1, T2, *tuple[R, ...]]` since the project requires Python 3.12+.

**Files touched:** `models/types.py`.

- [x] Detect `prefixItems + items` combo
- [x] Emit variadic tuple annotation
- [x] Test case

---

### T2-F · `auth_context` pytest fixture instead of hardcoded `AuthContext()`

**Problem.** `fastapi/templates/test.py.jinja2` lines 29 and 48 emit:

```python
app.dependency_overrides[get_auth_context] = lambda: AuthContext()
```

directly inside the generated `client` and `client_with_mock` fixtures.  The
`dependency_auth.py.jinja2` scaffold produces an empty `AuthContext` (no fields), which
makes `AuthContext()` valid.  Real projects replace this stub with a real dataclass that
has required fields (e.g. `OperatorContext(operator_id: int, partner_id: int)`) exposed
via an alias in `app/dependencies/auth.py`.  This causes the generated tests to crash on
construction: `TypeError: __init__() missing required positional arguments`.

The workaround — manually changing `AuthContext()` to `AuthContext(1, 1)` in every test
file — is overwritten the next time `pyoas generate` is run.

**Solution.** Introduce an `auth_context` pytest fixture in `tests/generated/conftest.py`
(the scaffolded-once file) and have the generated test files accept it as a parameter
rather than constructing `AuthContext()` directly.

- The `auth_context` fixture in `conftest.py` returns `AuthContext()` by default.
- Users edit `conftest.py` **once** to return their real context
  (e.g. `AuthContext(operator_id=1, partner_id=42)`).
- `conftest.py` is scaffolded once and never overwritten unless
  `tests.overwrite: true` — so the customisation persists across regenerations.
- On `overwrite: true` (explicit full regeneration), conftest is regenerated from the
  template and users re-apply their one-line customisation.

**Real-world context (nova-data-api).**
`app/dependencies/__init__.py` defines `OperatorContext(operator_id: int, partner_id: int)`.
`app/dependencies/auth.py` re-exports it as `AuthContext = OperatorContext`.
The generated `tests/generated/test_charging_stations.py` was manually patched to use
`AuthContext(1, 1)` — a change that will be lost on the next overwrite run.

**Template changes.**

_`src/pyoas/fastapi/templates/test.py.jinja2`_

```diff
-def client() -> TestClient:
+def client({% if has_auth_dep %}auth_context: AuthContext{% endif %}) -> TestClient:
     app = FastAPI()
     app.include_router({{ tag_dirname }}_router)
 {% if has_auth_dep %}
-    app.dependency_overrides[get_auth_context] = lambda: AuthContext()
+    app.dependency_overrides[get_auth_context] = lambda: auth_context
 {% endif %}

-def client_with_mock(mock_service: AsyncMock) -> TestClient:
+def client_with_mock(mock_service: AsyncMock{% if has_auth_dep %}, auth_context: AuthContext{% endif %}) -> TestClient:
     app = FastAPI()
     app.include_router({{ tag_dirname }}_router)
     app.dependency_overrides[{{ service_dep_fn }}] = lambda: mock_service
 {% if has_auth_dep %}
-    app.dependency_overrides[get_auth_context] = lambda: AuthContext()
+    app.dependency_overrides[get_auth_context] = lambda: auth_context
 {% endif %}
```

_`src/pyoas/fastapi/templates/conftest.py.jinja2`_

- Make `from polyfactory...` import conditional on `factories` being non-empty (avoids
  unused-import error when conftest is written solely for auth with no response models).
- Append `auth_context` fixture block when `has_auth_dep`:

```jinja2
{% if factories %}
from polyfactory.factories.pydantic_factory import ModelFactory
{% endif %}
...
{% if has_auth_dep %}
import pytest
from {{ auth_dep_import_path }}.auth import AuthContext


@pytest.fixture
def auth_context() -> AuthContext:
    """Return the AuthContext injected into generated test clients.

    This file is scaffolded once and safe to edit.  Customize here to supply
    your application-specific context, e.g.:
        return AuthContext(operator_id=1, partner_id=42)
    """
    return AuthContext()
{% endif %}
```

**`testscaffold.py` changes.**

`_scaffold_conftest()` currently returns early if `not factories`.  Extend to also proceed
when `has_auth_dep`.  Add `has_auth_dep: bool` and `auth_dep_import_path: str | None`
parameters; thread into the template context and into the append-only path.

In `scaffold()`, accumulate `any_has_auth` across tag contexts (`context["has_auth_dep"]`
is already computed per tag in `_build_test_context()`) and pass to `_scaffold_conftest`.
`auth_dep_import_path` is constant per project (`self._config.dependencies.import_path`).

Append-only path (existing conftest.py present, no overwrite): if `has_auth_dep` and
`"def auth_context("` is not in the existing file, prepend the auth import(s) and fixture
to `new_lines`, guarding for already-present `import pytest` and the auth import line to
avoid duplicates.

**Files touched:**

- `src/pyoas/fastapi/templates/test.py.jinja2`
- `src/pyoas/fastapi/templates/conftest.py.jinja2`
- `src/pyoas/fastapi/testscaffold.py`
  - `_scaffold_conftest()` signature + body
  - `scaffold()` — collect `any_has_auth`, pass to conftest builder
- `tests/fastapi/test_testscaffold.py` — update any tests asserting on `AuthContext()`
  in client fixture bodies; add a test for the append-only path that adds `auth_context`
  to an existing conftest.py that lacks it
- `tests/fastapi/__snapshots__/test_testscaffold.ambr` — regenerate with
  `uv run pytest tests/fastapi/test_testscaffold.py --snapshot-update`

**Key existing code locations:**

| Location | Purpose |
|---|---|
| `testscaffold.py:490–568` | `_scaffold_conftest()` — full method to modify |
| `testscaffold.py:336–438` | `scaffold()` — tag loop + conftest call site |
| `testscaffold.py:903–907` | `has_auth_dep` computation (per-tag, in `_build_test_context`) |
| `test.py.jinja2:24–31` | `client` fixture (change here) |
| `test.py.jinja2:41–50` | `client_with_mock` fixture (change here) |
| `conftest.py.jinja2:1–20` | current conftest template (polyfactory only) |
| `tests/fastapi/test_testscaffold.py:72–85` | main snapshot test to update |
| `tests/fastapi/__snapshots__/test_testscaffold.ambr` | snapshot file to regenerate |

**Verification.**

```bash
# 1. Regenerate snapshots after template changes
uv run pytest tests/fastapi/test_testscaffold.py --snapshot-update

# 2. Full QA
uv run pytest && uv run ruff check src/ && uv run mypy src/

# 3. Smoke-test against nova-data-api (/Users/rawi/Documents/swch/nova-data-api)
#    Run: pyoas generate (with overwrite: true)
#    Assert: tests/generated/conftest.py contains auth_context fixture
#    Assert: tests/generated/test_*.py client fixtures accept auth_context param
#    Edit conftest.py auth_context to: return AuthContext(operator_id=1, partner_id=1)
#    Run: pytest tests/generated/ — should pass
```

- [x] Update `test.py.jinja2` — parametrize `client` and `client_with_mock`
- [x] Update `conftest.py.jinja2` — conditional polyfactory import + `auth_context` fixture
- [x] Update `testscaffold.py` — thread `has_auth_dep` / `auth_dep_import_path` to conftest builder
- [x] Update `_scaffold_conftest` append-only path to add `auth_context` if missing
- [x] Update/add tests in `test_testscaffold.py`
- [x] Regenerate snapshots

---

## Tier 3 — Developer experience (target 0.3.x)

---

### T3-A · CLI progress output

**Problem.** Generation runs silently. For a 100-tag spec, the CLI appears
frozen for seconds with no feedback.

**Fix.** Add a thin progress reporter (no third-party dep — just `print` to
stderr) that emits:
```
[models]  pets (3 schemas) ...
[models]  orders (7 schemas) ...
[routers] pets (4 endpoints) ...
```
Gate behind `--quiet` flag (suppress all progress, keep errors) and respect
`--verbose` flag (add timing per file). Both flags accepted by all generation
commands.

**Files touched:** `core/cli.py`, `models/generator.py`,
`fastapi/generator.py`.

- [x] Add `--quiet` / `--verbose` flags to generation commands
- [x] Progress reporter utility in `core/utils.py`
- [x] Thread through model generator
- [x] Thread through router generator

---

### T3-B · `--json` output for `doctor` and `validate`

**Problem.** CI pipelines that want to parse diagnostic output programmatically
must screen-scrape coloured text. This is fragile.

**Fix.**
- Add `--json` flag to `pyoas doctor` and `pyoas validate`.
- Emit a structured JSON object to stdout:
  ```json
  {"status": "error", "checks": [{"name": "missing_operation_ids", "severity": "error", "paths": ["/pets GET"]}]}
  ```
- `doctor.py` already returns structured check results internally — just needs a
  JSON serialization path.

**Files touched:** `core/cli.py`, `core/doctor.py`.

- [x] Add `--json` flag
- [x] Serialize doctor results
- [x] Serialize validate results
- [x] Test JSON output format

---

### T3-C · Populate CHANGELOG from git history

**Problem.** `CHANGELOG.md` has version headings but no content. This is a
trust signal for evaluators on PyPI.

**Fix.** Manually populate v0.1.0 and v0.1.1 entries from `git log`. Going
forward, Commitizen (`uv run cz bump`) will auto-populate on each bump
(already configured via `update_changelog_on_bump = true`). The issue is that
the initial commits did not use conventional commit prefixes so Commitizen
skipped them.

**Action.** Run `git log --oneline` and manually write bullet points for each
meaningful commit into `CHANGELOG.md` under the correct version.

- [x] Populate v0.1.0 entries
- [x] Populate v0.1.1 entries
- [x] Verify `cz bump` generates v0.2.0 entry correctly on next release

---

### T3-D · Example project

**Problem.** Users cannot see what pyoas generates before installing it.
No "before/after" exists in the repo.

**Fix.** Add `examples/petstore/` directory containing:
- `openapi.yaml` — minimal petstore spec (10 operations, 3 tags)
- `pyoas.yaml` — full config with services + tests + skills enabled
- `src/generated/` — committed generated output
- `src/services/` — hand-written service implementations
- `tests/generated/` — committed test scaffolding
- `README.md` — walkthrough

The example output should be kept in sync with the generator via a CI step
(`pyoas diff` exits 1 if example is stale).

**Files touched:** new `examples/petstore/` tree.

- [x] Write petstore spec
- [x] Write pyoas.yaml
- [x] Generate and commit output
- [x] Write example README
- [x] Add CI step to keep it in sync

---

### T3-E · Incremental generation (hash-based skip)

**Problem.** Every `pyoas generate` run regenerates every tag unconditionally.
For a 50-tag spec with 5 changed schemas, 45 tags are written unnecessarily,
invalidating editor reload, `git diff` noise, and slowing watch mode.

**Fix.**
1. After resolving the spec, compute a per-tag hash:
   `sha256(tag_name + json.dumps(sorted_tag_operations) + json.dumps(relevant_schemas))`.
2. Store hashes in `{output_dir}/.pyoas_cache.json` (a dict of
   `{tag: hash, "_config": config_hash}`).
3. Before writing each tag's output, compare hash against cache.
   Skip write and log `[skip] pets (unchanged)` if matching.
4. Invalidate all hashes when config changes (compare config hash stored in cache).
5. `--clean` flag bypasses cache entirely.
6. Cache file should be added to `.gitignore`.

**Files touched:** `models/generator.py`, `fastapi/generator.py`,
new `core/cache.py`.

- [x] `core/cache.py` — hash + read/write
- [x] Model generator: check/update cache
- [x] Router generator: check/update cache
- [x] `--clean` bypasses cache
- [x] `.gitignore` entry
- [x] Tests

---

### T3-F · `pyoas fix` command

**Problem.** `doctor` diagnoses but does not fix. Users must manually add
`operationId`s, normalize tags, and deduplicate schemas.

**Fix.** New `pyoas fix [--config PATH] [--dry-run]` command that:
1. Reads the spec.
2. Auto-assigns `operationId` for any operation missing one
   (`{method}_{path_snake_case}`).
3. Normalizes tag casing (all tags title-cased, or lowercase — configurable).
4. Removes duplicate `operationId`s by appending a numeric suffix.
5. Writes the fixed spec back in-place (YAML or JSON, matching input).
6. `--dry-run` prints a diff of changes without writing.
7. After fixing, re-runs doctor to confirm issues resolved.

**Files touched:** `core/cli.py`, new `core/fixer.py`.

- [x] `core/fixer.py`
- [x] `pyoas fix` CLI command
- [x] `--dry-run` flag
- [x] Tests

---

### T3-G · Extended doctor checks

**Problem.** Two generation-quality issues are not caught pre-flight, causing
silent bad output rather than an actionable warning:

1. **Parameter shadowing** — When a path parameter (`/items/{id}`) and a
   query or header parameter share the same name (`id`) in the same operation,
   the generated Python function will have a duplicate argument name →
   `SyntaxError` at import time.
2. **Missing 2xx response schema** — When an operation defines no 2xx response
   schema (or defines `{}` / no `content`), the router generator emits
   `response_model=None` and the return type annotation is `Any`. This silently
   kills client-side type safety. Common mistake in incomplete specs.

**Fix.**
- Add `parameter_shadowing` check (error): iterate each operation's
  `parameters` list; collect path-param names; warn for any
  query/header/cookie param whose name matches a path param name in the same
  operation.
- Add `missing_success_response` check (warning): for each operation, scan
  `responses` for any 2xx key. If none exists, or the matching response has no
  `content` block, emit the warning with the operation path + method.
- Both checks follow the existing `DoctorCheck` result structure and appear in
  both text and `--json` output.
- `pyoas fix` does **not** attempt to auto-fix either (parameter shadowing
  requires human judgement; missing schema requires domain knowledge of the
  return type).

**Files touched:** `core/doctor.py`, `tests/core/test_doctor.py`.

**Tests:** add fixture paths that trigger each new check; assert check name,
severity, and affected operation appear in results.

- [x] `parameter_shadowing` doctor check
- [x] `missing_success_response` doctor check
- [x] Tests for both checks
- [x] JSON output includes both new check names

---

## Tier 4 — Differentiation (target 0.4+)

These are larger features with clear implementation paths now that Tier 1–3 is
complete. Each is broken down to the same task-level detail as earlier tiers.

---

### T4-A · Jinja2 filter extension point

**Problem.** The only way to change how OpenAPI types map to Python types is to
fork the templates. Common real-world customisations (e.g. `format: uri` →
`AnyUrl`, `format: uuid` → `UUID`, custom validation decorators) require
maintaining a template fork across upgrades.

**Design.**

```yaml
# pyoas.yaml
extensions:
  filters: myapp.pyoas_extensions:custom_filters   # module:attr returning dict[str, Callable]
  globals: myapp.pyoas_extensions:custom_globals   # module:attr returning dict[str, Any]
```

`custom_filters` must be a callable that returns `dict[str, Callable]`.
`custom_globals` must be a callable that returns `dict[str, Any]`.
Both are optional. The module is loaded at render time via `importlib`.

**Files touched:** `core/config.py`, `core/renderer/__init__.py`,
`core/doctor.py`, `core/cli.py` (init template), new
`tests/core/test_renderer_extensions.py`.

**Implementation tasks.**

1. **ExtensionsConfig dataclass + YAML key** — Add `ExtensionsConfig(filters:
   str | None = None, globals: str | None = None)` to `config.py`; add
   `extensions: ExtensionsConfig = field(default_factory=ExtensionsConfig)` to
   `Config`; update `pyoas init` template to include commented-out example
   block.

2. **importlib loader in Renderer** — In `core/renderer/__init__.py:__init__`,
   after constructing `self._env`, call `_load_extensions(config.extensions)`.
   `_load_extensions()` splits `"module:attr"` strings, `importlib.import_module`
   the module, `getattr` the attr, calls it, and merges into
   `self._env.filters` / `self._env.globals`. Raise `ConfigError` with a
   human-readable message on `ImportError` or missing attr.

3. **Doctor validation** — Add `extensions_load` check (error): attempt the
   same `_load_extensions()` call in a dry-run mode; report any `ImportError`
   or bad `module:attr` format before generation starts. Prevents silent
   template failures at render time.

4. **Thread through generators** — Both `ModelGenerator` and `RouterGenerator`
   construct `Renderer(config=...)`; no change needed if Renderer reads
   `config.extensions` internally. Verify the `Renderer` constructor signature
   already accepts the full `Config` (it does — `renderer/__init__.py` line 18).

5. **Tests** — `test_renderer_extensions.py`: create a temp module with a
   filter dict; pass via config; assert filter appears in rendered output.
   Separate test: missing module raises `ConfigError` at renderer init.
   Doctor test: assert `extensions_load` check catches bad module path.

- [x] `ExtensionsConfig` dataclass + `Config` field + YAML init template block
- [x] `_load_extensions()` in `core/renderer/__init__.py`
- [x] `extensions_load` doctor check
- [x] Tests (renderer filter injection + missing module error + doctor check)
- [x] `pyoas.yaml` schema comment documentation

---

### ~~T4-B · SQLAlchemy 2.0 model output target~~ — CANCELLED

> **Decision (2026-05-10):** T4-B will not be implemented. OpenAPI describes
> the API contract (wire format); SQLAlchemy models describe the persistence
> contract (DB schema). These two layers diverge in almost every non-trivial
> project: API responses are denormalized projections while DB tables are
> normalized, computed fields have no stored column, audit/soft-delete/tenant
> columns are never in the API spec, and OAS `oneOf`/arrays/nested objects map
> to inheritance hierarchies or join tables — not simple columns. The generated
> output would require such heavy rework that it provides negative value.
> A scaffold-once model (like `services/`) was considered but rejected for the
> same reason: the structural mismatch means users spend more time unwinding
> generated code than writing from scratch.
> **T4-D (plugin architecture) is the better investment** — it makes pyoas
> extensible as a platform; an SA generator can be a community plugin rather
> than a first-party opinion.

~~**Problem.** Projects that use both an OpenAPI spec and a database need to
maintain Pydantic models and SQLAlchemy models separately, leading to
duplication and drift. `pyoas[sqlalchemy]` would generate `DeclarativeBase`
models from the same spec.~~

**Design decisions (resolved here so implementation is unambiguous).**

| Decision | Resolution |
|---|---|
| Primary key | Config option `sqlalchemy.primary_key_field: str = "id"`. If the schema has a property matching that name, it becomes `Column(..., primary_key=True)`. Otherwise, a synthetic `id = Column(Integer, primary_key=True, autoincrement=True)` is prepended. |
| Relationship inference | `$ref` fields → `relationship()` if the target schema is also being generated as a SQLAlchemy model. Arrays of `$ref` → one-to-many with a generated FK column. Non-model refs → plain `Column(JSON)`. |
| Type mapping | See table below. Falls back to `Column(JSON)` for unrecognised formats. |
| Dual output | Config `sqlalchemy.generate: bool = False`; models land in `output.sqlalchemy_models` (default `"src/generated/sqlalchemy_models"`). Pydantic models still generated unchanged. |

**OpenAPI → SQLAlchemy Column type table:**

| OAS type/format | SQLAlchemy Column |
|---|---|
| `string` | `String` |
| `string / date-time` | `DateTime` |
| `string / date` | `Date` |
| `string / uuid` | `Uuid` |
| `string / email` | `String(254)` |
| `integer / int32` | `Integer` |
| `integer / int64` | `BigInteger` |
| `number / float` | `Float` |
| `number / double` | `Double` |
| `boolean` | `Boolean` |
| `array` | `JSON` (unless $ref array — see relationship inference) |
| `object` (inline) | `JSON` |

**Files touched:** `core/config.py`, new `models/sqlalchemy_generator.py`,
new `models/sqlalchemy_type_mapper.py`, new
`models/templates/sqlalchemy_model.py.jinja2`, `pyproject.toml` (optional
extra), `core/cli.py` (generate command wiring), new
`tests/models/test_sqlalchemy_generator.py`.

**Implementation tasks.**

1. **`SQLAlchemyConfig` + `Config` wiring** — Add `SQLAlchemyConfig(generate:
   bool = False, output: str = "src/generated/sqlalchemy_models", primary_key_field:
   str = "id")` to `config.py`; add `sqlalchemy: SQLAlchemyConfig` to `Config`.
   Gate the import of `sqlalchemy` behind a try/except `ImportError` with a
   helpful "install pyoas[sqlalchemy]" message.

2. **`models/sqlalchemy_type_mapper.py`** — Pure function
   `schema_to_column_type(schema: dict) -> str` that applies the mapping table
   above. Separate from `types.py` to avoid coupling. Returns a string like
   `"Column(String)"` or `"Column(DateTime)"` for direct template insertion.

3. **Relationship detector** — In `SQLAlchemyGenerator`, after collecting
   schemas per tag, cross-reference `$ref` fields: if the target schema is in
   the same generation set, emit `relationship()` + FK column. Use
   `classifier.py`'s existing schema-to-tag map for target lookup.

4. **`sqlalchemy_model.py.jinja2` template** — Render:
   ```python
   from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
   from sqlalchemy import String, Integer, ...

   class Base(DeclarativeBase): pass

   class Pet(Base):
       __tablename__ = "pets"
       id: Mapped[int] = mapped_column(primary_key=True)
       name: Mapped[str] = mapped_column(String)
       owner: Mapped["Owner"] = relationship(back_populates="pets")
   ```
   Use `Mapped[T]` / `mapped_column()` syntax (SQLAlchemy 2.0 only). Each
   model in a separate class block in the file. One file per tag (mirrors
   Pydantic output).

5. **`SQLAlchemyGenerator` class** — Mirror `models/generator.py` structure:
   accepts resolved spec + config, iterates tags, applies cache, writes output.
   Reuse `GenerationCache` with a `sqlalchemy_` prefix in cache keys to avoid
   collision with Pydantic cache entries.

6. **Wire into `core/cli.py`** — In `generate` and `models` commands, after
   Pydantic generation, check `config.sqlalchemy.generate` and call
   `SQLAlchemyGenerator.generate()`.

7. **Tests** — `test_sqlalchemy_generator.py`: snapshot tests using the
   existing `tests/fixtures/` YAML files; assert `mapped_column`, `relationship`,
   and FK columns appear correctly. Separate unit tests for
   `schema_to_column_type`.

- ~~[ ] `SQLAlchemyConfig` + `Config` field~~
- ~~[ ] `models/sqlalchemy_type_mapper.py` with unit tests~~
- ~~[ ] Relationship detector logic~~
- ~~[ ] `sqlalchemy_model.py.jinja2` template~~
- ~~[ ] `SQLAlchemyGenerator` class with cache support~~
- ~~[ ] Wire into `generate` + `models` CLI commands~~
- ~~[ ] Snapshot tests against existing fixtures~~
- ~~[ ] `pyoas[sqlalchemy]` optional extra in `pyproject.toml`~~

---

### T4-C · `pyoas migrate` command

**Problem.** API-first teams review spec changes in PRs but have no tooling to
surface breaking vs non-breaking changes. Engineers must manually diff YAML
files or trust spec authors to annotate changes.

**Design.**

```
pyoas migrate OLD_SPEC NEW_SPEC [--json] [--breaking-only]
```

Reads two spec files (path or URL), computes a structured diff, classifies
each change, and exits non-zero if any breaking changes are found (useful for
CI gates).

**Breaking vs non-breaking classification:**

| Change | Classification |
|---|---|
| Operation removed | Breaking |
| Required request field removed | Breaking |
| Response field type narrowed (e.g. `number` → `integer`) | Breaking |
| `nullable: true` → `nullable: false` on response field | Breaking |
| 2xx response schema changed to incompatible type | Breaking |
| New required request field added | Breaking |
| Operation added | Non-breaking |
| Optional request field added | Non-breaking |
| Optional response field added | Non-breaking |
| Description / example changed | Non-breaking |
| `nullable: false` → `nullable: true` on response field | Non-breaking |
| Type widened (e.g. `integer` → `number`) | Non-breaking |

**Files touched:** new `core/differ.py`, new `core/migrate.py` (CLI wiring +
output formatters), `core/cli.py`.

**Implementation tasks.**

1. **`core/differ.py`** — Pure function
   `diff_specs(old: dict, new: dict) -> SpecDiff` where `SpecDiff` is a
   dataclass:
   ```python
   @dataclass
   class SpecDiff:
       added_operations: list[OperationRef]
       removed_operations: list[OperationRef]
       changed_operations: list[OperationChange]
       added_schemas: list[str]
       removed_schemas: list[str]
       changed_schemas: list[SchemaChange]
   ```
   Build operation index (`{method}:{path}` → operation dict) for each spec.
   Set-intersect to find added/removed. For changed: compare request body
   schemas and 2xx response schemas field-by-field (recursive dict diff).
   No dependency on resolver: accept already-resolved specs.

2. **Breaking-change classifier** — `classify_changes(diff: SpecDiff) ->
   list[MigrationIssue]` where `MigrationIssue` has `severity: "breaking" |
   "non-breaking"`, `path`, `description`. Apply the table above. Pure
   function; easily testable without file I/O.

3. **`core/migrate.py`** — CLI command handler:
   - Load and resolve both specs via existing `parser` + `resolver`.
   - Call `diff_specs` + `classify_changes`.
   - Format and emit output (text or JSON).
   - Exit with code `1` if any breaking changes found (CI gate).

4. **Text output formatter** — Grouped by breaking/non-breaking, coloured
   (same style as `doctor`), with path + method per issue.

5. **JSON output** —
   ```json
   {
     "breaking": [{"path": "/pets", "method": "DELETE", "issue": "operation_removed"}],
     "non_breaking": [...],
     "summary": {"breaking": 1, "non_breaking": 3}
   }
   ```

6. **Wire into CLI** — `pyoas migrate OLD NEW [--json] [--breaking-only]`.
   `--breaking-only` suppresses non-breaking output (useful for CI).

7. **Tests** — `tests/core/test_differ.py`: unit tests for `diff_specs` and
   `classify_changes` with synthetic dicts (no file I/O). Integration test:
   diff petstore v3.0 against a hand-modified copy with one operation removed
   and one field added; assert correct classification.

- [x] `SpecDiff` + `OperationChange` + `SchemaChange` dataclasses
- [x] `diff_specs()` in `core/differ.py`
- [x] `classify_changes()` breaking-change rules
- [x] `core/migrate.py` — load + resolve + format + exit code
- [x] Text formatter (coloured, grouped)
- [x] JSON formatter
- [x] Wire into `core/cli.py`
- [x] Unit tests for differ + classifier
- [x] Integration test with modified petstore fixture

---

### T4-D · Plugin architecture

**Problem.** All generation logic is hardcoded. Adding a new output target
(SQLAlchemy, TypeScript, Terraform) or a new spec transformation requires
modifying pyoas internals. Third-party packages cannot extend pyoas without
forking.

**Design.** Minimal lifecycle protocol — only the hooks that can be implemented
without refactoring the generators. Hooks are called synchronously. No
dependency injection framework.

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Plugin(Protocol):
    name: str                          # Unique plugin identifier
    version: str                       # For diagnostics

    def on_spec_loaded(
        self, spec: dict, resolved: dict
    ) -> tuple[dict, dict]:
        """Return (raw, resolved) — may modify in place or replace."""
        ...

    def on_model_file_written(
        self, tag: str, path: str, content: str
    ) -> str:
        """Return (potentially modified) file content after Pydantic model generation."""
        ...

    def on_router_file_written(
        self, tag: str, path: str, content: str
    ) -> str:
        """Return (potentially modified) file content after FastAPI router generation."""
        ...

    def on_generate_complete(self, stats: dict) -> None:
        """Called once after all files written. stats = {tags, files_written, skipped}."""
        ...
```

Plugins are discovered via `pyproject.toml` entry points:

```toml
[project.entry-points."pyoas.plugins"]
my_plugin = "mypackage.plugin:MyPlugin"
```

And optionally listed in `pyoas.yaml` for explicit activation or ordering:

```yaml
plugins:
  - mypackage.plugin:MyPlugin   # explicit activation (no entry-point needed)
```

**Note:** T4-D does **not** refactor `ModelGenerator` or `RouterGenerator`
internals. It adds a thin hook layer around existing file-write operations.
This avoids breaking changes while enabling the most common use cases
(post-processing generated content, adding custom headers, injecting imports).

**Files touched:** new `core/plugins.py`, `core/config.py` (plugins list),
`models/generator.py` (call hooks after write), `fastapi/generator.py` (call
hooks after write), `core/cli.py` (load + validate plugins), `core/doctor.py`
(new `plugin_load` check), new `tests/core/test_plugins.py`.

**Implementation tasks.**

1. **`Plugin` Protocol in `core/plugins.py`** — Define the protocol above.
   Add `PluginLoader` class: `load_from_config(config) -> list[Plugin]` that:
   - Reads `config.plugins` list (explicit module:class paths)
   - Discovers entry points under `"pyoas.plugins"` group
   - Instantiates each class (no-args constructor)
   - Validates each instance satisfies `isinstance(obj, Plugin)` (runtime_checkable)

2. **`plugins: list[str]` in `Config`** — New field; default empty list.
   Each entry is `"module:ClassName"` or just `"module"` (import the first
   `Plugin` implementor found).

3. **`plugin_load` doctor check** — Same dry-run load as T4-A's
   `extensions_load`; report any failing imports or non-Protocol classes.

4. **Hook calls in `ModelGenerator`** — After each file write, call
   `on_model_file_written(tag, path, content)` on each loaded plugin; replace
   file content with return value. If any plugin returns an empty string, raise
   `PluginError` (prevents accidental deletion).

5. **Hook calls in `RouterGenerator`** — Same pattern for
   `on_router_file_written`.

6. **`on_spec_loaded` hook in CLI** — After parsing + resolving in
   `generate` / `models` / `fastapi` commands, pass `(raw, resolved)` through
   the plugin chain before handing to generators.

7. **`on_generate_complete` hook** — Called once in `generate` command after
   all generators finish, with stats dict.

8. **Tests** — `test_plugins.py`: create a minimal `Plugin` implementation
   in a test fixture module; assert hook is called with correct arguments and
   return value is used. Test that `PluginLoader` discovers entry points (mock
   `importlib.metadata.entry_points`). Doctor test: assert `plugin_load` check
   catches bad module path.

- [x] `Plugin` Protocol + `PluginLoader` in `core/plugins.py`
- [x] `plugins: list[str]` in `Config`
- [x] `plugin_load` doctor check
- [x] Hook calls in `ModelGenerator` (after file write)
- [x] Hook calls in `RouterGenerator` (after file write)
- [x] `on_spec_loaded` hook in CLI generate commands
- [x] `on_generate_complete` hook in CLI generate command
- [x] Tests (hook invocation + entry-point discovery + doctor check)
- [x] Example plugin in `examples/` showing import injection use-case

---

## Cross-cutting concerns

These apply across all tiers and should be kept in mind during implementation.

| Concern | Guidance |
|---|---|
| Snapshot tests | Run `uv run pytest --snapshot-update` after any template change |
| Conventional commits | Use `fix:` for T1/T3-G, `feat:` for T2–T3, `feat!:` for T4 breaking |
| Integration tests | Run `uv run pytest --run-integration` before any release |
| Config backwards compat | New config keys must have defaults; never rename existing keys |
| Template override contract | Any variable added to a template context must be documented; user overrides rely on the contract |
| Type annotations | All new functions must be fully typed; `uv run mypy src/` must pass |
| Ruff | `uv run ruff check src/` must pass; line length 88, select E F I UP |
| T4 ordering | T4-A is independent. T4-C is independent. T4-B cancelled. T4-D is next and last. |

---

## Release cadence target

| Version | Contents |
|---|---|
| `0.1.2` | T1-A, T1-C (quick correctness fixes) |
| `0.1.3` | T1-B, T1-D (allOf + discriminator) |
| `0.2.0` | T2-A through T2-E + T3-C (CHANGELOG) |
| `0.3.0` | T2-F + T3-A through T3-F |
| `0.3.1` | T3-G (extended doctor checks — patch, no new generation output) |
| `0.4.0` | T4-A (filter extensions) + T4-C (`pyoas migrate`) |
| ~~`0.5.0`~~ | ~~T4-B (SQLAlchemy target)~~ — cancelled |
| `0.5.0` | T4-D (plugin architecture) |
