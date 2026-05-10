"""Plugin protocol and loader for pyoas.

Plugins are discovered from two sources (in order):
1. pyproject.toml entry-points group ``"pyoas.plugins"``
2. Explicit ``"module:ClassName"`` strings in ``config.plugins``

All discovered plugins are instantiated (no-args constructor) and validated
against the Plugin Protocol before being returned from :func:`load_plugins`.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from typing import Any, Protocol, runtime_checkable

from pyoas.core.config import Config


class PluginError(ValueError):
    """Raised when a plugin cannot be loaded or violates the hook contract."""


@runtime_checkable
class Plugin(Protocol):
    """Lifecycle protocol for pyoas plugins.

    Implement all four methods and set ``name`` / ``version`` attributes.
    Install via ``pyproject.toml`` entry-points group ``"pyoas.plugins"`` or
    list explicitly in ``pyoas.yaml`` under ``plugins:``.
    """

    name: str
    version: str

    def on_spec_loaded(
        self, spec: dict[str, Any], resolved: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return ``(raw, resolved)`` — may modify in-place or replace entirely."""
        ...

    def on_model_file_written(self, tag: str, path: str, content: str) -> str:
        """Return (possibly modified) content after a model file is rendered.

        Must return a non-empty string.  Return *content* unchanged if no
        modifications are needed.
        """
        ...

    def on_router_file_written(self, tag: str, path: str, content: str) -> str:
        """Return (possibly modified) content after a router file is rendered.

        Must return a non-empty string.  Return *content* unchanged if no
        modifications are needed.
        """
        ...

    def on_generate_complete(self, stats: dict[str, Any]) -> None:
        """Called once after all files have been written.

        *stats* contains at minimum: ``files_written`` (int), ``tags`` (list),
        ``skipped`` (int).
        """
        ...


def _load_plugin_class(spec_str: str) -> type:
    """Import and return a class given a ``'module:ClassName'`` specifier."""
    if ":" not in spec_str:
        raise PluginError(
            f"Plugin specifier {spec_str!r} must be in 'module:ClassName' format"
        )
    module_name, class_name = spec_str.rsplit(":", 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise PluginError(
            f"Plugin module {module_name!r} could not be imported: {exc}"
        ) from exc
    if not hasattr(module, class_name):
        raise PluginError(
            f"Plugin module {module_name!r} has no attribute {class_name!r}"
        )
    return getattr(module, class_name)  # type: ignore[no-any-return]


def _instantiate_and_validate(cls: type, source: str) -> Plugin:
    """Instantiate *cls* and verify it satisfies the Plugin protocol."""
    try:
        instance = cls()
    except Exception as exc:
        raise PluginError(
            f"Plugin class {cls.__name__!r} (from {source!r}) could not be"
            f" instantiated: {exc}"
        ) from exc
    if not isinstance(instance, Plugin):
        raise PluginError(
            f"Object {instance!r} (from {source!r}) does not satisfy the Plugin"
            " protocol. Ensure it has 'name', 'version', and all four hook methods."
        )
    return instance  # type: ignore[return-value]


def load_plugins(config: Config) -> list[Plugin]:
    """Load all plugins from entry-points and ``config.plugins``.

    Discovery order:

    1. Entry-points under ``"pyoas.plugins"`` group (alphabetical by name).
    2. Explicit entries in ``config.plugins`` (in list order).

    Duplicate class types (same class from both sources) are deduplicated by
    keeping the first occurrence.
    """
    seen: set[type] = set()
    plugins: list[Plugin] = []

    # 1. Entry-point discovery
    eps: Any
    try:
        eps = importlib.metadata.entry_points(group="pyoas.plugins")
    except Exception:  # noqa: BLE001
        eps = []
    for ep in eps:
        try:
            cls = ep.load()
        except Exception as exc:  # noqa: BLE001
            raise PluginError(
                f"Failed to load entry-point plugin {ep.name!r}: {exc}"
            ) from exc
        if cls not in seen:
            seen.add(cls)
            plugins.append(_instantiate_and_validate(cls, f"entry-point:{ep.name}"))

    # 2. Explicit config.plugins list (deduped against entry-points)
    for spec_str in config.plugins or []:
        cls = _load_plugin_class(spec_str)
        if cls not in seen:
            seen.add(cls)
            plugins.append(_instantiate_and_validate(cls, spec_str))

    return plugins
