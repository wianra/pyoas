"""
Tests for RouterScaffolder and detect_router_drift.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from syrupy.assertion import SnapshotAssertion

from pyoas.core.config import (
    Config,
    FieldsConfig,
    FormatConfig,
    OutputConfig,
    RouterScaffoldConfig,
)
from pyoas.fastapi.routerscaffold import RouterScaffolder, detect_router_drift

FIXTURES = Path(__file__).parents[1] / "fixtures"
PETSTORE = FIXTURES / "petstore_3.0.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(spec_path: str, output_dir: str) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(
            models="src/generated/models",
            routers=str(Path(output_dir) / "gen_routers"),
        ),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        router_scaffold=RouterScaffoldConfig(
            generate=True,
            output=output_dir,
            overwrite=False,
        ),
    )


def _make_cfg_overwrite(spec_path: str, output_dir: str) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(
            models="src/generated/models",
            routers=str(Path(output_dir) / "gen_routers"),
        ),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        router_scaffold=RouterScaffoldConfig(
            generate=True,
            output=output_dir,
            overwrite=True,
        ),
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Snapshot tests — first run
# ---------------------------------------------------------------------------


def test_scaffold_petstore_30_first_run(
    petstore_30: Path, snapshot: SnapshotAssertion
) -> None:
    """First run: full scaffold file with raise NotImplementedError, safe-to-edit header."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        RouterScaffolder(cfg).scaffold()

        output = Path(tmp)
        assert (output / "pets.py").exists()
        assert (output / "__init__.py").exists()

        pets_src = _read(output / "pets.py")
        assert "# Scaffolded by pyoas" in pets_src
        assert "do not edit manually" not in pets_src
        assert "raise NotImplementedError" in pets_src
        assert "return await service." not in pets_src
        assert "get_pets_service" not in pets_src

        assert pets_src == snapshot(name="pets_scaffold_30_first_run")


def test_scaffold_does_not_import_service(petstore_30: Path) -> None:
    """Scaffold router must never import from the service layer."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        RouterScaffolder(cfg).scaffold()

        pets_src = _read(Path(tmp) / "pets.py")
        assert "PetsService" not in pets_src
        assert "get_pets_service" not in pets_src
        assert "Depends(get_pets_service)" not in pets_src


# ---------------------------------------------------------------------------
# Append-only: second run skips unchanged endpoints
# ---------------------------------------------------------------------------


def test_scaffold_skips_existing_endpoints(petstore_30: Path) -> None:
    """Second run does not duplicate existing endpoint functions."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        RouterScaffolder(cfg).scaffold()
        first_src = _read(Path(tmp) / "pets.py")

        # Second run — file already exists with all endpoints
        RouterScaffolder(cfg).scaffold()
        second_src = _read(Path(tmp) / "pets.py")

        assert first_src == second_src


def test_scaffold_appends_new_endpoint(petstore_30: Path) -> None:
    """After removing one endpoint from the file, second run re-adds it."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        RouterScaffolder(cfg).scaffold()

        pets_file = Path(tmp) / "pets.py"
        original = _read(pets_file)

        # Remove the list_pets endpoint block from the file
        lines = original.split("\n")
        # Find the @router.get("/pets" line and cut from there to the next @router
        cut_start = None
        cut_end = None
        for i, line in enumerate(lines):
            if "@router.get" in line and cut_start is None:
                cut_start = i
            elif "@router." in line and cut_start is not None:
                cut_end = i
                break
        assert cut_start is not None and cut_end is not None
        modified = "\n".join(lines[:cut_start] + lines[cut_end:])
        pets_file.write_text(modified)

        # Second run should re-add the missing endpoint
        RouterScaffolder(cfg).scaffold()
        restored = _read(pets_file)

        # Original endpoints should all be present
        assert "async def list_pets(" in restored
        assert "async def create_pet(" in restored
        assert "async def get_pet(" in restored


def test_scaffold_warns_orphaned_endpoint(petstore_30: Path, capsys) -> None:  # noqa: ANN001
    """Endpoints in file with no matching spec operation emit a WARNING."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        RouterScaffolder(cfg).scaffold()

        pets_file = Path(tmp) / "pets.py"
        existing = _read(pets_file)
        # Inject a ghost endpoint
        ghost = (
            "\n\n@router.get('/ghost')\nasync def ghost_endpoint() -> None:\n"
            "    raise NotImplementedError\n"
        )
        pets_file.write_text(existing + ghost)

        RouterScaffolder(cfg).scaffold()
        captured = capsys.readouterr()
        assert "orphaned" in captured.err.lower() or "ghost_endpoint" in captured.err


