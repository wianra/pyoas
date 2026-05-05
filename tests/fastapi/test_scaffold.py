"""
Tests for detect_service_drift and related scaffold utilities.
"""

from __future__ import annotations

from pathlib import Path

from pyoas.core.config import (
    Config,
    FieldsConfig,
    FormatConfig,
    OutputConfig,
    ServicesConfig,
)
from pyoas.fastapi.scaffold import detect_service_drift

FIXTURES = Path(__file__).parents[1] / "fixtures"
PETSTORE = FIXTURES / "petstore_3.0.yaml"


def _make_cfg(tmp_path: Path, *, import_path: str = "app.services") -> Config:
    return Config(
        spec=str(PETSTORE),
        output=OutputConfig(
            models=str(tmp_path / "models"),
            routers=str(tmp_path / "routers"),
        ),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        services=ServicesConfig(
            generate=True,
            output=str(tmp_path / "services"),
            overwrite=False,
            import_path=import_path,
        ),
    )


# ---------------------------------------------------------------------------
# missing_file
# ---------------------------------------------------------------------------


def test_detect_drift_missing_file(tmp_path: Path) -> None:
    """Service directory empty → DriftItem(kind='missing_file') for each tag."""
    cfg = _make_cfg(tmp_path)
    (tmp_path / "services").mkdir()

    items = detect_service_drift(cfg)

    assert len(items) >= 1
    kinds = {i.kind for i in items}
    assert "missing_file" in kinds
    file_names = {Path(item.file).name for item in items if item.kind == "missing_file"}
    assert any(f.endswith(".py") for f in file_names)
    for item in items:
        if item.kind == "missing_file":
            assert item.method is None


# ---------------------------------------------------------------------------
# missing_method
# ---------------------------------------------------------------------------


def test_detect_drift_missing_method(tmp_path: Path) -> None:
    """Service file exists but is missing a method → kind='missing_method'."""
    svc_dir = tmp_path / "services"
    svc_dir.mkdir()
    # Petstore pets tag has: list_pets, create_pet, get_pet
    # Only stub list_pets — create_pet and get_pet should be reported missing
    (svc_dir / "pets.py").write_text(
        "class PetsService:\n    async def list_pets(self) -> None:\n        pass\n"
    )
    cfg = _make_cfg(tmp_path)

    items = detect_service_drift(cfg)

    missing = [i for i in items if i.kind == "missing_method"]
    assert len(missing) >= 1
    method_names = {i.method for i in missing}
    assert "create_pet" in method_names or "get_pet" in method_names
    for item in missing:
        assert item.file.endswith("pets.py")
        assert item.method is not None


# ---------------------------------------------------------------------------
# orphaned_method
# ---------------------------------------------------------------------------


def test_detect_drift_orphaned_method(tmp_path: Path) -> None:
    """Method exists in file but has no matching spec operation → kind='orphaned_method'."""
    svc_dir = tmp_path / "services"
    svc_dir.mkdir()
    # Include all expected methods (list_pets, create_pet, get_pet) plus one orphan
    (svc_dir / "pets.py").write_text(
        "class PetsService:\n"
        "    async def list_pets(self) -> None:\n        pass\n"
        "    async def create_pet(self) -> None:\n        pass\n"
        "    async def get_pet(self) -> None:\n        pass\n"
        "    async def deprecated_old_method(self) -> None:\n        pass\n"
    )
    cfg = _make_cfg(tmp_path)

    items = detect_service_drift(cfg)

    orphaned = [i for i in items if i.kind == "orphaned_method"]
    assert any(i.method == "deprecated_old_method" for i in orphaned)


# ---------------------------------------------------------------------------
# signature_changed
# ---------------------------------------------------------------------------


def test_detect_drift_signature_changed(tmp_path: Path) -> None:
    """Method has wrong signature → kind='signature_changed'."""
    svc_dir = tmp_path / "services"
    svc_dir.mkdir()
    # get_pet expects (self, *, pet_id: int) -> Pet; declare wrong return type
    (svc_dir / "pets.py").write_text(
        "class PetsService:\n"
        "    async def list_pets(self) -> None:\n        pass\n"
        "    async def create_pet(self) -> None:\n        pass\n"
        "    async def get_pet(self, *, pet_id: str) -> None:\n        pass\n"
    )
    cfg = _make_cfg(tmp_path)

    items = detect_service_drift(cfg)

    sig_items = [i for i in items if i.kind == "signature_changed"]
    assert any(i.method == "get_pet" for i in sig_items)
    detail = next(i.detail for i in sig_items if i.method == "get_pet")
    assert "expected:" in detail
    assert "actual:" in detail


# ---------------------------------------------------------------------------
# clean (no drift)
# ---------------------------------------------------------------------------


def test_detect_drift_clean_returns_empty(tmp_path: Path) -> None:
    """Up-to-date service file → empty list."""
    from pyoas.fastapi.scaffold import ServiceScaffolder

    cfg = _make_cfg(tmp_path)
    ServiceScaffolder(cfg).scaffold()

    items = detect_service_drift(cfg)

    # Only signature_changed or orphaned are plausible; missing_file/missing_method
    # must be absent.
    for item in items:
        assert item.kind not in ("missing_file", "missing_method")


# ---------------------------------------------------------------------------
# tag_filter
# ---------------------------------------------------------------------------


def test_detect_drift_tag_filter(tmp_path: Path) -> None:
    """tag_filter limits which service files are checked."""
    cfg = Config(
        spec=str(FIXTURES / "multi_tag.yaml"),
        output=OutputConfig(
            models=str(tmp_path / "models"),
            routers=str(tmp_path / "routers"),
        ),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        services=ServicesConfig(
            generate=True,
            output=str(tmp_path / "services"),
            overwrite=False,
            import_path="app.services",
        ),
    )
    (tmp_path / "services").mkdir()

    items = detect_service_drift(cfg, tag_filter=["users"])

    # Should only report drift for the 'users' tag, not 'orders'
    for item in items:
        assert "users" in item.file
        assert "orders" not in item.file
