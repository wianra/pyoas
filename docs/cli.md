# CLI Reference

The `pyoas` command is the entry point for all code generation tasks.

## Global options

All commands accept:

| Option | Default | Description |
|---|---|---|
| `--config PATH` | `pyoas.yaml` | Path to the config file |
| `--help` | — | Show help and exit |

## `pyoas init`

Generate a starter `pyoas.yaml` config.

```shell
pyoas init SPEC [--output PATH] [--force]
```

| Argument / Option | Default | Description |
|---|---|---|
| `SPEC` | _(required)_ | Path to the OpenAPI spec file |
| `--output PATH` | `pyoas.yaml` | Where to write the config |
| `--force` | — | Overwrite an existing config |

**Example:**

```shell
pyoas init openapi.yaml
pyoas init specs/v2.yaml --output pyoas-v2.yaml
```

---

## `pyoas validate`

Validate the OpenAPI spec.

```shell
pyoas validate [--config PATH]
```

Exits 0 if the spec is valid, non-zero otherwise. Prints validation errors to stderr.

---

## `pyoas models`

Generate Pydantic v2 model files only.

```shell
pyoas models [--config PATH] [--tags TAGS] [--clean]
```

| Option | Description |
|---|---|
| `--tags TAG1,TAG2` | Comma-separated list of tags to generate; default: all |
| `--clean` | Purge the models output directory before generating |

**Example:**

```shell
pyoas models
pyoas models --tags pets,users
pyoas models --clean
```

---

## `pyoas fastapi`

Generate FastAPI router files only.

```shell
pyoas fastapi [--config PATH] [--tags TAGS] [--clean]
```

Same options as `pyoas models`.

---

## `pyoas generate`

Generate models + routers, and optionally run scaffolding if configured.

```shell
pyoas generate [--config PATH] [--tags TAGS] [--clean]
```

This is the primary command for day-to-day use. It generates:

1. Pydantic v2 models (`pyoas`)
2. FastAPI routers (`pyoas[fastapi]`)
3. Service stubs — if `services.generate: true`
4. Test stubs — if `tests.generate: true`
5. Dependency stubs — if `dependencies.generate: true`
6. Claude Code skills — if `skills.generate: true`

---

## `pyoas diff`

Dry-run: compute what would be generated and diff against current files.

```shell
pyoas diff [--config PATH] [--tags TAGS]
```

- Exits **0** if no files would change
- Exits **1** if any file would be added or modified
- Prints a unified diff to stdout

Use in CI to enforce that generated files are up to date:

```yaml
# .github/workflows/ci.yml
- name: Check generated files are up to date
  run: pyoas diff
```

---

## `pyoas watch`

Watch the spec file and re-run `pyoas generate` on every change.

```shell
pyoas watch [--config PATH] [--tags TAGS]
```

Useful during development. Press `Ctrl+C` to stop.

---

## `pyoas scaffold`

Standalone scaffolding commands. These are normally invoked automatically by `pyoas generate` when the corresponding `generate: true` flag is set. Use these to run scaffolding independently.

### `pyoas scaffold services`

```shell
pyoas scaffold services [--config PATH]
```

Scaffold service stub files. Skips existing files unless `services.overwrite: true`.

### `pyoas scaffold tests`

```shell
pyoas scaffold tests [--config PATH]
```

Scaffold pytest test stub files. Appends new test classes to existing files.

### `pyoas scaffold dependencies`

```shell
pyoas scaffold dependencies [--config PATH]
```

Scaffold dependency injection stubs (`src/dependencies/auth.py`). Skips if exists.

### `pyoas scaffold skills`

```shell
pyoas scaffold skills [--config PATH]
```

Scaffold Claude Code skill files. Requires `pyoas[claude]`. Skips existing files unless `skills.overwrite: true`.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Generation error, validation failure, or diff detected changes |
| `2` | Bad arguments / config parse error |
