"""
SkillScaffolder — writes Claude Code skill files for pyoas projects.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from pyoas.core.config import Config
from pyoas.core.renderer import Renderer
from pyoas.core.result import ScaffoldResult
from pyoas.core.utils import derive_import_path

_DEFAULT_TEMPLATES = Path(__file__).parent / "templates"


def _rel(path_str: str) -> str:
    """Return path_str as a relative path to cwd when possible."""
    p = Path(path_str)
    if not p.is_absolute():
        return path_str
    try:
        return str(p.relative_to(Path.cwd()))
    except ValueError:
        return path_str


class SkillScaffolder:
    def __init__(self, config: Config) -> None:
        self._config = config

    def scaffold(self) -> ScaffoldResult:
        result = ScaffoldResult()
        if not self._config.skills.generate:
            return result
        output_dir = Path(self._config.skills.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        context = self._build_context()
        renderer = Renderer(default_templates_dir=_DEFAULT_TEMPLATES)
        for method in (
            self._scaffold_implement_tests,
            self._scaffold_add_test_case,
            self._scaffold_review_generated,
            self._scaffold_implement_services,
        ):
            if method(output_dir, context, renderer):
                result.wrote += 1
            else:
                result.skipped += 1
        return result

    def _scaffold_implement_tests(
        self, output_dir: Path, context: dict[str, Any], renderer: Renderer
    ) -> bool:
        skill_file = output_dir / "implement-tests.md"
        if skill_file.exists() and not self._config.skills.overwrite:
            typer.echo(
                typer.style(
                    f"  skipped  {skill_file} — already exists", fg=typer.colors.YELLOW
                )
            )
            return False
        src = renderer.render("implement_tests.md.jinja2", context)
        skill_file.write_text(src, encoding="utf-8")
        typer.echo(typer.style(f"  wrote  {skill_file}", fg=typer.colors.GREEN))
        return True

    def _scaffold_add_test_case(
        self, output_dir: Path, context: dict[str, Any], renderer: Renderer
    ) -> bool:
        skill_file = output_dir / "add-test-case.md"
        if skill_file.exists() and not self._config.skills.overwrite:
            typer.echo(
                typer.style(
                    f"  skipped  {skill_file} — already exists", fg=typer.colors.YELLOW
                )
            )
            return False
        src = renderer.render("add_test_case.md.jinja2", context)
        skill_file.write_text(src, encoding="utf-8")
        typer.echo(typer.style(f"  wrote  {skill_file}", fg=typer.colors.GREEN))
        return True

    def _scaffold_review_generated(
        self, output_dir: Path, context: dict[str, Any], renderer: Renderer
    ) -> bool:
        skill_file = output_dir / "review-generated.md"
        if skill_file.exists() and not self._config.skills.overwrite:
            typer.echo(
                typer.style(
                    f"  skipped  {skill_file} — already exists", fg=typer.colors.YELLOW
                )
            )
            return False
        src = renderer.render("review_generated.md.jinja2", context)
        skill_file.write_text(src, encoding="utf-8")
        typer.echo(typer.style(f"  wrote  {skill_file}", fg=typer.colors.GREEN))
        return True

    def _scaffold_implement_services(
        self, output_dir: Path, context: dict[str, Any], renderer: Renderer
    ) -> bool:
        if not context["has_services"]:
            return False
        skill_file = output_dir / "implement-services.md"
        if skill_file.exists() and not self._config.skills.overwrite:
            typer.echo(
                typer.style(
                    f"  skipped  {skill_file} — already exists", fg=typer.colors.YELLOW
                )
            )
            return False
        src = renderer.render("implement_services.md.jinja2", context)
        skill_file.write_text(src, encoding="utf-8")
        typer.echo(typer.style(f"  wrote  {skill_file}", fg=typer.colors.GREEN))
        return True

    def _build_context(self) -> dict[str, Any]:
        cfg = self._config
        tests_output = _rel(cfg.tests.output)
        services_output = _rel(cfg.services.output) if cfg.services.generate else None
        models_import = cfg.output.models_import or derive_import_path(
            cfg.output.models, cfg.output.source_root
        )
        return {
            "spec": _rel(cfg.spec),
            "tests_output": tests_output,
            "services_output": services_output,
            "models_output": _rel(cfg.output.models),
            "routers_output": _rel(cfg.output.routers),
            "models_import_path": models_import,
            "router_import_path": cfg.output.routers_import
            or derive_import_path(cfg.output.routers, cfg.output.source_root),
            "has_services": bool(cfg.services.import_path),
            "not_found_exception": cfg.tests.not_found_exception,
            "services_pattern": cfg.skills.services_pattern,
        }
