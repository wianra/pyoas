"""Tests for the pyoas plugin system (T4-D)."""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest import mock

import pytest

from pyoas.core.config import Config, OutputConfig
from pyoas.core.plugins import Plugin, PluginError, load_plugins

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _NullPlugin:
    """Minimal fully-conforming Plugin for use in tests."""

    name = "null-plugin"
    version = "0.0.0"

    def on_spec_loaded(
        self, spec: dict[str, Any], resolved: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return spec, resolved

    def on_model_file_written(self, tag: str, path: str, content: str) -> str:
        return content

    def on_router_file_written(self, tag: str, path: str, content: str) -> str:
        return content

    def on_generate_complete(self, stats: dict[str, Any]) -> None:
        pass


def _make_temp_module(name: str, attrs: dict) -> types.ModuleType:
    """Create and register an in-memory module on sys.modules."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


@pytest.fixture(autouse=True)
def _cleanup_test_modules():
    yield
    for key in list(sys.modules.keys()):
        if key.startswith("_pyoas_test_plugin_"):
            del sys.modules[key]


def _cfg(plugins: list[str] | None = None) -> Config:
    return Config(
        spec="fake.yaml",
        output=OutputConfig(),
        plugins=plugins or [],
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_null_plugin_satisfies_protocol() -> None:
    assert isinstance(_NullPlugin(), Plugin)


def test_non_conforming_class_does_not_satisfy_protocol() -> None:
    class _Bad:
        pass

    assert not isinstance(_Bad(), Plugin)


# ---------------------------------------------------------------------------
# load_plugins — happy paths
# ---------------------------------------------------------------------------


def test_load_plugins_empty_config_returns_empty() -> None:
    assert load_plugins(Config(spec="x.yaml")) == []


def test_load_plugins_from_config_list() -> None:
    _make_temp_module("_pyoas_test_plugin_a", {"_NullPlugin": _NullPlugin})
    plugins = load_plugins(_cfg(["_pyoas_test_plugin_a:_NullPlugin"]))
    assert len(plugins) == 1
    assert plugins[0].name == "null-plugin"


def test_load_plugins_multiple_entries() -> None:
    class _AnotherPlugin(_NullPlugin):
        name = "another"

    _make_temp_module(
        "_pyoas_test_plugin_multi",
        {"_NullPlugin": _NullPlugin, "_AnotherPlugin": _AnotherPlugin},
    )
    plugins = load_plugins(
        _cfg(
            [
                "_pyoas_test_plugin_multi:_NullPlugin",
                "_pyoas_test_plugin_multi:_AnotherPlugin",
            ]
        )
    )
    assert len(plugins) == 2
    assert {p.name for p in plugins} == {"null-plugin", "another"}


# ---------------------------------------------------------------------------
# load_plugins — error paths
# ---------------------------------------------------------------------------


def test_bad_format_raises() -> None:
    with pytest.raises(PluginError, match="module:ClassName"):
        load_plugins(_cfg(["notavalidformat"]))


def test_missing_module_raises() -> None:
    with pytest.raises(PluginError, match="could not be imported"):
        load_plugins(_cfg(["_no_such_module_xyz_abc:Plugin"]))


def test_missing_attr_raises() -> None:
    _make_temp_module("_pyoas_test_plugin_noattr", {})
    with pytest.raises(PluginError, match="has no attribute"):
        load_plugins(_cfg(["_pyoas_test_plugin_noattr:_NullPlugin"]))


def test_non_protocol_class_raises() -> None:
    class _Bad:
        pass

    _make_temp_module("_pyoas_test_plugin_bad", {"_Bad": _Bad})
    with pytest.raises(PluginError, match="Plugin protocol"):
        load_plugins(_cfg(["_pyoas_test_plugin_bad:_Bad"]))


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_dedup_by_class_across_sources() -> None:
    """Same class loaded from entry-point and config yields one instance."""
    _make_temp_module("_pyoas_test_plugin_dedup", {"_NullPlugin": _NullPlugin})

    fake_ep = mock.MagicMock()
    fake_ep.name = "null_plugin"
    fake_ep.load.return_value = _NullPlugin

    with mock.patch(
        "pyoas.core.plugins.importlib.metadata.entry_points",
        return_value=[fake_ep],
    ):
        plugins = load_plugins(_cfg(["_pyoas_test_plugin_dedup:_NullPlugin"]))

    assert len(plugins) == 1


# ---------------------------------------------------------------------------
# Entry-point discovery
# ---------------------------------------------------------------------------


def test_entry_point_discovery() -> None:
    fake_ep = mock.MagicMock()
    fake_ep.name = "null_plugin"
    fake_ep.load.return_value = _NullPlugin

    with mock.patch(
        "pyoas.core.plugins.importlib.metadata.entry_points",
        return_value=[fake_ep],
    ):
        plugins = load_plugins(Config(spec="x.yaml"))

    assert len(plugins) == 1
    assert plugins[0].name == "null-plugin"


def test_entry_point_discovery_skipped_when_exception() -> None:
    """If entry_points() raises, fall back to empty list gracefully."""
    with mock.patch(
        "pyoas.core.plugins.importlib.metadata.entry_points",
        side_effect=Exception("metadata unavailable"),
    ):
        plugins = load_plugins(Config(spec="x.yaml"))

    assert plugins == []


# ---------------------------------------------------------------------------
# on_spec_loaded hook (via _run_spec_loaded_hooks helper)
# ---------------------------------------------------------------------------


def test_run_spec_loaded_hooks_identity_when_no_plugins(tmp_path) -> None:
    from pyoas.core.cli import _run_spec_loaded_hooks
    from pyoas.core.parsed_spec import ParsedSpec

    spec = {"openapi": "3.0.0"}
    parsed = ParsedSpec(raw=spec, resolved=spec, path="x.yaml")
    result = _run_spec_loaded_hooks([], parsed)
    assert result is parsed


def test_run_spec_loaded_hooks_new_instance_when_modified(tmp_path) -> None:
    from pyoas.core.cli import _run_spec_loaded_hooks
    from pyoas.core.parsed_spec import ParsedSpec

    class _ModifyingPlugin(_NullPlugin):
        def on_spec_loaded(self, spec, resolved):
            return {**spec, "x-marker": True}, resolved

    spec = {"openapi": "3.0.0"}
    parsed = ParsedSpec(raw=spec, resolved=spec, path="x.yaml")
    result = _run_spec_loaded_hooks([_ModifyingPlugin()], parsed)
    assert result is not parsed
    assert result.raw.get("x-marker") is True
    assert result.path == parsed.path


# ---------------------------------------------------------------------------
# on_model_file_written hook via ModelGenerator
# ---------------------------------------------------------------------------


def test_on_model_file_written_hook_applied(tmp_path) -> None:
    """Plugin that prepends a header ends up in the written file."""
    from pyoas.core.config import Config, OutputConfig
    from pyoas.models.generator import ModelGenerator

    HEADER = "# INJECTED BY TEST\n"

    class _HeaderPlugin(_NullPlugin):
        def on_model_file_written(self, tag, path, content):
            return HEADER + content

    _make_temp_module("_pyoas_test_plugin_header", {"_HeaderPlugin": _HeaderPlugin})

    models_dir = tmp_path / "models"
    cfg = Config(
        spec=str(
            __import__("pathlib").Path(__file__).parent.parent
            / "fixtures"
            / "petstore_3.0.yaml"
        ),
        output=OutputConfig(
            models=str(models_dir),
            routers=str(tmp_path / "routers"),
        ),
        plugins=["_pyoas_test_plugin_header:_HeaderPlugin"],
    )

    gen = ModelGenerator(cfg)
    gen.generate(clean=True)

    written = list(models_dir.glob("*.py"))
    assert written, "No files were generated"
    for f in written:
        if f.name == "__init__.py":
            continue
        content = f.read_text(encoding="utf-8")
        assert content.startswith(HEADER), f"{f.name} missing injected header"


def test_on_model_file_written_empty_return_raises(tmp_path) -> None:
    from pyoas.core.config import Config, OutputConfig
    from pyoas.models.generator import ModelGenerator

    class _EmptyPlugin(_NullPlugin):
        def on_model_file_written(self, tag, path, content):
            return ""

    _make_temp_module("_pyoas_test_plugin_empty_m", {"_EmptyPlugin": _EmptyPlugin})

    models_dir = tmp_path / "models"
    cfg = Config(
        spec=str(
            __import__("pathlib").Path(__file__).parent.parent
            / "fixtures"
            / "petstore_3.0.yaml"
        ),
        output=OutputConfig(
            models=str(models_dir),
            routers=str(tmp_path / "routers"),
        ),
        plugins=["_pyoas_test_plugin_empty_m:_EmptyPlugin"],
    )

    with pytest.raises(PluginError, match="empty content"):
        ModelGenerator(cfg).generate(clean=True)


# ---------------------------------------------------------------------------
# on_router_file_written hook via RouterGenerator
# ---------------------------------------------------------------------------


def test_on_router_file_written_hook_applied(tmp_path) -> None:
    from pyoas.core.config import (
        Config,
        DependenciesConfig,
        OutputConfig,
        ServicesConfig,
    )
    from pyoas.fastapi.generator import RouterGenerator

    HEADER = "# ROUTER INJECTED BY TEST\n"

    class _RouterPlugin(_NullPlugin):
        def on_router_file_written(self, tag, path, content):
            return HEADER + content

    _make_temp_module("_pyoas_test_plugin_router", {"_RouterPlugin": _RouterPlugin})

    routers_dir = tmp_path / "routers"
    cfg = Config(
        spec=str(
            __import__("pathlib").Path(__file__).parent.parent
            / "fixtures"
            / "petstore_3.0.yaml"
        ),
        output=OutputConfig(
            models=str(tmp_path / "models"),
            routers=str(routers_dir),
        ),
        dependencies=DependenciesConfig(import_path="app.dependencies"),
        services=ServicesConfig(import_path="app.services"),
        plugins=["_pyoas_test_plugin_router:_RouterPlugin"],
    )

    RouterGenerator(cfg).generate(clean=True)

    written = list(routers_dir.glob("*.py"))
    assert written, "No router files were generated"
    for f in written:
        if f.name == "__init__.py":
            continue
        content = f.read_text(encoding="utf-8")
        assert content.startswith(HEADER), f"{f.name} missing injected header"


def test_on_router_file_written_empty_return_raises(tmp_path) -> None:
    from pyoas.core.config import (
        Config,
        DependenciesConfig,
        OutputConfig,
        ServicesConfig,
    )
    from pyoas.fastapi.generator import RouterGenerator

    class _EmptyPlugin(_NullPlugin):
        def on_router_file_written(self, tag, path, content):
            return ""

    _make_temp_module("_pyoas_test_plugin_empty_r", {"_EmptyPlugin": _EmptyPlugin})

    routers_dir = tmp_path / "routers"
    cfg = Config(
        spec=str(
            __import__("pathlib").Path(__file__).parent.parent
            / "fixtures"
            / "petstore_3.0.yaml"
        ),
        output=OutputConfig(
            models=str(tmp_path / "models"),
            routers=str(routers_dir),
        ),
        dependencies=DependenciesConfig(import_path="app.dependencies"),
        services=ServicesConfig(import_path="app.services"),
        plugins=["_pyoas_test_plugin_empty_r:_EmptyPlugin"],
    )

    with pytest.raises(PluginError, match="empty content"):
        RouterGenerator(cfg).generate(clean=True)


# ---------------------------------------------------------------------------
# on_generate_complete via CLI
# ---------------------------------------------------------------------------


def test_on_generate_complete_called(tmp_path) -> None:
    """CLI generate command calls on_generate_complete with stats dict."""
    from typer.testing import CliRunner

    from pyoas.core.cli import app

    calls: list[dict] = []

    class _TrackingPlugin(_NullPlugin):
        def on_generate_complete(self, stats):
            calls.append(dict(stats))

    _make_temp_module(
        "_pyoas_test_plugin_complete", {"_TrackingPlugin": _TrackingPlugin}
    )

    # Write a minimal pyoas.yaml in tmp_path
    petstore = (
        __import__("pathlib").Path(__file__).parent.parent
        / "fixtures"
        / "petstore_3.0.yaml"
    )
    config_file = tmp_path / "pyoas.yaml"
    config_file.write_text(
        f"""\
spec: {petstore}
output:
  models: {tmp_path / "models"}
  routers: {tmp_path / "routers"}
plugins:
  - _pyoas_test_plugin_complete:_TrackingPlugin
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["generate", "--config", str(config_file), "--quiet"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "files_written" in calls[0]


# ---------------------------------------------------------------------------
# Doctor: plugin_load check
# ---------------------------------------------------------------------------


def test_doctor_plugin_load_bad_format() -> None:
    from pyoas.core.doctor import run_doctor_checks

    cfg = _cfg(["notamodule"])
    spec_raw: dict = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
    }
    issues = run_doctor_checks(spec_raw, cfg)
    plugin_issues = [i for i in issues if i.check == "plugin_load"]
    assert len(plugin_issues) == 1
    assert plugin_issues[0].level == "error"
    assert "module:ClassName" in plugin_issues[0].message


def test_doctor_plugin_load_missing_module() -> None:
    from pyoas.core.doctor import run_doctor_checks

    cfg = _cfg(["_nonexistent_module_xyz_abc:Plugin"])
    spec_raw: dict = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
    }
    issues = run_doctor_checks(spec_raw, cfg)
    plugin_issues = [i for i in issues if i.check == "plugin_load"]
    assert len(plugin_issues) == 1
    assert plugin_issues[0].level == "error"
    assert "_nonexistent_module_xyz_abc" in plugin_issues[0].message


def test_doctor_no_plugin_issue_when_empty() -> None:
    from pyoas.core.doctor import run_doctor_checks

    cfg = Config(spec="fake.yaml")
    spec_raw: dict = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
    }
    issues = run_doctor_checks(spec_raw, cfg)
    assert not any(i.check == "plugin_load" for i in issues)
