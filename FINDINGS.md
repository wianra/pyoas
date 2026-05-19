# pyoas Codebase Findings

> Analysis date: 2026-05-19 · Version: 0.5.1
>
> Status legend: `[ ]` open · `[x]` fixed · `[-]` won't fix · `[~]` in progress (WP-6)

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
**Status**: [~] *(WP-6)*

`_build_models_context` calls `has_circular_refs(...)` and passes `has_circular` in the Jinja2 context, but `model.py.jinja2` never references it. Dead computation on every generation pass.

**Fix**: Either use `has_circular` in the template (e.g., emit `model_rebuild()` for circular schemas), or remove the computation.

---

### B-03 · `find_split_schema_names` misses inherited `readOnly`/`writeOnly`
**Severity**: Medium
**File**: `core/analysis.py:237-249`
**Status**: [ ]

Only inspects `schema.get("properties")` at the top level. If a schema uses `allOf` inheritance and the **parent** carries `readOnly`/`writeOnly` properties, the child is never added to `split_schema_names`. The router generator then does not substitute the `Write` variant for request bodies of those child schemas.

**Fix**: Recurse into `allOf` sub-schemas (following `$ref` entries) when checking for read/write-only properties.

---

### B-04 · Service scaffolder method insertion targets wrong position via string search
**Severity**: Low
**File**: `fastapi/scaffold.py:216-221`
**Status**: [ ]

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
**Status**: [~] *(WP-6)*

`_expected_sig_str` iterates `op["parameters"]` in spec order; `_service_sig_from_ast` iterates `func.args.kwonlyargs` in file order. Reordering keyword-only parameters in a service method (a harmless refactor) incorrectly triggers drift detection.

**Fix**: Sort both sides by parameter name before comparing.

---

### B-06 · Auth imports appended to bottom of `conftest.py` instead of top
**Severity**: Medium
**File**: `fastapi/testscaffold.py:569-589`
**Status**: [~] *(WP-6)*

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
**Status**: [~] *(WP-6)*

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
**Status**: [~] *(WP-6)*

```python
function_name = to_snake_case(re.sub(r"[^a-zA-Z0-9_]", "_", operation_id))
```

OperationIds like `"list-pets--v2"` produce `"list_pets__v2"` (double underscore). `to_snake_case` doesn't collapse consecutive underscores.

**Fix**: Add `re.sub(r"_+", "_", ...).strip("_")` after the substitution, consistent with the pattern already used in `generate_function_name`.

---

### B-14 · Stale docstring in router generator
**Severity**: Low
**File**: `fastapi/generator.py:4`
**Status**: [~] *(WP-6)*

```
"""RouterGenerator — orchestrates FastAPI router generation from an OpenAPI spec.

Milestone 3 will fill in the complete implementation.
"""
```

Leftover scaffolding text from a development milestone. Implementation is complete.

**Fix**: Remove the stale sentence.

---

## Missing OpenAPI Feature Support

### F-01 · `"2XX"` / `"2xx"` wildcard response codes
**Status**: [x]
See B-01. Affects response type resolution, status code selection, and doctor diagnostics.

---

### F-02 · Security scheme type not used in auth dependency generation
**Status**: [ ]

`components/securitySchemes` is completely ignored. The generated `AuthContext` / `get_auth_context` stubs are always generic with no reference to the actual security type (Bearer JWT, OAuth2, API key, HTTP basic). OAuth2 scopes are emitted as comments only.

**Improvement**: Read `securitySchemes` to generate typed stubs (e.g., Bearer extraction vs. API key header extraction).

---

### F-03 · OAS 3.1 `const` keyword not handled
**Status**: [ ]

`{"const": "active"}` should produce `Literal["active"]`. Currently produces `Any` (no `type`, no `enum`, no composition keyword). The ambiguous-schema doctor check fires, but generation silently falls back.

**Fix**: In `_base_type`, detect `"const"` before the `match raw_type` block and return `Literal[repr(const_value)]`.

---

### F-04 · `patternProperties` not handled
**Status**: [ ]

Valid in OAS 3.1 (JSON Schema). Not handled; silently ignored. Should produce `dict[str, T]` for typed pattern-based maps, or at minimum `dict[str, Any]` with a warning.

---

### F-05 · `if`/`then`/`else` conditional schemas not handled
**Status**: [ ]

