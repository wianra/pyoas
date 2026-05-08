from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

if TYPE_CHECKING:
    from pyoas.core.config import ExtensionsConfig


def _load_extensions(env: Environment, ext: ExtensionsConfig) -> None:
    """Merge user-supplied filter and global dicts into *env*.

    Each of ``ext.filters`` and ``ext.globals`` is a ``"module:attr"`` string
    pointing to a zero-argument callable that returns a dict.  The returned
    dict is merged into ``env.filters`` or ``env.globals`` respectively.
    """
    for attr_path, target in (
        (ext.filters, env.filters),
        (ext.globals, env.globals),
    ):
        if not attr_path:
            continue
        if ":" not in attr_path:
            raise ValueError(
                f"extensions path {attr_path!r} must be in 'module:attr' format"
            )
        module_name, attr_name = attr_path.rsplit(":", 1)
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise ValueError(
                f"extensions module {module_name!r} could not be imported: {exc}"
            ) from exc
        if not hasattr(module, attr_name):
            raise ValueError(
                f"extensions module {module_name!r} has no attribute {attr_name!r}"
            )
        target.update(getattr(module, attr_name)())


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
        extensions_config: ExtensionsConfig | None = None,
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

        if extensions_config is not None:
            _load_extensions(self._env, extensions_config)

    def render(self, template_name: str, context: dict[str, Any]) -> str:
        template = self._env.get_template(template_name)
        return template.render(**context)

    def render_string(self, source: str, context: dict[str, Any]) -> str:
        """Render a raw Jinja2 template string (useful in tests)."""
        template = self._env.from_string(source)
        return template.render(**context)
