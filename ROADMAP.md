# pyoas Development Roadmap

_Analysis date: 2026-05-04_

## Project State

Architecture complete, production-quality implementation. 220 tests, all green (1.55s). Full pipeline implemented and snapshot-tested: OpenAPI parse → `$ref` resolve → tag extraction → schema analysis → Jinja2 render → ruff format.

---

## Known Issues

### `packages/` dead weight
`packages/specgen-{core,models,fastapi,claude}/src/specgen/` are completely empty stubs — remnants of an earlier namespace-package design. Code lives entirely under `src/pyoas/`. Either delete them (if single-package-with-extras is final) or properly implement as PEP 420 namespace packages with working `pyproject.toml` files.

### README/docs package table naming
The package table in `README.md` and `docs/index.md` lists `pyoas` in all three rows. The package names are not differentiated, which is confusing to new users.

### `diff` command format inconsistency
`diff` generates to a temp dir with `format.enabled = False`, then compares text against on-disk files that were generated with formatting enabled. Comparison is between unformatted and formatted output → false positives in CI. Fix: run `ruff format` on temp output before comparing, or normalize both sides before comparison.

---

## Proposed Next Pushes

Ordered by impact and natural sequencing.

### 1. Clean up `packages/` directory
**Effort:** Low | **Value:** Hygiene / contributor clarity

Delete the four empty `packages/specgen-*` directories or properly implement them. Leaving empty workspace members misleads contributors and may confuse `uv workspace` tooling.

---

### 2. CLI integration test suite
**Effort:** Medium | **Value:** High — zero CLI-layer coverage right now

The `init`, `validate`, `generate`, `diff`, and `scaffold` commands have no test coverage at the CLI layer. All testing happens at the generator API level. Add a test module using `typer.testing.CliRunner`.

```python
from typer.testing import CliRunner
from pyoas.core.cli import app

result = runner.invoke(app, ["validate", "--config", str(cfg_path)])
assert result.exit_code == 0
```

Scenarios to cover: wrong config path, invalid spec, `--tags` filtering, exit codes for `diff`, scaffold subcommands.

---

### 3. Fix `diff` format inconsistency
**Effort:** Small | **Value:** Correctness — affects CI users

See _Known Issues_ above. Options:
- Run `format_output()` on temp files before comparing
- Compare AST-normalized content instead of raw text

---

### 4. Webhook support / warning (OAS 3.1)
**Effort:** Medium | **Value:** OAS 3.1 completeness

OpenAPI 3.1 adds a `webhooks:` key alongside `paths:`. Currently silently ignored. At minimum emit a warning when a spec has webhooks. Ideally treat webhooks like paths and generate router stubs — they follow the same operation structure.

---

### 5. `pyoas --version` and colored output
**Effort:** Small | **Value:** DX

No `--version` flag exists. Trivial with typer:
```python
@app.callback()
def main(version: bool = typer.Option(None, "--version", is_eager=True, callback=...)):
    ...
```

Also: generation output (written file paths, schema warnings) has no color. Use `typer.style()` or rich markup to make output scannable.

---

### 6. Multiple 2xx response handling
**Effort:** Medium | **Value:** Correctness for real-world specs

`resolve_response_type()` picks the first 2xx response. Operations with multiple distinct response schemas (e.g., 200 + 201, or 200 + 204) should produce a `Union` type or fall back to `Response`. Affects correctness for specs like GitHub's API.

---

### 7. Real-world spec integration tests
**Effort:** Medium | **Value:** High edge-case discovery

Hand-crafted fixtures miss real-world patterns. Add a `tests/integration/` suite (marked `@pytest.mark.integration`, skipped by default) that runs against published specs: GitHub, Stripe, OpenAI, Kubernetes. These exercise discriminated unions, `x-` extensions, webhooks, large allOf chains, and hundreds of tags.

---

### 8. Multipart/form complex type resolution
**Effort:** Medium | **Value:** Completeness

`params.py:325,348` falls back to `bytes` + TODO comment when form fields can't be resolved individually. Handle inline-property schemas to emit typed `Form(...)` parameters. Extend `tests/fixtures/form_upload.yaml` to cover this path.

---

### 9. `deprecated` field/operation handling
**Effort:** Small–Medium | **Value:** DX for API consumers

`deprecated: true` on operations and schema properties is currently ignored. Options:
- Router stubs: `# deprecated` comment or `warnings.warn()` inside the stub
- Model fields: `Field(deprecated=True)` (Pydantic 2.9+) or `# deprecated` comment

---

### 10. First PyPI release (v0.1.0)
**Effort:** Medium | **Value:** Milestone — unlocks `uv add pyoas`

Publish workflow (`publish.yml`) exists with OIDC auth. Commitizen is in pre-commit config. Prerequisites before tagging:
- [ ] Fix README/docs package table naming
- [ ] Clean up `packages/` stubs
- [ ] Fix `diff` format inconsistency
- Tag `v0.1.0` → workflow publishes to PyPI

---

## Lower Priority / Backlog

| Item | Notes |
|---|---|
| Watch mode tests | Hard to test deterministically; mock `watchdog.Observer` instead of hitting the filesystem event loop |
| Shared spec parsing in `generate` | `ModelGenerator` and `RouterGenerator` each independently load/resolve the spec; a shared `ParsedSpec` value object would halve parse time for large specs |
| `x-enum-varnames` extension | Maps enum values to Python identifiers; common in NSwag/Swagger codegen output; small lift, high compat improvement |
| Plugin/hook system | Pre/post render hooks for custom type mappings or generated file post-processing; premature now, worth tracking |
| `services_pattern` test coverage | The `none \| repository \| domain` option is wired through to the skill template but has no dedicated test |
