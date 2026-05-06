"""
DependencyScaffolder — writes FastAPI dependency stubs from security scheme info.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from pyoas.core.config import Config
from pyoas.core.parser import SpecParser
from pyoas.core.renderer import Renderer
from pyoas.core.result import ScaffoldResult
from pyoas.core.tags import extract_tags

_DEFAULT_TEMPLATES = Path(__file__).parent / "templates"


def _detect_security_scheme(spec_raw: dict[str, Any]) -> tuple[str, str]:
    """Inspect ``components.securitySchemes`` and return ``(scheme_type, oauth2_token_url)``.

    ``scheme_type`` is one of ``"bearer"``, ``"basic"``, ``"apikey"``, ``"oauth2"``.
    Falls back to ``"bearer"`` when no schemes are declared.
    ``oauth2_token_url`` is only meaningful when ``scheme_type == "oauth2"``.
    """
    schemes = spec_raw.get("components", {}).get("securitySchemes", {})
    # Priority: oauth2 > bearer > basic > apikey. Collect all and pick the best.
    _priority = {"oauth2": 3, "bearer": 2, "basic": 1, "apikey": 0}
    best: tuple[str, str] = ("bearer", "")
    best_priority = -1
    for scheme in schemes.values():
        t = scheme.get("type", "")
        if t == "http":
            name = scheme.get("scheme", "bearer").lower()
            p = _priority.get(name, 0)
            if p > best_priority:
                best_priority = p
                best = (name, "")
        elif t == "oauth2":
            p = _priority["oauth2"]
            if p > best_priority:
                best_priority = p
                best = ("oauth2", _extract_oauth2_token_url(scheme))
        elif t == "apiKey":
            p = _priority["apikey"]
            if p > best_priority:
                best_priority = p
                best = ("apikey", "")
    return best


def _extract_oauth2_token_url(scheme: dict[str, Any]) -> str:
    """Return the first tokenUrl found in an OAuth2 security scheme's flows."""
    flows = scheme.get("flows", {})
    for flow in flows.values():
        url = flow.get("tokenUrl", "")
        if url:
            return url
    return "token"


def _has_any_secured_operation(spec_raw: dict[str, Any], default_tag: str) -> bool:
    """Return True if at least one operation in the spec requires authentication."""
    from pyoas.fastapi.generator import _has_security

    global_security: list[Any] = spec_raw.get("security") or []
    grouped = extract_tags(spec_raw, default_tag=default_tag)
    for operations in grouped.values():
        for op_entry in operations:
            operation = op_entry["operation"]
            if _has_security(operation, global_security):
                return True
    return False


def _collect_all_scopes(spec_raw: dict[str, Any], default_tag: str) -> list[str]:
    """Return a sorted, deduplicated list of all OAuth2 scope names in the spec."""
    from pyoas.fastapi.generator import _extract_security_scopes

    global_security: list[Any] = spec_raw.get("security") or []
    grouped = extract_tags(spec_raw, default_tag=default_tag)
    scopes: list[str] = []
    for operations in grouped.values():
        for op_entry in operations:
            for scope in _extract_security_scopes(
                op_entry["operation"], global_security
            ):
                if scope not in scopes:
                    scopes.append(scope)
    return sorted(scopes)


class DependencyScaffolder:
    def __init__(self, config: Config) -> None:
        self._config = config

    def scaffold(self) -> ScaffoldResult:
        result = ScaffoldResult()
        cfg = self._config
        if not cfg.dependencies.generate and not cfg.dependencies.import_path:
            typer.echo(
                "Dependency generation is not configured. "
                "Set dependencies.generate: true in config.",
                err=True,
            )
            return result

        spec_raw = SpecParser(cfg.spec).load()

        if not _has_any_secured_operation(spec_raw, cfg.default_tag):
            typer.echo(
                "No secured operations found in the spec — skipping dependency scaffolding.",
                err=True,
            )
            return result

        scheme_type, oauth2_token_url = _detect_security_scheme(spec_raw)

        renderer = Renderer(default_templates_dir=_DEFAULT_TEMPLATES)
        output_root = Path(cfg.dependencies.output)
        output_root.mkdir(parents=True, exist_ok=True)

        auth_file = output_root / "auth.py"
        if not auth_file.exists() or cfg.dependencies.overwrite:
            all_scopes = _collect_all_scopes(spec_raw, cfg.default_tag)
            src = renderer.render(
                "dependency_auth.py.jinja2",
                {
                    "scheme_type": scheme_type,
                    "oauth2_token_url": oauth2_token_url,
                    "all_scopes": all_scopes,
                },
            )
            auth_file.write_text(src, encoding="utf-8")
            typer.echo(typer.style(f"  wrote  {auth_file}", fg=typer.colors.GREEN))
            result.wrote += 1
        else:
            typer.echo(
                typer.style(
                    f"  skipped  {auth_file} — already exists",
                    fg=typer.colors.YELLOW,
                )
            )
            result.skipped += 1

        init_file = output_root / "__init__.py"
        if not init_file.exists():
            init_file.write_text(
                "# Scaffolded by pyoas — safe to edit.\n", encoding="utf-8"
            )
        return result
