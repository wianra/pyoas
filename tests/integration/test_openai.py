"""Integration tests against the OpenAI API spec.

The OpenAI spec exercises:
- Nullable fields and mixed OAS 3.0 patterns
- Streaming / event-type response schemas
- oneOf with varied discriminator patterns
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .helpers import assert_generate_succeeds, write_integration_config


@pytest.mark.integration
class TestOpenAISpec:
    def test_generate_exits_zero(self, openai_spec: Path, tmp_path: Path) -> None:
        cfg = write_integration_config(tmp_path, openai_spec)
        assert_generate_succeeds(cfg)

    def test_models_have_pydantic_imports(
        self, openai_spec: Path, tmp_path: Path
    ) -> None:
        cfg = write_integration_config(tmp_path, openai_spec)
        models_dir, _ = assert_generate_succeeds(cfg)
        any_pydantic = any(
            "from pydantic" in f.read_text(encoding="utf-8")
            for f in models_dir.glob("*.py")
        )
        assert any_pydantic, "No 'from pydantic' found in any model file"

    def test_routers_have_fastapi_imports(
        self, openai_spec: Path, tmp_path: Path
    ) -> None:
        cfg = write_integration_config(tmp_path, openai_spec)
        _, routers_dir = assert_generate_succeeds(cfg)
        any_fastapi = any(
            "from fastapi" in f.read_text(encoding="utf-8")
            for f in routers_dir.glob("*.py")
        )
        assert any_fastapi, "No 'from fastapi' found in any router file"

    def test_nullable_fields_do_not_crash(
        self, openai_spec: Path, tmp_path: Path
    ) -> None:
        """anyOf: [{$ref: X}, {type: 'null'}] nullable patterns must not crash."""
        cfg = write_integration_config(tmp_path, openai_spec)
        assert_generate_succeeds(cfg)
