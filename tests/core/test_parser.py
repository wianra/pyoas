from pathlib import Path

import pytest

from pyoas.core.parser import SpecParser


def test_load_petstore_30(petstore_30: Path) -> None:
    parser = SpecParser(str(petstore_30))
    spec = parser.load()
    assert spec["openapi"].startswith("3.0")
    assert parser.is_v30
    assert not parser.is_v31
    assert "paths" in spec
    assert "components" in spec


def test_load_petstore_31(petstore_31: Path) -> None:
    parser = SpecParser(str(petstore_31))
    spec = parser.load()
    assert spec["openapi"].startswith("3.1")
    assert parser.is_v31
    assert not parser.is_v30


def test_load_is_cached(petstore_30: Path) -> None:
    parser = SpecParser(str(petstore_30))
    spec1 = parser.load()
    spec2 = parser.load()
    assert spec1 is spec2


def test_unsupported_extension(tmp_path: Path) -> None:
    bad = tmp_path / "spec.xml"
    bad.write_text("<openapi/>")
    with pytest.raises(ValueError, match="Unsupported spec format"):
        SpecParser(str(bad)).load()


def test_openapi_version_before_load(petstore_30: Path) -> None:
    parser = SpecParser(str(petstore_30))
    with pytest.raises(RuntimeError):
        _ = parser.openapi_version
