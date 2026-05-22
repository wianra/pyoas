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


def test_scaffold_bearer_scheme_uses_http_bearer(tmp_path: Path) -> None:
    """Bearer scheme produces an HTTPBearer dependency stub."""
    cfg = _make_cfg(str(FIXTURES / "secured.yaml"), str(tmp_path / "deps"))
    DependencyScaffolder(cfg).scaffold()

    src = (tmp_path / "deps" / "auth.py").read_text()
    assert "HTTPBearer" in src
    assert "HTTPAuthorizationCredentials" in src
    assert "credentials.credentials" in src


def test_scaffold_auth_does_not_import_unused_field(tmp_path: Path) -> None:
    """B-24: ``field`` is only mentioned in the AuthContext docstring, never in code,
    so the dataclasses import line must not pull it in."""
    cfg = _make_cfg(str(FIXTURES / "secured.yaml"), str(tmp_path / "deps"))
    DependencyScaffolder(cfg).scaffold()

    src = (tmp_path / "deps" / "auth.py").read_text()
    assert "from dataclasses import dataclass\n" in src
    assert "from dataclasses import dataclass, field" not in src


def test_scaffold_basic_scheme_uses_http_basic(tmp_path: Path) -> None:
    """Basic auth scheme produces an HTTPBasic dependency stub."""
    cfg = _make_cfg(str(FIXTURES / "secured_basic.yaml"), str(tmp_path / "deps"))
    DependencyScaffolder(cfg).scaffold()

    src = (tmp_path / "deps" / "auth.py").read_text()
    assert "HTTPBasic" in src
    assert "HTTPBasicCredentials" in src
    assert "credentials.username" in src


def test_scaffold_apikey_scheme_uses_api_key_header(tmp_path: Path) -> None:
    """API key scheme produces an APIKeyHeader dependency stub."""
    cfg = _make_cfg(str(FIXTURES / "secured_apikey.yaml"), str(tmp_path / "deps"))
    DependencyScaffolder(cfg).scaffold()

    src = (tmp_path / "deps" / "auth.py").read_text()
    assert "APIKeyHeader" in src
    assert "api_key" in src


def test_scaffold_oauth2_scheme_uses_oauth2_password_bearer(tmp_path: Path) -> None:
    """OAuth2 scheme produces an OAuth2PasswordBearer dependency stub with the token URL."""
    cfg = _make_cfg(str(FIXTURES / "secured_scoped.yaml"), str(tmp_path / "deps"))
    DependencyScaffolder(cfg).scaffold()

    src = (tmp_path / "deps" / "auth.py").read_text()
    assert "OAuth2PasswordBearer" in src
    assert "tokenUrl=" in src
    assert "/token" in src
