# pyoas Development Roadmap

_Updated: 2026-05-05_

## Project State

Architecture complete, production-quality implementation. 282 tests, all green. Full pipeline implemented and snapshot-tested: OpenAPI parse → `$ref` resolve → tag extraction → schema analysis → Jinja2 render → ruff format. `DependencyScaffolder` complete (detects bearer/basic/apiKey/OAuth2 and writes typed auth stubs). `pyoas --version` flag added; all scaffolders return structured `ScaffoldResult`; `generate` prints a clean aligned summary table on completion.

---

## Confirmed Closed

| Item | Notes |
|---|---|
| `packages/` dead weight | Deleted — code lives entirely under `src/pyoas/` |
| `diff` format inconsistency | Fixed — `diff` deep-copies config and inherits `format.enabled`, both sides formatted identically |
| `deprecated=True` on router operations | Router decorator emits `deprecated=True` when spec marks operation deprecated |
| `pyoas --version` flag | Added via `@app.callback()` + `importlib.metadata.version("pyoas")` |
| Warning noise (`warnings.warn`) | Replaced with `typer.echo(..., err=True)` — no more Python stacktrace pointers |
| Colored output inconsistency | All scaffolders and generators now use `  wrote  {path}` (green) / `  skipped  {path}` (yellow) uniformly |
| `generate` summary table | `ScaffoldResult` dataclass aggregates counts across all scaffolders; `_print_summary()` prints an aligned two-column table at the end of `pyoas generate` |
| `deprecated` model field propagation | Schema properties marked `deprecated: true` now emit `Field(deprecated=True)` on Pydantic model fields; requires Pydantic ≥ 2.9 |
| `x-enum-varnames` support | `_render_enum_class()` reads `x-enum-varnames` (NSwag/Swagger Codegen extension) and uses those names instead of synthesizing `VALUE_1` etc.; falls back gracefully when absent or too short |
| OAS 3.1 webhook support | `WebhooksConfig`, `include_webhooks` in `extract_tags`, warning when disabled, `webhooks = APIRouter(...)` in router template, `pyoas init` starter config updated |

---

## Proposed Next Pushes

Ordered by impact and natural sequencing.

### 1. ~~`pyoas --version` and colored output~~ ✓ Done

`--version` flag, uniform colored output, and `generate` summary table all shipped.

---

### 2. ~~Complete CLI integration test suite~~ ✓ Done

`tests/core/test_cli.py` covers all commands and subcommands: `init`, `validate`, `models`, `fastapi`, `generate`, `diff`, and all `scaffold` subcommands (`services`, `tests`, `dependencies`, `skills`). Scenarios include `--tags` filtering, exit codes, missing extras (ImportError path), `diff` detecting new/modified/removed/missing files and service method drift. Coverage also improved across `core/tags`, `core/utils`, `fastapi/servicetestscaffold`, and `fastapi/deps_scaffold`. Overall line coverage: 84% → 89%.

---

### 3. ~~Deprecated model field propagation~~ ✓ Done

Schema properties marked `deprecated: true` now emit `Field(deprecated=True)` consistent with router operation handling. Pydantic lower bound bumped to ≥ 2.9.

---

### 4. ~~`x-enum-varnames` support~~ ✓ Done

`x-enum-varnames` is now read in `_render_enum_class()` and used (aligned by original enum index, NSwag convention) instead of synthesizing names. Falls back to synthesis for missing/short arrays. Integer enum `Priority` with `x-enum-varnames: [LOW, MEDIUM, HIGH]` now produces `LOW = 1` etc. instead of `VALUE_1 = 1`.

---

### 5. ~~Webhook support / warning (OAS 3.1)~~ ✓ Done

`WebhooksConfig(generate: bool = False)` added to config. `extract_tags` gains `include_webhooks` param; when True, iterates `spec["webhooks"]` and stamps `is_webhook: True` on each entry. Both `ModelGenerator` and `RouterGenerator` warn via `typer.echo(..., err=True)` when webhooks are present but `generate=False`. Router template emits a `webhooks = APIRouter(...)` variable and dispatches webhook ops via `@webhooks.method(...)`. `pyoas init` starter config includes `webhooks: generate: false`. New `tests/fixtures/webhooks_3.1.yaml` fixture; 14 new tests across tags, model generator, router generator, and CLI.

---

### 6. Multiple 2xx response handling

**Effort:** Medium | **Value:** Correctness for real-world specs

`resolve_response_type()` picks the first 2xx response. Operations with multiple distinct 2xx schemas (200 + 201, 200 + 204) should produce a `Union` type or fall back to `fastapi.Response`. Affects correctness for high-coverage specs like GitHub's and Stripe's.

---

### 7. `pyoas doctor` diagnostic command

**Effort:** Small–Medium | **Value:** DX — prevents confusing generation failures

A pre-flight check command that statically reports common problems before `generate` fails silently or produces garbage:

