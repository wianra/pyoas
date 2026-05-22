# pyoas Codebase Findings

> Initial analysis: 2026-05-19 · v0.5.1 · B-01–T-13
> Phase 1 audit: 2026-05-22 · v0.7.1 · B-15–B-26 (QA_PLAN.md Phase 1)
> WP-11: 2026-05-22 · B-23, B-24, B-25, A-10 closed
>
> Status legend: `[ ]` open · `[x]` fixed · `[-]` won't fix

---

## Bugs

### B-01 · `"2XX"` wildcard response codes silently ignored
**Severity**: High
**Files**: `fastapi/params.py:418`, `fastapi/params.py:447`
**Status**: [x]

`resolve_response_type` and `resolve_response_status_code` both use `re.match(r"^2\d{2}$", code)`, which only matches 3-digit numeric codes. OAS 3.0/3.1 explicitly allows `"2XX"` / `"2xx"` wildcard codes. Operations that use only wildcard codes get `response_model=None` (falls back to `"None"`), silently dropping the response schema.

Compounding this: the doctor check in `doctor.py:193` uses `str(k).startswith("2")` (correctly handles wildcards), so the doctor reports no issue while generation produces wrong output.

**Fix**: Replace the regex in `resolve_response_type` and `resolve_response_status_code` with a check that also matches `"2XX"` / `"2xx"`.

---

### B-02 · `has_circular` context variable computed but never used in template
**Severity**: Low
**Files**: `models/context.py:198`, `models/templates/model.py.jinja2`
**Status**: [x] *(WP-6)*

`_build_models_context` calls `has_circular_refs(...)` and passes `has_circular` in the Jinja2 context, but `model.py.jinja2` never references it. Dead computation on every generation pass.

**Fix**: Either use `has_circular` in the template (e.g., emit `model_rebuild()` for circular schemas), or remove the computation.

---

### B-03 · `find_split_schema_names` misses inherited `readOnly`/`writeOnly`
**Severity**: Medium
**File**: `core/analysis.py:237-249`
**Status**: [x] *(WP-7)*

Only inspects `schema.get("properties")` at the top level. If a schema uses `allOf` inheritance and the **parent** carries `readOnly`/`writeOnly` properties, the child is never added to `split_schema_names`. The router generator then does not substitute the `Write` variant for request bodies of those child schemas.

**Fix**: Recurse into `allOf` sub-schemas (following `$ref` entries) when checking for read/write-only properties.

---

### B-04 · Service scaffolder method insertion targets wrong position via string search
**Severity**: Low
**File**: `fastapi/scaffold.py:216-221`
**Status**: [x] *(WP-8)*

```python
dep_fn = f"async def get_{tag_dirname}_service"
if dep_fn in existing_src:
    insert_at = existing_src.index(dep_fn)
```

`str.index()` finds the **first** occurrence. If the function name string appears in a docstring or comment earlier in the file, method stubs are inserted at the wrong position.

**Fix**: Use AST to locate the dependency function node and insert stubs before its line offset.

---

### B-05 · Drift detection is order-sensitive for keyword-only arguments
**Severity**: Low
**File**: `fastapi/scaffold.py:372-382`, `fastapi/scaffold.py:397-408`
**Status**: [x] *(WP-6)*

`_expected_sig_str` iterates `op["parameters"]` in spec order; `_service_sig_from_ast` iterates `func.args.kwonlyargs` in file order. Reordering keyword-only parameters in a service method (a harmless refactor) incorrectly triggers drift detection.

**Fix**: Sort both sides by parameter name before comparing.

---

### B-06 · Auth imports appended to bottom of `conftest.py` instead of top
**Severity**: Medium
**File**: `fastapi/testscaffold.py:569-589`
**Status**: [x] *(WP-6)*

When adding the `auth_context` fixture to an existing `conftest.py`, the code does:

```python
new_lines = missing_imports + auth_fixture_lines + new_lines
# ...
updated = existing_src.rstrip() + "\n" + "\n".join(new_lines) + "\n"
```

`new_lines` is appended at the **end** of the file, so `import pytest` and the `AuthContext` import land after all existing function definitions. Module-level usages of `AuthContext` in type annotations (without `from __future__ import annotations`) would raise `NameError`.

