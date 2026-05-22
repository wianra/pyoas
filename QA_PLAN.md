# Generator behavioral QA plan

> Goal: close the gap that let 8 generator bugs ship this week. All of them
> shared one root cause — pyoas snapshots the rendered text but never imports,
> type-checks, or pytest-runs the output. This plan combines a one-shot audit
> (to scope the iceberg) with a permanent smoke test in CI (to stop the bleed).

Status legend: `[ ]` open · `[~]` in progress · `[x]` done · `[-]` won't do

---

## Phase 1 — Audit the current state (one-shot)

Establish a ground-truth list of every latent bug in today's generated output
before designing the permanent smoke test, so Phase 2's fixture is grounded
in real failure modes (not guesses).

**Target spec**: `/Users/rawi/Documents/swch/nova-data-api/specs/1.0.0/openapi.yaml`
(the richest real-world spec we have — 6,937 lines, hits every feature).

**Procedure**:

- [x] Regenerate fresh into `/tmp/pyoas_audit/` with `services.overwrite: true`, `tests.overwrite: true`, `router_scaffold.overwrite: true` — keep dependencies + skills off the critical path
- [x] `python -m compileall -q /tmp/pyoas_audit` — collect any `SyntaxError` *(clean — 0 errors)*
- [x] `ruff check --select=E,F,I,UP,W /tmp/pyoas_audit` — focus on `F821` (undefined), `F811` (redef), `E402` (mid-file imports), `F401` (unused) *(22 × F401, 1 × UP046 — no F821/F811/E402, the recently-fixed classes)*
- [x] Per-module import smoke: `python -c "import …"` over every generated `.py` — collect `ImportError` / `NameError` *(clean — 162/162 import, after fixing path isolation in `_import_smoke.py`)*
- [x] `mypy --strict /tmp/pyoas_audit` — collect type errors (filter false positives like missing third-party stubs) *(1 real error — `Field(default=None)` on `list[T]`)*
- [x] `pytest /tmp/pyoas_audit/tests/generated/` with a `MagicMock()` service in conftest — collect 422s, 500s, `RecursionError`, etc. *(701 passed, 552 skipped, 0 failed, 0 warnings with `-W error`)*
- [x] For each finding: symptom → file → root cause → owning scaffolder
- [x] Append findings to `FINDINGS.md` (B-15–B-26, A-10, T-14)

**Phase 1 result**: 4 new open bugs (B-23 F401 in re-export-only model files · B-24 F401 unused `field` in auth scaffold · B-25 `Field(default=None)` on `list[T]` · B-26 PEP 695 modernization), plus A-10 (format scope) and T-14 (no behavioral smoke test, addressed by Phase 2). All eight previously-discovered bugs (B-15–B-22) confirmed fixed end-to-end — including the historical 422s on `getDriverSubscriptionCancellationInfo` and the `RecursionError`s on PDF/CSV endpoints.

**Audit workspace**: `/tmp/pyoas_audit/` (isolated `.venv` + `pyproject.toml`, `_import_smoke.py`). Safe to delete; recreate from `QA_PLAN.md` if needed.

---

## Phase 2 — Permanent smoke test in pyoas CI

A pytest integration test that runs Phase 1's checks against a curated fixture
spec on every CI run. Fails the build on regression.

**Smoke spec coverage** (start from these, extend with anything Phase 1 surfaces):

- Enum params in path, query, and body-field positions — covers the missing `Literal` import family
- `application/pdf`, `application/octet-stream`, `text/csv` responses returning `Response` — covers `-> Response` mock recursion and missing `from fastapi import Response`
- `application/json` request body whose root schema is `type: array` — covers the `{}` vs `[]` body stub bug
- Body with required `list[Model]` field — covers `_default_value_for_field` for arrays/objects
- Paths sharing prefix: `/foo`, `/foo/{id}`, `/foo/{id}:action`, `/foo/{id}/sub` — covers route ordering
- Operations across multiple tags referencing the same schema — exercises `shared.py` classification
- `model_config.request_extra: forbid` — exercises Write split variants in service stub imports
- Operations with security — exercises auth_context conftest fixture

**Integration test** (`tests/integration/test_generated_output_smoke.py`):

- [x] Session-scoped fixture generates the smoke spec into a `tmp_path`
- [x] Check 1: `compileall` — every `.py` compiles
- [x] Check 2: `ruff check --select=E,F --ignore=E501` — zero violations (E501 is ignored in the project's own ruff config; `I/UP/W` are out of scope here)
- [x] Check 3: every generated module imports cleanly (walk the tree, `importlib.import_module` in a subprocess)
- [x] Check 4: `pytest` the generated test tree in a subprocess against a `MagicMock` service — zero failures, no `RecursionError`
- [-] Check 5 (optional, gated by config flag): `mypy --strict` on the output — *deferred* (Phase 1 surfaced only B-25, already fixed; reopen if a new strict-only bug class emerges)

**Build-out order**:

- [x] Write `tests/fixtures/smoke_spec.yaml` from the coverage matrix
- [x] Implement the four checks
- [x] Wire into default pytest selection (so `uv run pytest` runs it) — required loosening the integration conftest skip rule to match only the explicit `@pytest.mark.integration` marker, not the directory keyword
- [x] Document the contract in `CLAUDE.md` so future agents know to extend the smoke spec when adding scaffolder features

---

## Phase 3 — Format parity (follow-up, optional)

Phase 1 will likely confirm that `pyoas` only runs ruff on `models/` and
`routers/`, not on `services/` / `tests/` / `dependencies/` / `conftest.py`.
Downstream pre-commit hooks paper over this, but it's a generator
responsibility. If the cost is low, extend `cli.py:format_paths` to cover
all generated trees behind the existing `format.enabled` flag.

- [ ] Confirm scope from Phase 1 findings
- [ ] Extend `_format_output(…)` call site to include services / tests / deps

---

## Risks & non-goals

- **Runtime cost**: subprocess `pytest` + `mypy` could add 10–20s to CI. Mitigate with a session fixture so generation happens once. If still too slow, gate `mypy` behind an opt-in marker.
- **Version coupling**: ruff/mypy versions move; pin in `pyproject.toml` so the smoke test is reproducible.
- **Generated-code idioms**: some ruff rules (e.g. `I001` import sort) belong to the formatter, not the linter — gate on `E,F` only.
- **Non-goal**: chasing false positives in the user's own service implementation. The smoke test only asserts the *scaffolded* output is valid; user-edited methods are out of scope.

---

## Status

- Phase 1 — **complete** (2026-05-22) — 4 new open bugs, 8 fixes confirmed green; see `FINDINGS.md` B-15–B-26
- Phase 2 — **complete** (2026-05-22, WP-12) — smoke test wired into default pytest selection; see `tests/integration/test_generated_output_smoke.py` and `tests/fixtures/smoke_spec.yaml`. Closes T-14.
- Phase 3 — already complete (A-10 fixed in WP-11)
