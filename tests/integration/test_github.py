"""Integration tests against the GitHub REST API spec.

The GitHub spec exercises:
- 500+ operations across many tags
- OAuth / API-key security schemes
- ``x-github-*`` vendor extension fields
- Shared component schemas referenced by many tags
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .helpers import assert_generate_succeeds, write_integration_config


@pytest.mark.integration
class TestGitHubSpec:
    def test_generate_exits_zero(self, github_spec: Path, tmp_path: Path) -> None:
        cfg = write_integration_config(tmp_path, github_spec)
        assert_generate_succeeds(cfg)

    def test_many_model_files_created(self, github_spec: Path, tmp_path: Path) -> None:
        cfg = write_integration_config(tmp_path, github_spec)
        models_dir, _ = assert_generate_succeeds(cfg)
        py_files = list(models_dir.glob("*.py"))
        assert len(py_files) > 10, f"Expected >10 model files, got {len(py_files)}"

    def test_many_router_files_created(self, github_spec: Path, tmp_path: Path) -> None:
        cfg = write_integration_config(tmp_path, github_spec)
        _, routers_dir = assert_generate_succeeds(cfg)
        py_files = list(routers_dir.glob("*.py"))
        assert len(py_files) > 10, f"Expected >10 router files, got {len(py_files)}"

    def test_x_extensions_do_not_crash(self, github_spec: Path, tmp_path: Path) -> None:
        """x-github-* extension fields must not raise during generation."""
        cfg = write_integration_config(tmp_path, github_spec)
        # exit_code == 0 is the assertion; a crash would produce a non-zero exit
        assert_generate_succeeds(cfg)

    def test_shared_models_file_created(
        self, github_spec: Path, tmp_path: Path
    ) -> None:
        """Schemas referenced by multiple tags must land in shared.py."""
        cfg = write_integration_config(tmp_path, github_spec)
        models_dir, _ = assert_generate_succeeds(cfg)
        assert (models_dir / "shared.py").exists()

    def test_models_have_pydantic_base_classes(
        self, github_spec: Path, tmp_path: Path
    ) -> None:
        cfg = write_integration_config(tmp_path, github_spec)
        models_dir, _ = assert_generate_succeeds(cfg)
        any_pydantic = any(
            "from pydantic" in f.read_text(encoding="utf-8")
            for f in models_dir.glob("*.py")
        )
        assert any_pydantic, "No 'from pydantic' found in any model file"