**Fix**: Insert missing imports at the top of `existing_src`, before the first non-comment line.

---

### B-07 · `polyfactory` listed as runtime dependency but only used in scaffolded user code
**Severity**: High
**File**: `pyproject.toml:17`
**Status**: [x]

`polyfactory>=2.0` is in `[project.dependencies]` (core runtime). Polyfactory is only referenced in the scaffolded `conftest.py` templates — pyoas's own code never imports it. Every `pip install pyoas` user gets polyfactory unnecessarily.

**Fix**: Move `polyfactory` to an optional extra (e.g., `[fastapi]` or a new `[testing]` extra) or to `[dependency-groups].dev`.

---

### B-08 · `bytes` response type generates invalid `response_model=bytes`
**Severity**: Medium
**Files**: `fastapi/params.py:481-483`, `fastapi/templates/router.py.jinja2:40`
**Status**: [x]

`resolve_response_type` returns `"bytes"` for a single non-JSON 2xx response (e.g., `application/pdf`). The template then emits `response_model=bytes`. FastAPI does not validate `bytes` as a Pydantic model; the correct pattern for binary responses is to return a `Response` object. The template already excludes `"Response"` from `response_model=`, but not `"bytes"`.

**Fix**: In `resolve_response_type`, return `"Response"` (not `"bytes"`) when all 2xx responses are non-JSON content, mirroring the existing mixed-content logic.

---

### B-09 · `_extract_model_class_names` regex fails for nested-bracket Literals
**Severity**: Low
**File**: `fastapi/generator.py:313`
**Status**: [x] *(WP-6)*

```python
combined = re.sub(r"Literal\[[^\]]*\]", "", combined)
```

`[^\]]*` means "no `]` characters", so `Literal[tuple[str, int]]` is stripped only up to the first `]`, leaving `]` in the string. This can cause spurious PascalCase tokens to be extracted and incorrectly treated as model class names.

**Fix**: Use a proper balanced-bracket strip (recursive regex or a small parser), similar to `_parse_generic_title` in `core/analysis.py`.

---

### B-10 · Incremental cache doesn't invalidate when generic group `home_tag` changes
**Severity**: High
**File**: `models/generator.py:191-210`
**Status**: [x]

The per-tag cache hash only includes raw schemas belonging to that tag. Generic group detection (`detect_generic_groups_global`) is global — adding a new `Paginated[NewModel]` in Tag B can change `Paginated.home_tag` from `"pets"` to `None` (shared). Tag A's (pets) cache is not invalidated, so `pets.py` continues to import `Paginated` from `pets` instead of `shared`, causing an `ImportError` at runtime.

**Fix**: Include a hash of the global generic group configuration in each tag's cache key.

---

### B-11 · Shared schema name detection uses substring matching, not whole-word
**Severity**: Medium
**File**: `models/context.py:175-188`
**Status**: [x]

```python
for sname in all_shared_names:
    if sname in f["python_type"]:
        referenced_shared.add(sname)
```

A shared schema named `"Pet"` incorrectly matches any field type containing `"PetList"` or `"PetStatus"`, adding a spurious import from `shared`.

**Fix**: Replace with `re.search(r'\b' + re.escape(sname) + r'\b', f["python_type"])`.

---

### B-12 · `on_generate_complete` plugin hook never called
**Severity**: High
**Files**: `core/plugins.py:58-64`, `core/cli.py`
**Status**: [x] *(hook already called at `cli.py:400-407`; confirmed in WP-5)*

The `Plugin` protocol documents `on_generate_complete(stats)` as "called once after all files have been written." Neither `ModelGenerator.generate()`, `RouterGenerator.generate()`, nor any CLI command calls this hook. Plugins implementing it receive no callback.

**Fix**: Call `plugin.on_generate_complete(stats)` at the end of the `generate` CLI command, passing `{"files_written": len(written), "tags": all_tags, "skipped": skipped_count}`.

---

### B-13 · Consecutive underscores not collapsed in generated function names
**Severity**: Low
**File**: `fastapi/generator.py:544-545`
**Status**: [x] *(WP-6)*

```python
function_name = to_snake_case(re.sub(r"[^a-zA-Z0-9_]", "_", operation_id))
```