- Operations missing `operationId` (breaks synthesized names for inline schemas and test methods)
- Schemas with no `type` and no `$ref` (silently become `Any`)
- Tag names that normalize to the same `dirname` (silently collapse files)
- `services.import_path` pointing to a non-existent module
- `components.schemas` entries with unresolvable `$ref` chains
- Duplicate `operationId` values

Zero runtime cost; runs entirely against the parsed spec before any generation.

---

### 8. `pyoas drift` standalone command

**Effort:** Small | **Value:** CI use case — detect service drift without writing files

Drift detection is currently embedded in `ServiceScaffolder.scaffold()` and only surfaces when you run `scaffold`. A dedicated `pyoas drift` command reports orphaned service methods and signature changes (operations that no longer match the spec) *without* writing anything. Useful as a CI gate: "did someone update the spec without updating the service?"

Implementation: extract the drift-detection logic from `ServiceScaffolder` into a pure function; `pyoas drift` calls it and exits 1 if drift is found.

---

### 9. `allOf` inheritance in model generation

**Effort:** Medium | **Value:** Cleaner generated code for polymorphic specs

`allOf: [{$ref: "#/components/schemas/Animal"}, {properties: ...}]` is currently flattened into a single model with all merged properties. Pydantic v2 supports true class inheritance — generating `class Dog(Animal): ...` produces cleaner, more idiomatic code that preserves the spec's intent and reduces repetition. Detection rule: `allOf` with exactly one `$ref` and additional `properties` → inheritance; `allOf` with multiple `$ref` → flatten (Python has no clean n-way Pydantic inheritance).

---

### 10. Real-world spec integration tests

**Effort:** Medium | **Value:** High edge-case discovery

Hand-crafted fixtures miss real-world patterns. Add `tests/integration/` (marked `@pytest.mark.integration`, skipped by default in CI unless `--run-integration` is passed) running against published specs: GitHub REST API, Stripe, OpenAI, Kubernetes. These surface discriminated union edge cases, `x-` extensions, large `allOf` chains, hundreds of tags, and implicit webhook patterns.

Tie to the shared `ParsedSpec` refactor (see Backlog) before running against Kubernetes — parsing twice per `generate` on a 10k-line spec is slow.

---

### 11. Multipart/form complex type resolution

**Effort:** Medium | **Value:** Completeness

`params.py:325,348` falls back to `Annotated[bytes, Body()]` + TODO comment when form fields can't be resolved to individual `Form(...)` parameters. Handle inline-property schemas in form content to emit properly typed multipart parameters. Extend `tests/fixtures/form_upload.yaml` with a complex inline schema to cover this path.

---

### 12. First PyPI release (v0.1.0)

**Effort:** Medium | **Value:** Milestone — unlocks `uv add pyoas`

`publish.yml` exists with OIDC auth. Commitizen is in pre-commit config. Prerequisites before tagging:

- [ ] `pyoas --version` reads from package metadata — ✓ Done
- [ ] Tag `v0.1.0` → workflow publishes to PyPI

---

## Medium-Term Feature Directions

### Typed client generation (`pyoas[client]`)

Generate an async `httpx`-based client with one typed method per operation, matching the same parameter signatures as the generated service stubs. The parameter and response-type machinery already exists in `params.py` and `generator.py`; the missing piece is a client template and a `ClientGenerator` orchestrator. Natural `pyoas[client]` extra.

### `pyoas doctor` → `pyoas mock` (mock server)

Generate a runnable FastAPI app that serves spec `examples` (or factory-generated data) instead of calling real service implementations. The endpoint structure is already generated; the missing piece is an example extractor and a response factory using polyfactory. High value for frontend/consumer teams doing API-first development. Natural `pyoas[mock]` extra.

### Response validation middleware (dev-mode)

A `pyoas scaffold middleware` command that generates FastAPI middleware validating response payloads against the spec schema at runtime (dev/test only). Closes the loop between generated router types and service implementations — catches fields returned by a service that aren't in the spec before they reach the client.

---

## Backlog

| Item | Notes |
|---|---|
| Shared `ParsedSpec` in `generate` | `ModelGenerator` and `RouterGenerator` each independently load/resolve the spec; a shared `ParsedSpec(raw, resolved)` value object would halve parse time for large specs — prerequisite before real-world integration tests |
| `services_pattern` test coverage | `none \| repository \| domain` wired to the Claude skill template but has no dedicated test |
| Watch mode tests | Hard to test deterministically; mock `watchdog.Observer` instead of hitting the filesystem event loop |
| OAS 3.1 `anyOf` nullable edge case | Verify `anyOf: [{$ref: X}, {type: "null"}]` is correctly rendered as `Optional[X]` across all nested/resolved cases; add a 3.1-specific nullable fixture |
| `py.typed` marker | Add a `py.typed` file to `src/pyoas/` to declare the package as typed for downstream consumers |
| Plugin/hook system | Pre/post render hooks for custom type mappings or generated file post-processing; premature now, worth tracking |
