"""Tests for DependencyScaffolder — security scheme detection and scope annotation."""

from __future__ import annotations

from pathlib import Path

from pyoas.core.config import (
    Config,
    DependenciesConfig,
    FieldsConfig,
    FormatConfig,
    OutputConfig,
)
from pyoas.fastapi.deps_scaffold import DependencyScaffolder

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _make_cfg(spec_path: str, deps_dir: str) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(models="src/generated/models", routers=""),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        dependencies=DependenciesConfig(
            generate=True,
            output=deps_dir,
            overwrite=True,
            import_path="myapp.deps",
        ),
    )


def test_scaffold_emits_required_scopes(tmp_path: Path) -> None:
    """Scaffolded auth stub lists required scopes and TODO when scopes exist."""
    cfg = _make_cfg(str(FIXTURES / "secured_scoped.yaml"), str(tmp_path / "deps"))
    DependencyScaffolder(cfg).scaffold()

    src = (tmp_path / "deps" / "auth.py").read_text()
    assert "# Required scopes: read:pets, write:pets" in src
    assert "# TODO: validate scopes" in src


def test_scaffold_no_scope_comment_when_no_scopes(tmp_path: Path) -> None:
    """Bearer auth with no named scopes produces no scope comment in the stub."""
    cfg = _make_cfg(str(FIXTURES / "secured.yaml"), str(tmp_path / "deps"))
    DependencyScaffolder(cfg).scaffold()

    src = (tmp_path / "deps" / "auth.py").read_text()
    assert "# Required scopes:" not in src
    assert "# TODO: validate scopes" not in src


def test_scaffold_skips_when_no_secured_operations(tmp_path: Path, capsys) -> None:
    """Scaffolder emits a warning and skips when the spec has no secured operations."""
    cfg = _make_cfg(str(FIXTURES / "petstore_3.0.yaml"), str(tmp_path / "deps"))
    result = DependencyScaffolder(cfg).scaffold()

    assert result.wrote == 0
    stderr = capsys.readouterr().err
    assert "No secured operations" in stderr