OperationIds like `"list-pets--v2"` produce `"list_pets__v2"` (double underscore). `to_snake_case` doesn't collapse consecutive underscores.

**Fix**: Add `re.sub(r"_+", "_", ...).strip("_")` after the substitution, consistent with the pattern already used in `generate_function_name`.

---

### B-14 · Stale docstring in router generator
**Severity**: Low
**File**: `fastapi/generator.py:4`
**Status**: [x] *(WP-6)*

```
"""RouterGenerator — orchestrates FastAPI router generation from an OpenAPI spec.

Milestone 3 will fill in the complete implementation.
"""
```

Leftover scaffolding text from a development milestone. Implementation is complete.

**Fix**: Remove the stale sentence.

---

### B-15 · `-> Response` endpoints recurse FastAPI's serializer
**Severity**: High
**Files**: `fastapi/testscaffold.py:287` (`_default_mock_return_repr`), `fastapi/templates/test.py.jinja2:54-65`
**Status**: [x] *(commit e6ebd33, 2026-05-21)*

Endpoints typed `-> Response` (binary downloads — PDF, CSV, octet-stream) emitted no `mock_service.fn.return_value = …` line in `test_endpoint_exists`. The unset `AsyncMock` returned was not a `Response` instance, so FastAPI fell through to `serialize_response → jsonable_encoder`, which recursed on `dict(mock)` until the stack blew (`RecursionError: maximum recursion depth exceeded`).

Discovered in nova-data-api on the `getInvoicePdf`, `getConsumerInvoicePdf`, `exportInvoicesCsv`, and `exportChargingSessionsCsv` endpoints.

**Fix**: `_default_mock_return_repr` now returns `'Response(content=b"", media_type="application/octet-stream")'` for `Response` types; the test template adds `from fastapi import Response` when any op needs it.

---

### B-16 · Required `list[Model]` body sent as `json={}` instead of `json=[]`
**Severity**: High
**File**: `fastapi/testscaffold.py:320` (`_minimal_body_repr`)
**Status**: [x] *(commit e6ebd33, 2026-05-21)*

When a request-body schema is `type: array`, `_minimal_body_repr` fell through to the empty-required-fields branch and returned `repr({})`. The generated `test_success` then sent `json={}` against a `list[X]` body, producing 422.

Discovered in nova-data-api on `updateCsIntegrationChargingStations` (body `list[StationToIntegrateDTO]`).

**Fix**: branch on `body_schema.get("type") == "array"` first and return `repr([])`.

---

### B-17 · `_default_value_for_field` produces `"example"` for array / object fields
**Severity**: High
**File**: `fastapi/testscaffold.py:167` (`_default_value_for_field`)
**Status**: [x] *(commit e6ebd33, 2026-05-21)*

`_FIELD_TYPE_DEFAULTS` lacked entries for `array` and `object`, so `_default_value_for_field` returned the literal string `"example"` for any required `list[Model]` / `dict[...]` field. The valid-base-body construction then produced bodies like `{"drivers": "example"}`, which Pydantic rejects → 422.

Discovered in nova-data-api on `bulkCreateDrivers` (`drivers: list[DriverCreateDTO]`).

**Fix**: handle `type == "array"` → `[]` and `type == "object"` → `{}` before the scalar fallback.

---

### B-18 · Route ordering: `/foo/{id}` shadows `/foo/{id}:cancel`
**Severity**: High
**File**: `fastapi/generator.py:427`
**Status**: [x] *(commit 352c178, 2026-05-21)*

The route sort key replaced `{param}` with `\xff` then lex-sorted. For two paths sharing a `{param}` segment, the bare-`{param}` variant sorted *before* the literal-suffixed variant because end-of-string compared less than `:` (0x3A). Starlette routes first-match with greedy `[^/]+`, so `GET /foo/1:cancel` matched `/foo/{id}` with `id="1:cancel"` and failed int coercion → 422.

The bug was hidden by `test_endpoint_exists` (asserts only `not in (404, 405)` — 422 silently passes); only `test_success` and `test_not_found` surfaced it.

Discovered in nova-data-api on `getDriverSubscriptionCancellationInfo` (which shared a path prefix with `getDriverSubscription`).

