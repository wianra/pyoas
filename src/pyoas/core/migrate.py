"""CLI handler and output formatters for ``pyoas migrate``."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import typer

from pyoas.core.differ import MigrationIssue, classify_changes, diff_specs


def _load_spec(source: str) -> dict[str, Any]:
    """Load and resolve an OpenAPI spec from a file path or URL."""
    from pyoas.core.parser import SpecParser
    from pyoas.core.resolver import resolve_refs

    if source.startswith(("http://", "https://")):
        import urllib.request

        suffix = ".yaml" if source.lower().endswith((".yaml", ".yml")) else ".json"
        try:
            with urllib.request.urlopen(source) as resp:  # noqa: S310  # nosec B310
                content = resp.read()
        except Exception as exc:
            raise ValueError(f"Failed to download spec from {source!r}: {exc}") from exc

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(content)
            tmp_path = f.name

        try:
            raw = SpecParser(tmp_path).load()
            return resolve_refs(raw, tmp_path)
        finally:
            os.unlink(tmp_path)

    p = Path(source)
    if not p.exists():
        raise FileNotFoundError(f"Spec file not found: {source!r}")
    raw = SpecParser(source).load()
    return resolve_refs(raw, source)


def _emit_text(issues: list[MigrationIssue], breaking_only: bool) -> None:
    """Print a coloured text report to stdout."""
    breaking = [i for i in issues if i.severity == "breaking"]
    non_breaking = [i for i in issues if i.severity == "non_breaking"]

    def _location(issue: MigrationIssue) -> str:
        if issue.method and issue.path:
            return f"{issue.method} {issue.path}"
        return ""

    for issue in breaking:
        label = typer.style("  [BREAKING]     ", fg=typer.colors.RED)
        typer.echo(
            f"{label} {issue.issue:<35} {_location(issue)} — {issue.description}"
        )

    if not breaking_only:
        for issue in non_breaking:
            label = typer.style("  [NON-BREAKING] ", fg=typer.colors.CYAN)
            typer.echo(
                f"{label} {issue.issue:<35} {_location(issue)} — {issue.description}"
            )

    typer.echo(
        f"\n  {len(breaking)} breaking change(s), {len(non_breaking)} non-breaking change(s)"
    )


def _emit_json(issues: list[MigrationIssue], breaking_only: bool) -> None:
    """Print a structured JSON report to stdout."""
    breaking = [i for i in issues if i.severity == "breaking"]
    non_breaking = [i for i in issues if i.severity == "non_breaking"]

    def _to_dict(i: MigrationIssue) -> dict[str, Any]:
        return {
            "path": i.path,
            "method": i.method,
            "operation_id": i.operation_id,
            "issue": i.issue,
            "description": i.description,
        }

    data: dict[str, Any] = {
        "breaking": [_to_dict(i) for i in breaking],
        "non_breaking": [] if breaking_only else [_to_dict(i) for i in non_breaking],
        "summary": {
            "breaking": len(breaking),
            "non_breaking": len(non_breaking),
        },
    }
    typer.echo(json.dumps(data))


def run_migrate(
    old_spec: str,
    new_spec: str,
    *,
    json_output: bool = False,
    breaking_only: bool = False,
) -> int:
    """Load, diff, classify, and report. Returns exit code (0 or 1)."""
    try:
        old = _load_spec(old_spec)
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"Error loading old spec: {exc}", err=True)
        return 1

    try:
        new = _load_spec(new_spec)
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"Error loading new spec: {exc}", err=True)
        return 1

    diff = diff_specs(old, new)
    issues = classify_changes(diff)

    if json_output:
        _emit_json(issues, breaking_only)
    else:
        _emit_text(issues, breaking_only)

    return 1 if any(i.severity == "breaking" for i in issues) else 0
