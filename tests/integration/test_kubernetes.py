"""Integration tests against the Kubernetes API spec.

The Kubernetes spec exercises:
- Very large spec (~5 MB, 600+ definitions)
- Circular ``$ref`` chains that must be detected and not cause infinite loops
- Many internal types with complex inheritance
- OAS 2.0 / Swagger format (kubernetes/swagger.json is Swagger 2.0 format)

Note: these tests may take 30–90 seconds due to the size of the spec.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .helpers import assert_generate_succeeds, write_integration_config


@pytest.mark.integration
class TestKubernetesSpec:
    def test_generate_exits_zero(self, kubernetes_spec: Path, tmp_path: Path) -> None:
        """Kubernetes spec is ~5 MB; must not hang, crash, or hit RecursionError."""
        cfg = write_integration_config(tmp_path, kubernetes_spec)
        assert_generate_succeeds(cfg)

    def test_model_files_written(self, kubernetes_spec: Path, tmp_path: Path) -> None:
        cfg = write_integration_config(tmp_path, kubernetes_spec)
        models_dir, _ = assert_generate_succeeds(cfg)
        py_files = list(models_dir.glob("*.py"))
        assert len(py_files) >= 1, "No model files generated from Kubernetes spec"

    def test_circular_refs_do_not_hang(
        self, kubernetes_spec: Path, tmp_path: Path
    ) -> None:
        """Circular $ref chains must terminate; if mishandled this hangs or raises RecursionError."""
        cfg = write_integration_config(tmp_path, kubernetes_spec)
        # assert_generate_succeeds will raise AssertionError if exit_code != 0,
        # and the test runner will kill it on timeout if it hangs.
        assert_generate_succeeds(cfg)