**Fix**: replace the flat string key with a per-segment tuple `(kind, normalized)` where `kind=0` for pure literal, `1` for literal-suffixed `{param}`, `2` for bare `{param}` — `kind 1 < kind 2` puts the literal-suffixed variant first. (`_route_sort_key` helper.)

---

### B-19 · Service stubs reference `Literal` without importing it
**Severity**: High
**Files**: `fastapi/scaffold.py:579-589` (`_build_service_context`), `fastapi/templates/service.py.jinja2`
**Status**: [x] *(commit e7045a1, 2026-05-21)*

Enum query/path/body parameters rendered as `Literal["a", "b"]` in the service stub, but the template only emitted `from typing import …` when `needs_any` or `needs_annotated` was true — `Literal` had no flag. Result: `Name 'Literal' is not defined` at runtime in any service that had at least one enum parameter.

**Fix**: add `needs_literal = "Literal[" in combined` and include `Literal` in the `typing` import list when set. Template now builds the `typing` import list from per-flag accumulators so future imports stay additive.

---

### B-20 · Service stubs reference `Response` without importing it
**Severity**: High
**Files**: `fastapi/scaffold.py:583-589`, `fastapi/templates/service.py.jinja2`
**Status**: [x] *(commit e7045a1, 2026-05-21)*

Same shape as B-19 but for `-> Response` (binary downloads). Detection uses a word-boundary regex `(?<![A-Za-z0-9_])Response(?![A-Za-z0-9_])` so types like `ChargingActivationResponseDTO` do not trigger a spurious `from fastapi import Response`.

**Fix**: emit `from fastapi import Response` from the same per-flag import list used by B-19.

---

### B-21 · Service stubs drop `…Write` split-variant imports
**Severity**: High
**File**: `fastapi/scaffold.py:599-605` (`_build_service_context` → `classify_model_imports`)
**Status**: [x] *(commit e7045a1, 2026-05-21)*

With `model_config.request_extra: forbid` the body schemas resolve to `…Write` split variants. `_build_service_context` accepted `split_schema_names` as a parameter but never forwarded it to `classify_model_imports`. The Write names then failed the schema-tag-map lookup and were dropped from the import block, leaving `body: ConsentDTOWrite` (etc.) as undefined references.

Discovered in nova-data-api on `profile.py` (`ConsentDTOWrite`, `VehicleDTOWrite`).

**Fix**: pass `split_schema_names=split_schema_names` to `classify_model_imports` in the service scaffolder, matching the router scaffolder's call site.

---

### B-22 · `auth_context` fixture imports appended mid-file (regression of B-06)
**Severity**: Medium
**File**: `fastapi/templates/conftest.py.jinja2`
**Status**: [x] *(commit 02d26a2, 2026-05-21)*

The `auth_context` fixture block lived at the end of the template, with its `import pytest` and `from …auth import AuthContext` lines inlined alongside it. Ruff flagged `E402` (module-level imports not at top of file). This is the same shape as B-06, which had been fixed in WP-6 but regressed at some point between then and v0.7.1 — strong signal we need a behavioural smoke test (Phase 2 of QA_PLAN.md) to keep it from coming back a third time.

**Fix**: hoist both imports into the existing top-of-file import block under the same `has_auth_dep` guard.

---

### B-23 · Re-export-only model files import `BaseModel`/`ConfigDict`/`Field` unused
**Severity**: Low
**Files**: 7 model files generated when a tag's schemas are all type aliases (e.g. `contacts.py`, `events.py`, `evses.py`, `mobility_providers.py`, `promotions.py`, `tariff_plans.py`, `terminal_groups.py`)
**Owner**: `models/scaffolder.py` / `models/templates/model.py.jinja2`
**Status**: [x] *(WP-11, 2026-05-22)*
**Surfaced by**: Phase 1 audit · ruff F401

When a tag's model file contains only type aliases (e.g. `PagingResultContactLightDTO = PagingResult[ContactLightDTO]`) and no actual classes, the template still emits `from pydantic import BaseModel, ConfigDict, Field` unconditionally. Pre-commit hooks downstream flag 21 F401s across these files.

