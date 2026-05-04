from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined


class Renderer:
    """
    Jinja2 rendering engine with two-level template override resolution.

    Template lookup order:
    1. ``user_templates_dir`` (if provided via config)
    2. ``default_templates_dir`` (shipped with the package)

    Jinja2 ``StrictUndefined`` is used so missing template variables raise an
    error immediately instead of silently rendering as empty strings.
    """

    def __init__(
        self,
        default_templates_dir: Path,
        user_templates_dir: Path | None = None,
    ) -> None:
        search_path: list[str] = []
        if user_templates_dir is not None:
            search_path.append(str(user_templates_dir))
        search_path.append(str(default_templates_dir))

        self._env = Environment(  # nosec B701
            loader=FileSystemLoader(search_path),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            autoescape=False,
        )

    def render(self, template_name: str, context: dict[str, Any]) -> str:
        template = self._env.get_template(template_name)
        return template.render(**context)

    def render_string(self, source: str, context: dict[str, Any]) -> str:
        """Render a raw Jinja2 template string (useful in tests)."""
        template = self._env.from_string(source)
        return template.render(**context)
