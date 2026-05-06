Run the full QA suite.

```bash
uv run pytest                  # all tests
uv run ruff check src/         # linting (E, F, I, UP)
uv run mypy src/               # type checking
```

For targeted testing:

```bash
uv run pytest tests/fastapi/   # single area
uv run pytest tests/models/    # single area
```

Fix any failures before committing or releasing.