**Fix**: `_build_models_context` now sets `needs_basemodel = any(not is_alias and not is_enum_class for rs in schemas)` and the `model.py.jinja2` pydantic import block is gated on it, parallel to the existing `typing`-import dynamic-name list pattern. `Discriminator`/`Tag`/`model_validator` remain emit-able for alias-only files since aliases CAN reference them.

---

### B-24 · `app/dependencies/auth.py` imports `dataclasses.field` unused
**Severity**: Low
**File**: `fastapi/deps_scaffold.py` / `fastapi/templates/dependency_auth.py.jinja2`
**Status**: [x] *(WP-11, 2026-05-22)*
**Surfaced by**: Phase 1 audit · ruff F401

The auth-dependency template imports `field` from `dataclasses` because the example usage shown in the docstring mentions `scopes: list[str] = field(default_factory=list)`. `field` is only referenced inside the docstring, never in code.

**Fix**: dropped `, field` from the template import. The docstring example still references `field(default_factory=list)` for instructional purposes — users adding such a field will re-add the import themselves.

---

### B-25 · `PagingResult.items` has `Field(default=None)` on a `list[T]` field
**Severity**: Medium
**File**: `models/schema_renderer.py` (whichever helper assigns `default` for `array` properties)
**Status**: [x] *(WP-11, 2026-05-22)*
**Surfaced by**: Phase 1 audit · `mypy --strict` `[arg-type]`

```python
class PagingResult(BaseModel, Generic[T]):
    items: list[T] = Field(default=None)   # arg-type: expected list[T], got None
```

Two problems: the typing is incompatible (`None` is not `list[T]`), and the runtime semantic is surprising — a missing `items` field deserializes to `None`, not `[]`. Both are wrong for a paginated wrapper.

**Fix**: `_build_field_kwargs` now takes the rendered `python_type` and emits `default_factory=list` only when the type is `list[…]` *without* a `| None` suffix (i.e., generic parents like `Paginated[T].items: list[T]`). Regular non-required arrays whose rendered type is `list[T] | None` still get `default=None`, preserving the existing semantic that "field absent in input → None in Python."

---

