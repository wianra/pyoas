"""
Tests for ModelScaffolder and detect_model_drift.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from syrupy.assertion import SnapshotAssertion

from pyoas.core.config import (
    Config,
    FieldsConfig,
    FormatConfig,
    ModelScaffoldConfig,
    OutputConfig,
)
from pyoas.models.scaffolder import ModelScaffolder, detect_model_drift

FIXTURES = Path(__file__).parents[1] / "fixtures"
PETSTORE = FIXTURES / "petstore_3.0.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(spec_path: str, output_dir: str) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(
            models=str(Path(output_dir) / "gen_models"),
            routers=str(Path(output_dir) / "gen_routers"),
        ),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        model_scaffold=ModelScaffoldConfig(
            generate=True,
            output=output_dir,
            overwrite=False,
        ),
    )


def _make_cfg_overwrite(spec_path: str, output_dir: str) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(
            models=str(Path(output_dir) / "gen_models"),
            routers=str(Path(output_dir) / "gen_routers"),
        ),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        model_scaffold=ModelScaffoldConfig(
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
    """First run: full scaffold file with safe-to-edit header."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        ModelScaffolder(cfg).scaffold()

        output = Path(tmp)
        assert (output / "pets.py").exists()
        assert (output / "__init__.py").exists()

        pets_src = _read(output / "pets.py")
        assert "# Scaffolded by pyoas" in pets_src
        assert "do not edit manually" not in pets_src
        assert "BaseModel" in pets_src

        assert pets_src == snapshot(name="pets_models_scaffold_30_first_run")


# ---------------------------------------------------------------------------
# Append-only: second run skips unchanged schemas
# ---------------------------------------------------------------------------


def test_scaffold_skips_existing_classes(petstore_30: Path) -> None:
    """Second run does not duplicate existing class definitions."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        ModelScaffolder(cfg).scaffold()
        first_src = _read(Path(tmp) / "pets.py")

        ModelScaffolder(cfg).scaffold()
        second_src = _read(Path(tmp) / "pets.py")

        assert first_src == second_src


def test_scaffold_appends_new_schema(petstore_30: Path) -> None:
    """After removing one class from the file, second run re-adds it."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        ModelScaffolder(cfg).scaffold()

        pets_file = Path(tmp) / "pets.py"
        original = _read(pets_file)

        # Find a class definition and remove it from the file
        import re

        classes = re.findall(r"^class (\w+)", original, re.MULTILINE)
        if not classes:
            return  # no classes to remove, skip
        target = classes[0]

        # Remove the first class block
        m = re.search(rf"^class {re.escape(target)}", original, re.MULTILINE)
        assert m is not None
        next_m = re.search(r"^class \w+", original[m.start() + 1 :], re.MULTILINE)
        if next_m:
            end = m.start() + 1 + next_m.start()
        else:
            end = len(original)
        modified = original[: m.start()] + original[end:]
        pets_file.write_text(modified)

        # Second run should re-add the missing class
        ModelScaffolder(cfg).scaffold()
        restored = _read(pets_file)
        assert f"class {target}" in restored


def test_scaffold_warns_orphaned_class(petstore_30: Path, capsys) -> None:  # noqa: ANN001
    """Classes in file with no matching spec definition emit a WARNING."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        ModelScaffolder(cfg).scaffold()

        pets_file = Path(tmp) / "pets.py"
        existing = _read(pets_file)
        # Inject a ghost class
        ghost = "\n\nclass GhostOrphanedModel(BaseModel):\n    pass\n"
        pets_file.write_text(existing + ghost)

        ModelScaffolder(cfg).scaffold()
        captured = capsys.readouterr()
        assert (
            "orphaned" in captured.err.lower() or "GhostOrphanedModel" in captured.err
        )


def test_scaffold_overwrite_regenerates_file(petstore_30: Path) -> None:
    """overwrite=True fully regenerates the file even if it already exists."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_cfg(str(petstore_30), tmp)
        ModelScaffolder(cfg).scaffold()

        pets_file = Path(tmp) / "pets.py"
        pets_file.write_text("# this file was trashed\n")

        cfg_ow = _make_cfg_overwrite(str(petstore_30), tmp)
        ModelScaffolder(cfg_ow).scaffold()

        restored = _read(pets_file)
        assert "# Scaffolded by pyoas" in restored
        assert "BaseModel" in restored
        assert "this file was trashed" not in restored


# ---------------------------------------------------------------------------
# detect_model_drift
# ---------------------------------------------------------------------------


def _make_drift_cfg(tmp_path: Path) -> Config:
    return Config(
        spec=str(PETSTORE),
        output=OutputConfig(
            models=str(tmp_path / "gen_models"),
            routers=str(tmp_path / "gen_routers"),
        ),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        model_scaffold=ModelScaffoldConfig(
            generate=True,
            output=str(tmp_path / "models"),
            overwrite=False,
        ),
    )


def test_detect_model_drift_missing_file(tmp_path: Path) -> None:
    """Model directory empty → ModelDriftItem(kind='missing_file') for each tag."""
    cfg = _make_drift_cfg(tmp_path)
    (tmp_path / "models").mkdir()

    items = detect_model_drift(cfg)

    assert len(items) >= 1
    kinds = {i.kind for i in items}
    assert "missing_file" in kinds
    for item in items:
        if item.kind == "missing_file":
            assert item.schema is None


def test_detect_model_drift_missing_class(tmp_path: Path) -> None:
    """Model file exists but is missing a class → kind='missing_class'."""
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    # Write a minimal pets.py with no class definitions
    (model_dir / "pets.py").write_text(
        "# Scaffolded by pyoas\nfrom __future__ import annotations\n"
        "from pydantic import BaseModel, ConfigDict, Field\n"
    )
    cfg = _make_drift_cfg(tmp_path)

    items = detect_model_drift(cfg)

    missing = [i for i in items if i.kind == "missing_class" and "pets" in i.file]
    assert len(missing) >= 1
    for item in missing:
        assert item.schema is not None


def test_detect_model_drift_orphaned_class(tmp_path: Path) -> None:
    """Class in file has no matching spec definition → kind='orphaned_class'."""
    cfg = _make_drift_cfg(tmp_path)
    # Generate the scaffold first to get a valid file
    ModelScaffolder(cfg).scaffold()

    pets_file = tmp_path / "models" / "pets.py"
    existing = _read(pets_file)
    ghost = "\n\nclass OrphanedGhostModel(BaseModel):\n    pass\n"
    pets_file.write_text(existing + ghost)

    items = detect_model_drift(cfg)

    orphaned = [i for i in items if i.kind == "orphaned_class"]
    assert any(i.schema == "OrphanedGhostModel" for i in orphaned)


def test_detect_model_drift_clean_returns_empty(tmp_path: Path) -> None:
    """No drift when scaffold files match the spec exactly."""
    cfg = _make_drift_cfg(tmp_path)
    ModelScaffolder(cfg).scaffold()

    items = detect_model_drift(cfg)

    non_orphan = [i for i in items if i.kind not in ("orphaned_class",)]
    assert non_orphan == []


def test_detect_model_drift_tag_filter(tmp_path: Path) -> None:
    """Tag filter limits drift detection to specified tags."""
    cfg = _make_drift_cfg(tmp_path)
    ModelScaffolder(cfg).scaffold(tag_filter=["pets"])

    items = detect_model_drift(cfg, tag_filter=["pets"])

    missing_files = [i for i in items if i.kind == "missing_file"]
    # Pets tag should be present (we just scaffolded it)
    assert all("pets" not in i.file for i in missing_files)
