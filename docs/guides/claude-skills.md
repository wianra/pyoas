# Claude Code Skills

pyoas can generate [Claude Code](https://claude.ai/code) skill files (slash commands) that help you implement the scaffolded stubs. This feature requires the `pyoas[claude]` package.

## Installation

```shell
uv add pyoas[claude]
```

## Enabling skill generation

```yaml
# pyoas.yaml
skills:
  generate: true
  output: .claude/commands
  services_pattern: none    # none | repository | domain
```

Then run:

```shell
pyoas generate
# or, standalone:
pyoas scaffold skills
```

## Generated skills

Four skill files are written to `.claude/commands/`:

| File | Slash command | Purpose |
|---|---|---|
| `implement-tests.md` | `/implement-tests` | Implement all `pytest.skip("implement me")` stubs in a test file |
| `add-test-case.md` | `/add-test-case` | Add a new test method for a described scenario |
| `review-generated.md` | `/review-generated` | Cross-check generated code against the OpenAPI spec |
| `implement-services.md` | `/implement-services` | Implement service method stubs |

## Using the skills

### `/implement-tests`

```
/implement-tests tests/generated/test_pets.py
```

Claude reads the test file and the corresponding service, then implements all `pytest.skip` stubs — writing mocks, assertions, and setup for each.

### `/add-test-case`

```
/add-test-case tests/generated/test_pets.py "creating a pet with duplicate name returns 409"
```

Claude adds a new test method to the appropriate class in the test file.

### `/review-generated`

```
/review-generated
```

Claude compares all generated routers and models against the OpenAPI spec and reports:
- Missing endpoints or operations
- Parameter type mismatches
- Response type mismatches
- Undocumented error responses

### `/implement-services`

```
/implement-services src/services/pets.py
```

Claude reads the service file, the generated models, and the routers, then implements the `NotImplementedError` stubs using the service pattern configured in `skills.services_pattern`.

## `services_pattern`

Hints at your service layer architecture so Claude generates appropriate implementations:

| Value | Pattern |
|---|---|
| `none` | Plain service class; no specific layers assumed |
| `repository` | Service delegates data access to a repository object (injected via `__init__`) |
| `domain` | Service contains domain logic; infrastructure concerns are separate |

```yaml
skills:
  services_pattern: repository
```

## Overwriting

By default, skill files are never overwritten. To regenerate:

```yaml
skills:
  overwrite: true
```
