## v0.1.1 (2026-05-06)

### Added

- `feat(models)`: Support OAS 3.1 `$defs` schema blocks; tag-local and shared `$defs`
  are classified and emitted as named module-level classes with correct cross-file imports.
- `feat(models)`: Add `fields.unique_items_as_set` config flag; when `false`, `uniqueItems`
  arrays emit `list[T]` with a deduplication validator to avoid Pydantic v2 set JSON errors.
- `feat(models)`: Support OAS 3.1 tuple schemas with `prefixItems + items`; emits
  `tuple[T1, T2, *tuple[R, ...]]` for variable-length tails.
- `feat(fastapi)`: Emit required OAuth2 scope annotations as comments above secured
  endpoints; auth stub collects all unique scopes.
- `feat(cli)`: Add `--quiet` / `--verbose` flags to `models`, `fastapi`, and `generate`;
  add `--json` flag to `doctor` and `validate` for structured CI output.

### Fixed

- `fix(models)`: `allOf` with a single `$ref` entry now returns the referenced schema name
  instead of a union type.
- `fix(models)`: Discriminator mappings now emit Pydantic `Tag` / `Annotated`
  `Discriminator` constructs correctly.
- `fix(models)`: Self-referencing schemas emit `from __future__ import annotations` to
  prevent `NameError` at import time.
- `fix(fastapi)`: `text/plain` and `application/octet-stream` request bodies are now
  mapped to `str` and `bytes` respectively.

## v0.1.0 (2026-05-04)

### Added

- Initial release: generate Pydantic v2 models and FastAPI router stubs from OpenAPI
  3.0 and 3.1 specs, organised by operation tag.
- `drift` and `doctor` CLI commands for detecting service method drift and running
  pre-flight spec diagnostics.
- `allOf` model inheritance: schemas with `allOf` render as Pydantic class hierarchies.
- Multipart form-data and file upload support in router parameter generation.
- Multiple 2xx response codes per endpoint; primary success type used as response model.
- `deprecated` flag propagation from OpenAPI operations and schema fields to models.
- Integration test suite against real-world specs (GitHub, Kubernetes, OpenAI, Stripe).
