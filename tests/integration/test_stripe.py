"""Integration tests against the Stripe API spec.

The Stripe spec exercises:
- Discriminated unions via ``oneOf`` with ``x-stripeResource`` annotations
- Large ``allOf`` chains (inherited base objects)
- Hundreds of component schemas across a small number of tags
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .helpers import assert_generate_succeeds, write_integration_config


@pytest.mark.integration
class TestStripeSpec:
    def test_generate_exits_zero(self, stripe_spec: Path, tmp_path: Path) -> None:
        cfg = write_integration_config(tmp_path, stripe_spec)
        assert_generate_succeeds(cfg)

    def test_models_contain_union_annotations(
        self, stripe_spec: Path, tmp_path: Path
    ) -> None:
        """Stripe uses oneOf extensively; Union[...] must appear in generated models."""
        cfg = write_integration_config(tmp_path, stripe_spec)
        models_dir, _ = assert_generate_succeeds(cfg)
        any_union = any(
            "Union[" in f.read_text(encoding="utf-8") for f in models_dir.glob("*.py")
        )
        assert any_union, "No Union annotations found; oneOf handling may be broken"

    def test_models_have_class_definitions(
        self, stripe_spec: Path, tmp_path: Path
    ) -> None:
        """allOf chains must produce class bodies with field definitions."""
        cfg = write_integration_config(tmp_path, stripe_spec)
        models_dir, _ = assert_generate_succeeds(cfg)
        combined = "\n".join(
            f.read_text(encoding="utf-8") for f in models_dir.glob("*.py")
        )
        assert "class " in combined, "No class definitions found in model files"

    def test_routers_not_empty(self, stripe_spec: Path, tmp_path: Path) -> None:
        cfg = write_integration_config(tmp_path, stripe_spec)
        _, routers_dir = assert_generate_succeeds(cfg)
        py_files = list(routers_dir.glob("*.py"))
        assert len(py_files) >= 1, "No router files generated"

    def test_x_stripe_extensions_do_not_crash(
        self, stripe_spec: Path, tmp_path: Path
    ) -> None:
        """x-stripeResource and related extensions must not raise during generation."""
        cfg = write_integration_config(tmp_path, stripe_spec)
        assert_generate_succeeds(cfg)