### B-26 · `class PagingResult(BaseModel, Generic[T])` should use PEP 695 syntax
**Severity**: Low
**File**: `models/schema_renderer.py` (generic-class rendering)
**Status**: [-] *(won't fix without a Python-version policy)*
**Surfaced by**: Phase 1 audit · ruff `UP046`

Ruff suggests `class PagingResult[T](BaseModel):` (PEP 695, Python 3.12+) instead of the explicit `Generic[T]` subclass. Functionally equivalent today; modernization only.

**Recommendation**: defer until pyoas drops Python 3.11 support, then flip the generator template.

---

## Missing OpenAPI Feature Support

### F-01 · `"2XX"` / `"2xx"` wildcard response codes
**Status**: [x]
See B-01. Affects response type resolution, status code selection, and doctor diagnostics.

---

### F-02 · Security scheme type not used in auth dependency generation
**Status**: [x] *(WP-8)*

`components/securitySchemes` is completely ignored. The generated `AuthContext` / `get_auth_context` stubs are always generic with no reference to the actual security type (Bearer JWT, OAuth2, API key, HTTP basic). OAuth2 scopes are emitted as comments only.

**Improvement**: Read `securitySchemes` to generate typed stubs (e.g., Bearer extraction vs. API key header extraction).

---

### F-03 · OAS 3.1 `const` keyword not handled
**Status**: [x] *(WP-7)*

`{"const": "active"}` should produce `Literal["active"]`. Currently produces `Any` (no `type`, no `enum`, no composition keyword). The ambiguous-schema doctor check fires, but generation silently falls back.

**Fix**: In `_base_type`, detect `"const"` before the `match raw_type` block and return `Literal[repr(const_value)]`.

---

### F-04 · `patternProperties` not handled
**Status**: [x] *(WP-9)*

Valid in OAS 3.1 (JSON Schema). Not handled; silently ignored. Should produce `dict[str, T]` for typed pattern-based maps, or at minimum `dict[str, Any]` with a warning.

---

### F-05 · `if`/`then`/`else` conditional schemas not handled
**Status**: [x] *(WP-9)*

Valid in OAS 3.1. Not handled; silently produces `Any`. Consider mapping to the `then` branch as a best-effort, with a warning.

---

### F-06 · `"default"` response code treated as missing
**Status**: [x]

`resolve_response_type` only scans `re.match(r"^2\d{2}$", code)` codes. Specs that define only a `"default"` response (no explicit `"200"` etc.) get `response_type = None`. The doctor flags these as "missing_success_response" — a false positive for specs using `"default"` as their success code.

**Fix**: If no `2xx` codes are found, fall back to the `"default"` response entry.

---

### F-07 · OAS Callbacks not processed
**Status**: [x] *(WP-10)*
`paths[…][method].callbacks` is not processed. Doctor now warns on operations with callbacks (`unprocessed_callbacks`). Generated routers emit a `# NOTE` comment listing the unprocessed callback names for each affected operation.

---

### F-08 · `allOf` with multiple `$ref`s emits union instead of composed model
**Status**: [x] *(WP-10 — confirmed already correct; regression test added)*

`allOf: [$ref/A, $ref/B]` already produces `class C(A, B): pass` via `_find_allof_bases` in `schema_renderer.py`. Confirmed with `test_allof_multi_ref_generates_composed_class_not_union`.

---

### F-09 · OAS 3.1 `$ref` + sibling keywords (nullable override) ignored
**Status**: [x] *(WP-9)*

In OAS 3.1, `{$ref: "…", nullable: true}` is valid. `schema_to_python_type` returns early on any top-level `$ref` found (`break` at line 87 of `types.py`), ignoring the sibling `nullable`. This produces non-nullable types when the override should apply.

---

### F-10 · `contentEncoding` / `contentMediaType` not handled
**Status**: [x] *(WP-9)*

`{"type": "string", "contentEncoding": "base64"}` should produce `bytes`. Currently produces `str`.

---

## Architecture & Design Issues

### A-01 · No config schema validation — unknown keys silently ignored
**Status**: [x] *(WP-7)*

`_parse_config` uses `data.get("key", default)` throughout. A misspelled key like `enums-as-literals` (kebab vs. snake) produces no error and the default value applies silently.

**Fix**: Validate the raw YAML dict against a known-key allowlist or use a `pydantic.BaseModel` / `dacite` for structured parsing.

---

### A-02 · Spec re-parsed multiple times per `generate` run
**Status**: [x] *(WP-7)*

`ServiceScaffolder.scaffold()` and `TestScaffolder.scaffold()` each call `SpecParser.load()` + `resolve_refs()` independently. A full `pyoas generate` (models + routers + services + tests) parses and resolves the spec 4+ times. `ParsedSpec` is correctly shared between `ModelGenerator` and `RouterGenerator` but not passed to scaffolders.

**Fix**: Accept an optional `parsed_spec: ParsedSpec | None` parameter in scaffolder `scaffold()` methods, same pattern as generators.

---

### A-03 · Private API (`_`-prefixed) exported across module boundaries
**Status**: [x] *(WP-10)*

`_GenericGroup`, `_collect_defs_schemas`, `_collect_shared_schemas`, `_build_models_context`, `_classify_model_imports`, `_extract_model_class_names`, `_has_security`, `_annotated_base_type` — all prefixed `_` (private by convention) but imported across module boundaries. This creates invisible coupling and makes refactoring risky.

**Fix**: Promoted all 11 cross-module symbols to public API (removed `_` prefix). Consolidated duplicate `_has_security` in `servicetestscaffold.py` — now imports from `generator.py`.

---

### A-04 · `ruff` in core runtime dependencies
**Status**: [x]

`ruff>=0.4` is in `[project.dependencies]`. It's used only for the optional format step, which already silently skips if ruff is not found (`FileNotFoundError` is caught). This unnecessarily forces a large dev tool onto all users.

**Fix**: Move to an optional extra or detect and use the `ruff` Python API when available.

---

### A-05 · Custom templates directory not validated at config load time
**Status**: [x] *(WP-7)*

`TemplatesConfig.models` / `TemplatesConfig.routers` paths are not checked for existence or required template files (`model.py.jinja2`, `router.py.jinja2`) until render time. A `TemplateNotFound` error emerges deep in the stack with no reference to the config entry.

**Fix**: At config load or before generation, verify the custom template directory exists and contains the required templates.

---

### A-06 · `format_output` invoked separately per output directory
**Status**: [x] *(WP-8)*

`ModelGenerator` and `RouterGenerator` each call `format_output(output_root)` independently. A single `ruff format src/generated/` covering both dirs would be faster and require only one subprocess launch.

---

### A-07 · `.pyoas_cache.json` has no file locking
**Status**: [x] *(WP-9)*

Concurrent `pyoas models` runs (e.g., in parallel CI jobs sharing a workspace) can corrupt the cache JSON by writing simultaneously. `GenerationCache.save()` uses `Path.write_text()` with no exclusive lock.

**Fix**: Use an advisory lock (e.g., `fcntl.flock` on POSIX, or a lock file pattern) around cache reads and writes.

---

### A-08 · `_find_referenced_schemas` uses object identity (`id()`) for cycle detection
**Status**: [x] *(WP-9)*

`_seen` tracks `id(obj)` values. While Python does not garbage-collect objects mid-traversal in normal use, relying on object identity for cycle detection is fragile — two different dict objects at different points in the spec with the same `id()` (due to GC and reuse) would be incorrectly treated as the same node.

**Fix**: Use a path-based visited set (tracking the JSON Pointer path to each node) rather than object identity.

---

### A-09 · No validation that `model_config.extra` values are legal Pydantic strings
**Status**: [x] *(WP-6)*

`Config` accepts any string for `extra` and `request_extra`. Pydantic v2 only accepts `"ignore"`, `"allow"`, `"forbid"`. An invalid value (e.g., `"FORBID"`) causes a Pydantic `ValueError` at model class creation time, with an error pointing at generated code rather than the config file.

**Fix**: Validate `extra` and `request_extra` at config parse time against the allowed set.

---

## Test Coverage Gaps

### T-01 · `pyoas watch` — no tests
**Status**: [x] *(WP-9)*
Watchdog integration is completely untested. A broken `watch` command would not be caught by CI.

---

### T-02 · `pyoas migrate` — no CLI tests
**Status**: [x] *(WP-7)*
`differ.py` and `migrate.py` are unit-tested in isolation. The `migrate` CLI command itself has no test.

---

### T-03 · `pyoas init` — no tests
**Status**: [x] *(WP-7)*
The config file generation command has no test coverage.

---

### T-04 · `pyoas fix` round-trip — no end-to-end test
**Status**: [x] *(WP-8)*
No test applies `fix_spec`, writes the result, then runs generation and verifies the output is valid Python.

---

### T-05 · Custom templates — no tests
**Status**: [x] *(WP-8)*
The `TemplatesConfig` override mechanism (user-provided Jinja2 templates) has no test.

---

### T-06 · Webhook generation — no tests
**Status**: [x] *(WP-8 — tests already present: `test_generate_webhooks_produces_models`, `test_generate_webhooks_router_output`)*
The `include_webhooks=True` path through `ModelGenerator` and `RouterGenerator` has no test.

---

### T-07 · `format.enabled: false` — not tested
**Status**: [x] *(WP-7)*
The format step is always enabled in the test suite. Disabling it is untested.

---

### T-08 · `on_generate_complete` hook — no test
**Status**: [x]
`test_on_generate_complete_called` exists at `tests/core/test_plugins.py:393`. Hook is called (B-12 confirmed).

---

### T-09 · `"2XX"` wildcard response codes — no fixture spec
**Status**: [x]
Added `tests/fixtures/wildcard_responses.yaml` and 8 new tests in `tests/fastapi/test_params.py`.

---

### T-10 · OAS 3.1 `const` / `patternProperties` — no type conversion tests
**Status**: [x] *(WP-7)*
`test_types.py` has no cases for `const`, `patternProperties`, `if`/`then`/`else`.

---

### T-11 · Multi-tag filter + `--clean` — no end-to-end test
**Status**: [x] *(WP-8)*
The selective-clean code path (`tag_filter + clean=True`) removes individual tag files rather than the whole directory. This path is not tested end-to-end.

---

### T-12 · Router generated file snapshots — not using syrupy
**Status**: [x] *(already present prior to WP-6)*
`test_router_generator.py` makes structural assertions but has no syrupy snapshot tests. Model generation uses snapshots; routers should too for regression protection.

---

### T-13 · Config validation errors — limited coverage
**Status**: [x] *(WP-6)*
No tests for: missing `spec` key, invalid `extra` values, unknown top-level keys, malformed `plugins` entries.

---

### T-14 · No behavioral smoke test for generated output
**Status**: [ ] *(QA_PLAN.md Phase 2)*
**Surfaced by**: Phase 1 audit

The existing test suite snapshot-compares rendered text but never imports, type-checks, or pytest-runs the generated tree. B-15 through B-22 (eight bugs in one week) were all syntactically valid output that snapshots accepted. The smoke test in `QA_PLAN.md` Phase 2 closes this gap.

**Coverage matrix** (from Phase 1 findings + the eight just-fixed bugs):

- Enum params in path, query, body — covers B-19, historical bare-name `Literal[…]` regressions
- `application/pdf` / `application/octet-stream` / `text/csv` responses — covers B-15, B-20
- `application/json` body whose root schema is `type: array` — covers B-16
- Body with required `list[Model]` field — covers B-17
- Paths sharing prefix: `/foo`, `/foo/{id}`, `/foo/{id}:action`, `/foo/{id}/sub` — covers B-18
- `model_config.request_extra: forbid` — covers B-21
- Operation with security → conftest `auth_context` fixture — covers B-22 (regression of B-06)
- Multi-tag spec referencing shared schemas — exercises `shared.py` classification

---

### A-10 · `format.enabled` only formats `models/` and `routers/` — not services / tests / dependencies
**Status**: [x] *(WP-11, 2026-05-22)*
**Files**: `core/cli.py:329-335`
**Surfaced by**: Phase 1 audit · 129 × I001 + 422 × E501 on generated `services/`, `tests/`, `dependencies/`

`_format_output(*format_paths)` is called only on `cfg.output.models` and `cfg.router_scaffold.output` (or `cfg.output.routers`). Service stubs, test scaffolds, dependency stubs, and the conftest are never formatted, leaving unsorted imports and long lines in the output. Downstream consumers paper over this with their own pre-commit `ruff format` (e.g. nova-data-api auto-reformatted 103 generated files on commit) — but that's a generator responsibility, not a consumer one.

**Fix**: relocated the format block to after all scaffolders complete and expanded the path list to include `cfg.services.output`, `cfg.tests.output`, `cfg.dependencies.output`, and `cfg.model_scaffold.output` when each is enabled. Paths that don't exist are filtered out so `ruff format` is not invoked with a non-existent directory (which would silently skip ALL formatting via the `CalledProcessError` swallow).

---

## Summary

| Category | Total | Open | Fixed (WP-5) | Fixed (WP-6) | Fixed (WP-7) | Fixed (WP-8) | Fixed (WP-9) | Fixed (WP-10) | Fixed (v0.7) | Fixed (WP-11) | Phase-1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Bugs | 26 | 1 | B-01, B-07, B-08, B-10, B-11, B-12 | B-02, B-05, B-06, B-09, B-13, B-14 | B-03 | B-04 | — | — | B-15, B-16, B-17, B-18, B-19, B-20, B-21, B-22 | B-23, B-24, B-25 | B-26 (won't fix) |
| Missing OAS features | 10 | 0 | F-01, F-06 | — | F-03 | F-02 | F-04, F-05, F-09, F-10 | F-07, F-08 | — | — | — |
| Architecture issues | 10 | 0 | A-04 | A-09 | A-01, A-02, A-05 | A-06 | A-07, A-08 | A-03 | — | A-10 | — |
| Test gaps | 14 | 1 | T-08, T-09, T-12 | T-13 | T-02, T-03, T-07, T-10 | T-04, T-05, T-06, T-11 | T-01 | — | — | — | T-14 (open) |
| **Total** | **60** | **2** | **12** | **8** | **9** | **6** | **7** | **4** | **8** | **4** | **2 open** |

### Priority

| Priority | Items |
|---|---|
| **High** | *(all resolved)* |
| **Medium** | *(all resolved)* |
| **Low** | *(all resolved)* |
