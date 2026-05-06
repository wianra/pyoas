Cut a new pyoas release.

## Prerequisites

- All changes committed, working tree clean.
- Tests and linting pass (`/check`).

## Steps

```bash
uv run cz bump                           # bumps pyproject.toml, tags, updates CHANGELOG.md
git push origin main --follow-tags       # triggers publish.yml → PyPI
```

`cz bump` infers the version increment from conventional commit prefixes since the last tag:
- `fix:` → patch
- `feat:` → minor
- `feat!:` / `BREAKING CHANGE:` footer → major