def test_scaffold_overwrite_regenerates_file(petstore_30: Path) -> None:
    """overwrite=True fully regenerates the file even if it already exists."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        RouterScaffolder(cfg).scaffold()

        pets_file = Path(tmp) / "pets.py"
        # Clobber the file with garbage
        pets_file.write_text("# this file was trashed\n")

        cfg_ow = _make_cfg_overwrite(str(petstore_30), tmp)
        RouterScaffolder(cfg_ow).scaffold()

        restored = _read(pets_file)
        assert "# Scaffolded by pyoas" in restored
        assert "raise NotImplementedError" in restored
        assert "this file was trashed" not in restored


# ---------------------------------------------------------------------------
# detect_router_drift
# ---------------------------------------------------------------------------


def _make_drift_cfg(tmp_path: Path) -> Config:
    return Config(
        spec=str(PETSTORE),
        output=OutputConfig(
            models=str(tmp_path / "models"),
            routers=str(tmp_path / "gen_routers"),
        ),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        router_scaffold=RouterScaffoldConfig(
            generate=True,
            output=str(tmp_path / "routers"),
            overwrite=False,
        ),
    )


def test_detect_router_drift_missing_file(tmp_path: Path) -> None:
    """Router directory empty → RouterDriftItem(kind='missing_file') for each tag."""
    cfg = _make_drift_cfg(tmp_path)
    (tmp_path / "routers").mkdir()

    items = detect_router_drift(cfg)

    assert len(items) >= 1
    kinds = {i.kind for i in items}
    assert "missing_file" in kinds
    for item in items:
        if item.kind == "missing_file":
            assert item.endpoint is None


def test_detect_router_drift_missing_endpoint(tmp_path: Path) -> None:
    """Router file exists but is missing an endpoint → kind='missing_endpoint'."""
    router_dir = tmp_path / "routers"
    router_dir.mkdir()
    # Write a pets.py with only list_pets defined
    (router_dir / "pets.py").write_text(
        "from fastapi import APIRouter\n\nrouter = APIRouter(tags=['pets'])\n\n"
        "async def list_pets() -> None:\n    raise NotImplementedError\n"
    )
    cfg = _make_drift_cfg(tmp_path)

    items = detect_router_drift(cfg)

    missing = [i for i in items if i.kind == "missing_endpoint"]
    assert len(missing) >= 1
    endpoint_names = {i.endpoint for i in missing}
    assert "create_pet" in endpoint_names or "get_pet" in endpoint_names


def test_detect_router_drift_orphaned_endpoint(tmp_path: Path) -> None:
    """Endpoint in file has no matching spec operation → kind='orphaned_endpoint'."""
    router_dir = tmp_path / "routers"
    router_dir.mkdir()
    (router_dir / "pets.py").write_text(
        "from fastapi import APIRouter\n\nrouter = APIRouter(tags=['pets'])\n\n"
        "async def list_pets() -> None:\n    raise NotImplementedError\n\n"
        "async def create_pet() -> None:\n    raise NotImplementedError\n\n"
        "async def get_pet() -> None:\n    raise NotImplementedError\n\n"
        "async def ghost_old_endpoint() -> None:\n    raise NotImplementedError\n"
    )
    cfg = _make_drift_cfg(tmp_path)

    items = detect_router_drift(cfg)

    orphaned = [i for i in items if i.kind == "orphaned_endpoint"]
    assert any(i.endpoint == "ghost_old_endpoint" for i in orphaned)


def test_detect_router_drift_clean_returns_empty(tmp_path: Path) -> None:
    """No drift when scaffold files match the spec exactly."""
    cfg = _make_drift_cfg(tmp_path)
    # Generate the scaffold first
    RouterScaffolder(cfg).scaffold()

    items = detect_router_drift(cfg)

    non_orphan = [i for i in items if i.kind != "orphaned_endpoint"]
    assert non_orphan == []


def test_detect_router_drift_tag_filter(tmp_path: Path) -> None:
    """Tag filter limits drift detection to specified tags."""
    router_dir = tmp_path / "routers"
    router_dir.mkdir()
    # Only create pets.py — store.py is missing but we filter to pets only
    cfg = _make_drift_cfg(tmp_path)
    RouterScaffolder(cfg).scaffold(tag_filter=["pets"])

    items = detect_router_drift(cfg, tag_filter=["pets"])

    missing_files = [i for i in items if i.kind == "missing_file"]
    assert all("pets" in i.file for i in missing_files)
