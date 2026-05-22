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
    ServicesConfig,
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


def test_scaffold_does_not_import_service_when_unset(petstore_30: Path) -> None:
    """Scaffold router omits service imports when services.import_path is empty."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        RouterScaffolder(cfg).scaffold()

        pets_src = _read(Path(tmp) / "pets.py")
        assert "PetsService" not in pets_src
        assert "get_pets_service" not in pets_src
        assert "Depends(get_pets_service)" not in pets_src


def _make_cfg_with_services(spec_path: str, output_dir: str) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(
            models="src/generated/models",
            routers=str(Path(output_dir) / "gen_routers"),
        ),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        services=ServicesConfig(
            generate=True,
            output=str(Path(output_dir) / "services"),
            import_path="src.services",
        ),
        router_scaffold=RouterScaffoldConfig(
            generate=True,
            output=output_dir,
            overwrite=False,
        ),
    )


def test_scaffold_delegates_to_service_when_configured(petstore_30: Path) -> None:
    """Scaffold router calls service.fn(...) when services.import_path is set."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg_with_services(str(petstore_30), tmp)
        RouterScaffolder(cfg).scaffold()

        pets_src = _read(Path(tmp) / "pets.py")
        assert "from src.services.pets import PetsService, get_pets_service" in pets_src
        assert "service: PetsService = Depends(get_pets_service)" in pets_src
        # GET list_pets returns list[Pet] → must use `return await service.list_pets(`
        assert "return await service.list_pets(" in pets_src
        assert "raise NotImplementedError" not in pets_src


def test_scaffold_append_adds_service_imports(petstore_30: Path) -> None:
    """When new endpoints are appended, the service import is added to the file."""
    with tempfile.TemporaryDirectory() as tmp:
        # First scaffold without services
        cfg_no_svc = _make_cfg(str(petstore_30), tmp)
        RouterScaffolder(cfg_no_svc).scaffold()
        pets_file = Path(tmp) / "pets.py"
        original = _read(pets_file)
        # Remove an endpoint so the next pass appends
        lines = original.split("\n")
        cut_start = next(i for i, ln in enumerate(lines) if "@router.get" in ln)
        cut_end = next(
            i
            for i, ln in enumerate(lines[cut_start + 1 :], cut_start + 1)
            if "@router." in ln
        )
        pets_file.write_text("\n".join(lines[:cut_start] + lines[cut_end:]))

        # Second pass with services enabled — must add svc import and use service
        cfg_svc = _make_cfg_with_services(str(petstore_30), tmp)
        RouterScaffolder(cfg_svc).scaffold()
        updated = _read(pets_file)
        assert "from src.services.pets import PetsService, get_pets_service" in updated
        assert "service: PetsService = Depends(get_pets_service)" in updated


def test_scaffold_docstring_indents_multiline_descriptions(tmp_path: Path) -> None:
    """Multi-line OpenAPI descriptions must keep every line indented under `\"\"\"`."""
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        "openapi: 3.0.3\n"
        "info: {title: t, version: '1'}\n"
        "paths:\n"
        "  /items:\n"
        "    get:\n"
        "      operationId: listItems\n"
        "      tags: [items]\n"
        "      description: |\n"
        "        first line\n"
        "        second line\n"
        "        third line\n"
        "      responses:\n"
        "        '200': {description: ok}\n",
        encoding="utf-8",
    )
    cfg = Config(
        spec=str(spec),
        output=OutputConfig(models=str(tmp_path / "m"), routers=str(tmp_path / "r")),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        router_scaffold=RouterScaffoldConfig(
            generate=True, output=str(tmp_path / "scaffold"), overwrite=False
        ),
    )
    RouterScaffolder(cfg).scaffold()
    src = _read(tmp_path / "scaffold" / "items.py")
    # All non-first description lines must be indented to column 4.
    assert '    """first line\n    second line\n    third line"""' in src


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
# Scaffold __init__.py re-exports
# ---------------------------------------------------------------------------


def test_scaffold_init_contains_router_reexports(petstore_30: Path) -> None:
    """First run: __init__.py re-exports each tag's router."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        RouterScaffolder(cfg).scaffold()

        init_src = _read(Path(tmp) / "__init__.py")
        assert "# Scaffolded by pyoas" in init_src
        assert "from .pets import router as pets_router  # noqa: F401" in init_src


def test_scaffold_init_preserves_user_edits_and_appends_new_tag(
    petstore_30: Path,
) -> None:
    """Re-run: user-added lines stay; imports for new tags are appended."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        RouterScaffolder(cfg).scaffold()

        init_path = Path(tmp) / "__init__.py"
        original = _read(init_path)
        # Simulate user adding their own line, and removing an auto re-export.
        user_edited = original.replace(
            "from .pets import router as pets_router  # noqa: F401",
            "from .pets import router as pets_router  # noqa: F401\n"
            "# user-added comment\n"
            "my_custom = object()",
        )
        init_path.write_text(user_edited, encoding="utf-8")

        # Second run with the same spec: nothing new, file unchanged.
        RouterScaffolder(cfg).scaffold()
        assert _read(init_path) == user_edited

        # Now drop the pets import entirely and re-run — it should be re-appended.
        truncated = (
            "# Scaffolded by pyoas — keep my header\n"
            "from __future__ import annotations\n\n"
            "# user-added comment\n"
            "my_custom = object()\n"
        )
        init_path.write_text(truncated, encoding="utf-8")
        RouterScaffolder(cfg).scaffold()
        after = _read(init_path)
        assert "# user-added comment" in after
        assert "my_custom = object()" in after
        assert "from .pets import router as pets_router  # noqa: F401" in after


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


# ---------------------------------------------------------------------------
# skip_extensions
# ---------------------------------------------------------------------------


_DRAFT_SPEC_YAML = """\
openapi: 3.0.3
info: {title: t, version: '1'}
paths:
  /published:
    get:
      operationId: listPublished
      tags: [items]
      responses:
        '200': {description: ok}
  /draft:
    get:
      operationId: listDraft
      tags: [items]
      x-draft: true
      responses:
        '200': {description: ok}
"""


def _make_skip_cfg(spec_path: Path, output_dir: Path) -> Config:
    return Config(
        spec=str(spec_path),
        output=OutputConfig(
            models=str(output_dir / "gen_models"),
            routers=str(output_dir / "gen_routers"),
        ),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        router_scaffold=RouterScaffoldConfig(
            generate=True,
            output=str(output_dir),
            overwrite=False,
        ),
        skip_extensions={"x-draft": None},
    )


def test_router_scaffold_skips_x_draft_operations(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(_DRAFT_SPEC_YAML, encoding="utf-8")

    output_dir = tmp_path / "routers"
    cfg = _make_skip_cfg(spec_path, output_dir)
    RouterScaffolder(cfg).scaffold()

    items_src = _read(output_dir / "items.py")
    assert "list_published" in items_src
    assert "list_draft" not in items_src


def test_router_drift_ignores_x_draft_operations(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(_DRAFT_SPEC_YAML, encoding="utf-8")

    output_dir = tmp_path / "routers"
    cfg = _make_skip_cfg(spec_path, output_dir)
    RouterScaffolder(cfg).scaffold()

    items = detect_router_drift(cfg)
    # No drift expected — draft op should be filtered out, published op already
    # scaffolded.
    assert [i for i in items if i.kind != "orphaned_endpoint"] == []