Valid in OAS 3.1. Not handled; silently produces `Any`. Consider mapping to the `then` branch as a best-effort, with a warning.

---

### F-06 · `"default"` response code treated as missing
**Status**: [x]

`resolve_response_type` only scans `re.match(r"^2\d{2}$", code)` codes. Specs that define only a `"default"` response (no explicit `"200"` etc.) get `response_type = None`. The doctor flags these as "missing_success_response" — a false positive for specs using `"default"` as their success code.

**Fix**: If no `2xx` codes are found, fall back to the `"default"` response entry.

---

### F-07 · OAS Callbacks not processed
**Status**: [ ]
`paths[…][method].callbacks` is not processed. Generated routers silently omit them.

---

### F-08 · `allOf` with multiple `$ref`s emits union instead of composed model
**Status**: [ ]

`allOf: [$ref/A, $ref/B]` is rendered as `A | B`. OAS semantics are "implements all of A and B" (mixin). A composed class (`class C(A, B): ...`) would be more accurate. Currently only single-`$ref` `allOf` is treated as inheritance.

---

### F-09 · OAS 3.1 `$ref` + sibling keywords (nullable override) ignored
**Status**: [ ]

In OAS 3.1, `{$ref: "…", nullable: true}` is valid. `schema_to_python_type` returns early on any top-level `$ref` found (`break` at line 87 of `types.py`), ignoring the sibling `nullable`. This produces non-nullable types when the override should apply.

---

### F-10 · `contentEncoding` / `contentMediaType` not handled
**Status**: [ ]

`{"type": "string", "contentEncoding": "base64"}` should produce `bytes`. Currently produces `str`.

---

## Architecture & Design Issues

### A-01 · No config schema validation — unknown keys silently ignored
**Status**: [ ]

`_parse_config` uses `data.get("key", default)` throughout. A misspelled key like `enums-as-literals` (kebab vs. snake) produces no error and the default value applies silently.

**Fix**: Validate the raw YAML dict against a known-key allowlist or use a `pydantic.BaseModel` / `dacite` for structured parsing.

---

### A-02 · Spec re-parsed multiple times per `generate` run
**Status**: [ ]

`ServiceScaffolder.scaffold()` and `TestScaffolder.scaffold()` each call `SpecParser.load()` + `resolve_refs()` independently. A full `pyoas generate` (models + routers + services + tests) parses and resolves the spec 4+ times. `ParsedSpec` is correctly shared between `ModelGenerator` and `RouterGenerator` but not passed to scaffolders.

**Fix**: Accept an optional `parsed_spec: ParsedSpec | None` parameter in scaffolder `scaffold()` methods, same pattern as generators.

---

### A-03 · Private API (`_`-prefixed) exported across module boundaries
**Status**: [ ]

`_GenericGroup`, `_collect_defs_schemas`, `_collect_shared_schemas`, `_build_models_context`, `_classify_model_imports`, `_extract_model_class_names`, `_has_security`, `_annotated_base_type` — all prefixed `_` (private by convention) but imported across module boundaries. This creates invisible coupling and makes refactoring risky.

**Fix**: Promote these to public API (remove `_` prefix) or move them to a shared internal module with explicit `__all__`.

---

### A-04 · `ruff` in core runtime dependencies
**Status**: [x]

`ruff>=0.4` is in `[project.dependencies]`. It's used only for the optional format step, which already silently skips if ruff is not found (`FileNotFoundError` is caught). This unnecessarily forces a large dev tool onto all users.

**Fix**: Move to an optional extra or detect and use the `ruff` Python API when available.

---

### A-05 · Custom templates directory not validated at config load time
**Status**: [ ]

`TemplatesConfig.models` / `TemplatesConfig.routers` paths are not checked for existence or required template files (`model.py.jinja2`, `router.py.jinja2`) until render time. A `TemplateNotFound` error emerges deep in the stack with no reference to the config entry.

**Fix**: At config load or before generation, verify the custom template directory exists and contains the required templates.

---

### A-06 · `format_output` invoked separately per output directory
**Status**: [ ]

`ModelGenerator` and `RouterGenerator` each call `format_output(output_root)` independently. A single `ruff format src/generated/` covering both dirs would be faster and require only one subprocess launch.

---

