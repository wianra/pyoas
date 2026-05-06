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

- [ ] Resolve `$defs` references
- [ ] Collect `$defs` schemas in classifier
- [ ] Render as inner or module-level classes
- [ ] Fixture `tests/fixtures/inline_defs_3.1.yaml` + snapshot

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

- [ ] Config option
- [ ] Generator wiring
- [ ] `__init__.py` re-export
- [ ] CLI sub-command
- [ ] Tests with `tests/fixtures/webhooks_3.1.yaml`

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

- [ ] Add `--quiet` / `--verbose` flags to generation commands
- [ ] Progress reporter utility in `core/utils.py`
- [ ] Thread through model generator
- [ ] Thread through router generator

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

- [ ] Add `--json` flag
- [ ] Serialize doctor results
- [ ] Serialize validate results
- [ ] Test JSON output format

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

- [ ] Populate v0.1.0 entries
- [ ] Populate v0.1.1 entries
- [ ] Verify `cz bump` generates v0.2.0 entry correctly on next release

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

- [ ] Write petstore spec
- [ ] Write pyoas.yaml
- [ ] Generate and commit output
- [ ] Write example README
- [ ] Add CI step to keep it in sync

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

- [ ] `core/cache.py` — hash + read/write
- [ ] Model generator: check/update cache
- [ ] Router generator: check/update cache
- [ ] `--clean` bypasses cache
- [ ] `.gitignore` entry
- [ ] Tests

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

- [ ] `core/fixer.py`
- [ ] `pyoas fix` CLI command
- [ ] `--dry-run` flag
- [ ] Tests

---

## Tier 4 — Differentiation (future major, 0.4+)

These are larger features that require architecture decisions. Listed here for
awareness and to guide design choices in Tier 1–3 work.

---

### T4-A · Jinja2 filter extension point

Allow users to register custom Jinja2 filters via `pyoas.yaml`:

```yaml
extensions:
  filters: myapp.pyoas_extensions:filters  # dict of name → callable
```

The `Renderer` class (`core/renderer/__init__.py`) would load the module,
call the factory, and inject filters into the Jinja2 environment. This enables
custom format mappers (e.g. `format: uri` → `AnyUrl`) without forking templates.

---

### T4-B · SQLAlchemy 2.0 model output target

New optional extra `pyoas[sqlalchemy]`. Adds a `SQLAlchemyGenerator` that
produces `DeclarativeBase` models alongside or instead of Pydantic models.

Key design questions:
- How to handle schemas with no primary key in the spec?
- Relationship inference from `$ref` arrays (one-to-many)?
- Column type mapping from OpenAPI types?

---

### T4-C · `pyoas migrate` command

Given two spec files (old + new), produce a structured diff:
- New operations
- Removed operations
- Operations with changed request/response schemas
- Breaking changes (removed required fields, narrowed types)
- Non-breaking changes (new optional fields, widened types)

Output as human-readable markdown or `--json`. Use-case: PR reviews for
API changes.

---

### T4-D · Plugin architecture

Define a `pyoas.Plugin` protocol that third-party packages can implement:

```python
class Plugin(Protocol):
    name: str
    def on_spec_loaded(self, spec: ParsedSpec) -> ParsedSpec: ...
    def on_tag_generated(self, tag: str, files: list[GeneratedFile]) -> list[GeneratedFile]: ...
    def extra_templates(self) -> dict[str, str]: ...  # name → template source
```

Plugins registered via `pyproject.toml` entry points under
`pyoas.plugins`. Enables SQLAlchemy, TypeScript, and other output
targets as independent packages.

---

## Cross-cutting concerns

These apply across all tiers and should be kept in mind during implementation.

| Concern | Guidance |
|---|---|
| Snapshot tests | Run `uv run pytest --snapshot-update` after any template change |
| Conventional commits | Use `fix:` for T1, `feat:` for T2–T3, `feat!:` for T4 breaking |
| Integration tests | Run `uv run pytest --run-integration` before any release |
| Config backwards compat | New config keys must have defaults; never rename existing keys |
| Template override contract | Any variable added to a template context must be documented; user overrides rely on the contract |
| Type annotations | All new functions must be fully typed; `uv run mypy src/` must pass |
| Ruff | `uv run ruff check src/` must pass; line length 88, select E F I UP |

---

## Release cadence target

| Version | Contents |
|---|---|
| `0.1.2` | T1-A, T1-C (quick correctness fixes) |
| `0.1.3` | T1-B, T1-D (allOf + discriminator) |
| `0.2.0` | T2-A through T2-E + T3-C (CHANGELOG) |
| `0.3.0` | T3-A through T3-F |
| `0.4.0` | T4-A, T4-B (first power features) |
