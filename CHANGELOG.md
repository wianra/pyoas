## v0.5.0 (2026-05-18)

### Feat

- **scaffold**: add append-only router and model scaffolding

## v0.4.2 (2026-05-11)

### Fix

- **templates**: fix import ordering and isort stability

## v0.4.1 (2026-05-11)

### Fix

- **docs**: update README with new features and config options
- **docs**: add plugin example README
- **tests**: add migrate URL loading coverage
- **tests**: add CLI coverage for doctor and fix commands
- **core**: export new modules from pyoas.core.__init__

## v0.4.0 (2026-05-10)

### Feat

- **core**: add plugin architecture with lifecycle hooks (T4-D)
- **core**: add pyoas migrate command with breaking-change detection (T4-C)
- **core**: add Jinja2 filter/global extension point via config (T4-A)

### Fix

- add parameter_shadowing and missing_success_response doctor checks

## v0.3.0 (2026-05-07)

### Feat

- **example**: add petstore example project with CI sync check
- add pyoas fix command to auto-correct common spec issues

## v0.2.0 (2026-05-07)

### Feat

- **fastapi**: parametrize test fixtures with auth_context instead of hardcoding AuthContext()
- **fastapi**: skip unchanged router tags via hash cache
- **models**: skip unchanged tags via hash cache
- **core**: add GenerationCache and tag/config hash helpers
- **cli**: add progress output flags and JSON diagnostic output
- **models**: add OAS 3.1 \$defs schema support
- **fastapi**: emit security scope annotations in router stubs and auth scaffold
- **models**: add unique_items_as_set config flag with list deduplication validator
- **models**: support prefixItems with variable-length tail (OAS 3.1 tuple)

### Fix

- **models**: discriminator mapping emits Pydantic Tag/Discriminator
- **models**: allOf with single $ref returns ref name not union
- fix wrong test mock import
- **fastapi**: map text/plain and octet-stream request bodies to correct Python types
- **models**: add circular self-referencing schema test and has_circular context flag

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
