"""Tests for ParsedSpec value object."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyoas.core.config import (
    Config,
    FieldsConfig,
    FormatConfig,
    ModelConfig,
    OutputConfig,
)
from pyoas.core.parsed_spec import ParsedSpec

FIXTURES = Path(__file__).parents[1] / "fixtures"
PETSTORE = str(FIXTURES / "petstore_3.0.yaml")


def _make_config(spec_path: str) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(models="", routers=""),
        model_config=ModelConfig(extra="ignore", frozen=False, populate_by_name=True),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
    )


def test_from_config_raw_has_refs() -> None:
    """raw dict must still contain $ref strings (unresolved)."""
    cfg = _make_config(PETSTORE)
    ps = ParsedSpec.from_config(cfg)
    # petstore_3.0.yaml has $ref entries in its paths/components
    raw_str = str(ps.raw)
    assert "$ref" in raw_str


def test_from_config_resolved_has_no_dollar_ref_keys() -> None:
    """resolved dict must not contain any '$ref' keys — all references are inlined."""
    cfg = _make_config(PETSTORE)
    ps = ParsedSpec.from_config(cfg)

    def _has_ref_key(obj: object) -> bool:
        if isinstance(obj, dict):
            if "$ref" in obj:
                return True
            return any(_has_ref_key(v) for v in obj.values())
        if isinstance(obj, list):
            return any(_has_ref_key(item) for item in obj)
        return False

    assert not _has_ref_key(ps.resolved)


def test_from_config_frozen() -> None:
    """ParsedSpec must be immutable — attribute assignment must raise."""
    cfg = _make_config(PETSTORE)
    ps = ParsedSpec.from_config(cfg)
    with pytest.raises((AttributeError, TypeError)):
        ps.raw = {}  # type: ignore[misc]


def test_from_config_path_matches_spec() -> None:
    """path attribute must equal cfg.spec."""
    cfg = _make_config(PETSTORE)
    ps = ParsedSpec.from_config(cfg)
    assert ps.path == PETSTORE


def test_from_path_equivalent_to_from_config() -> None:
    """from_path and from_config must produce identical raw dicts."""
    cfg = _make_config(PETSTORE)
    ps_cfg = ParsedSpec.from_config(cfg)
    ps_path = ParsedSpec.from_path(PETSTORE)
    assert ps_cfg.raw == ps_path.raw
    assert ps_cfg.resolved == ps_path.resolved


def test_raw_not_mutated_by_resolution() -> None:
    """The raw dict must be independent of the resolved dict — mutating one must not affect the other."""
    cfg = _make_config(PETSTORE)
    ps = ParsedSpec.from_config(cfg)
    # Verify raw still has $ref strings even though resolved was built from it
    assert "$ref" in str(ps.raw)
    # A sentinel key injected into resolved must not appear in raw
    ps.resolved["__sentinel__"] = True  # type: ignore[index]
    assert "__sentinel__" not in ps.raw