### A-07 · `.pyoas_cache.json` has no file locking
**Status**: [ ]

Concurrent `pyoas models` runs (e.g., in parallel CI jobs sharing a workspace) can corrupt the cache JSON by writing simultaneously. `GenerationCache.save()` uses `Path.write_text()` with no exclusive lock.

**Fix**: Use an advisory lock (e.g., `fcntl.flock` on POSIX, or a lock file pattern) around cache reads and writes.

---

### A-08 · `_find_referenced_schemas` uses object identity (`id()`) for cycle detection
**Status**: [ ]

`_seen` tracks `id(obj)` values. While Python does not garbage-collect objects mid-traversal in normal use, relying on object identity for cycle detection is fragile — two different dict objects at different points in the spec with the same `id()` (due to GC and reuse) would be incorrectly treated as the same node.

**Fix**: Use a path-based visited set (tracking the JSON Pointer path to each node) rather than object identity.

---

### A-09 · No validation that `model_config.extra` values are legal Pydantic strings
**Status**: [~] *(WP-6)*

`Config` accepts any string for `extra` and `request_extra`. Pydantic v2 only accepts `"ignore"`, `"allow"`, `"forbid"`. An invalid value (e.g., `"FORBID"`) causes a Pydantic `ValueError` at model class creation time, with an error pointing at generated code rather than the config file.

**Fix**: Validate `extra` and `request_extra` at config parse time against the allowed set.

---

## Test Coverage Gaps

### T-01 · `pyoas watch` — no tests
**Status**: [ ]
Watchdog integration is completely untested. A broken `watch` command would not be caught by CI.

---

### T-02 · `pyoas migrate` — no CLI tests
**Status**: [ ]
`differ.py` and `migrate.py` are unit-tested in isolation. The `migrate` CLI command itself has no test.

---

### T-03 · `pyoas init` — no tests
**Status**: [ ]
The config file generation command has no test coverage.

---

### T-04 · `pyoas fix` round-trip — no end-to-end test
**Status**: [ ]
No test applies `fix_spec`, writes the result, then runs generation and verifies the output is valid Python.

---

### T-05 · Custom templates — no tests
**Status**: [ ]
The `TemplatesConfig` override mechanism (user-provided Jinja2 templates) has no test.

---

### T-06 · Webhook generation — no tests
**Status**: [ ]
The `include_webhooks=True` path through `ModelGenerator` and `RouterGenerator` has no test.

---

### T-07 · `format.enabled: false` — not tested
**Status**: [ ]
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
**Status**: [ ]
`test_types.py` has no cases for `const`, `patternProperties`, `if`/`then`/`else`.

---

### T-11 · Multi-tag filter + `--clean` — no end-to-end test
**Status**: [ ]
The selective-clean code path (`tag_filter + clean=True`) removes individual tag files rather than the whole directory. This path is not tested end-to-end.

---

### T-12 · Router generated file snapshots — not using syrupy
**Status**: [~] *(WP-6)*
`test_router_generator.py` makes structural assertions but has no syrupy snapshot tests. Model generation uses snapshots; routers should too for regression protection.

---

### T-13 · Config validation errors — limited coverage
**Status**: [~] *(WP-6)*
No tests for: missing `spec` key, invalid `extra` values, unknown top-level keys, malformed `plugins` entries.

---

## Summary

| Category | Total | Open | Fixed (WP-5) | In Progress (WP-6) |
|---|---|---|---|---|
| Bugs | 14 | 3 | B-01, B-07, B-08, B-10, B-11, B-12 | B-02, B-05, B-06, B-09, B-13, B-14 |
| Missing OAS features | 10 | 8 | F-01, F-06 | — |
| Architecture issues | 9 | 7 | A-04 | A-09 |
| Test gaps | 13 | 9 | T-08, T-09 | T-12, T-13 |
| **Total** | **46** | **27** | **11** | **9** |

### Priority

| Priority | Items |
|---|---|
| **High** | *(all resolved)* |
| **Medium** | B-03, B-06 *(WP-6)*, A-01, A-02, F-02 |
| **Low (WP-6)** | B-02, B-05, B-09, B-13, B-14, A-09, T-12, T-13 |
| **Low (deferred)** | B-04, F-03–F-05, F-07–F-10, A-03, A-05–A-08, T-01–T-07, T-10, T-11 |
