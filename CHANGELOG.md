## v0.7.2 (2026-05-22)

### Fix

- **generator**: clean up generated-output quality (B-23/24/25, A-10)
- **testscaffold**: hoist auth_context fixture imports to top of conftest
- **scaffold**: emit missing Literal/Response/Write imports in service stubs
- **router**: sort routes by per-segment specificity so {param}:literal precedes {param}
- **testscaffold**: keep AsyncMock out of FastAPI serializer for Response, list bodies, and array fields

## v0.7.1 (2026-05-21)

### Fix

- **testscaffold**: skip Response sentinel; route generics to shared

## v0.7.0 (2026-05-21)

### Feat

- **scaffold**: delegate to services, skip duplicate routers, fix docstring indent

## v0.6.0 (2026-05-20)

### Feat

- **tags**: value-aware skip_extensions with full scaffold coverage

## v0.5.2 (2026-05-19)

### Fix

- **drift**: normalise quote style before signature comparison
- **wp10**: F-07 F-08 A-03
- **wp9**: F-04 F-05 F-09 F-10 A-07 A-08 T-01
- **wp8**: B-04 F-02 A-06 T-04 T-05 T-06 T-11
- **wp7**: B-03 F-03 A-01 A-02 A-05 T-02 T-03 T-07 T-10
- **wp6**: B-02 B-05 B-06 B-09 B-13 B-14 A-09 T-13
- **models**: whole-word shared schema name matching; cache includes generic group fingerprint
- **fastapi**: handle 2XX wildcard + "default" response codes; fix bytes response_model
- **deps**: move polyfactory to testing extra, ruff to dev group (B-07, A-04)
- **release**: use pre_bump_hooks so uv.lock lands in the bump commit

## v0.5.1 (2026-05-19)

### Fix

- **drift**: replace regex sig-extraction with AST; add plugin rollback
- guard empty tag_dirname and crash on empty YAML config
- **analysis**: broaden generic title detection to handle nested type params

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
