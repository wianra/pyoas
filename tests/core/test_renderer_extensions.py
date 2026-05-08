"""Tests for Renderer extension point (custom filters and globals)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from pyoas.core.config import ExtensionsConfig
from pyoas.core.renderer import Renderer


def _make_temp_module(name: str, attrs: dict) -> types.ModuleType:
    """Create and register a temporary in-memory module on sys.modules."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


@pytest.fixture(autouse=True)
def _cleanup_test_modules():
    yield
    for key in list(sys.modules.keys()):
        if key.startswith("_pyoas_test_"):
            del sys.modules[key]


def _simple_tmpl_dir(tmp_path: Path, source: str) -> Path:
    tmpl_dir = tmp_path / "templates"
    tmpl_dir.mkdir()
    (tmpl_dir / "test.jinja2").write_text(source)
    return tmpl_dir


def test_custom_filter_applied(tmp_path: Path) -> None:
    """A filter injected via ExtensionsConfig is usable in templates."""
    _make_temp_module(
        "_pyoas_test_filters",
        {"get_filters": lambda: {"shout": str.upper}},
    )
    tmpl_dir = _simple_tmpl_dir(tmp_path, "{{ name | shout }}")

    ext = ExtensionsConfig(filters="_pyoas_test_filters:get_filters")
    renderer = Renderer(default_templates_dir=tmpl_dir, extensions_config=ext)
    assert renderer.render("test.jinja2", {"name": "hello"}) == "HELLO"


def test_custom_global_applied(tmp_path: Path) -> None:
    """A global injected via ExtensionsConfig is accessible in templates."""
    _make_temp_module(
        "_pyoas_test_globals",
        {"get_globals": lambda: {"APP_NAME": "myapp"}},
    )
    tmpl_dir = _simple_tmpl_dir(tmp_path, "{{ APP_NAME }}")

    ext = ExtensionsConfig(globals="_pyoas_test_globals:get_globals")
    renderer = Renderer(default_templates_dir=tmpl_dir, extensions_config=ext)
    assert renderer.render("test.jinja2", {}) == "myapp"


def test_missing_module_raises(tmp_path: Path) -> None:
    """Nonexistent module raises ValueError at Renderer construction."""
    ext = ExtensionsConfig(filters="_pyoas_test_nonexistent_xyz:get_filters")
    with pytest.raises(ValueError, match="could not be imported"):
        Renderer(default_templates_dir=tmp_path, extensions_config=ext)


def test_missing_attr_raises(tmp_path: Path) -> None:
    """Module exists but attr is absent raises ValueError."""
    _make_temp_module("_pyoas_test_noattr", {})
    tmpl_dir = _simple_tmpl_dir(tmp_path, "x")

    ext = ExtensionsConfig(filters="_pyoas_test_noattr:get_filters")
    with pytest.raises(ValueError, match="has no attribute"):
        Renderer(default_templates_dir=tmpl_dir, extensions_config=ext)


def test_invalid_format_raises(tmp_path: Path) -> None:
    """A path without ':' raises ValueError about 'module:attr' format."""
    ext = ExtensionsConfig(filters="not_a_valid_format")
    with pytest.raises(ValueError, match="module:attr"):
        Renderer(default_templates_dir=tmp_path, extensions_config=ext)


def test_none_extensions_no_op(tmp_path: Path) -> None:
    """Renderer without extensions_config works exactly as before."""
    tmpl_dir = _simple_tmpl_dir(tmp_path, "{{ value }}")
    renderer = Renderer(default_templates_dir=tmpl_dir)
    assert renderer.render("test.jinja2", {"value": "ok"}) == "ok"
