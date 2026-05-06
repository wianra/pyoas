Commit staged changes using conventional commit format.

## Commit prefix rules

| Prefix | Version bump |
|---|---|
| `fix:` | patch — `0.2.0 → 0.2.1` |
| `feat:` | minor — `0.2.0 → 0.3.0` |
| `feat!:` or `BREAKING CHANGE:` footer | major — `0.2.0 → 1.0.0` |

## Steps

1. Run `git diff --staged` to review what's staged.
2. If nothing is staged, stage specific files by name (avoid `git add -A` or `git add .`).
3. Draft a concise commit message (imperative mood, ≤72 chars subject).
4. Commit:

```bash
git commit -m "$(cat <<'EOF'
type(scope): description

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

## If a hook fails

- **Auto-formatting hook** (e.g. ruff format stages changes then fails): stage the hook's changes and amend:
  ```bash
  git add <reformatted files>
  git commit --amend --no-edit
  ```
  This keeps one clean commit instead of a separate "fix formatting" commit.

- **Substantive failure** (lint errors, type errors, test failures): fix the code, stage, then create a **new** commit — do not amend.
