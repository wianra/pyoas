"""
Tests for SkillScaffolder.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from syrupy.assertion import SnapshotAssertion

from pyoas.claude.scaffolder import SkillScaffolder
from pyoas.core.config import (
    Config,
    FieldsConfig,
    FormatConfig,
    OutputConfig,
    ServicesConfig,
    SkillsConfig,
    TestsConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    skills_output: str,
    *,
    not_found_exception: str | None = None,
    overwrite: bool = True,
    has_services: bool = False,
    services_pattern: str = "none",
) -> Config:
    return Config(
        spec="openapi.yaml",
        output=OutputConfig(
            models="src/generated/models",
            routers="src/generated/routers",
        ),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        services=ServicesConfig(
            generate=has_services,
            output="src/services",
            overwrite=False,
            import_path="myapp.services" if has_services else "",
        ),
        tests=TestsConfig(
            generate=True,
            output="tests/generated",
            overwrite=False,
            not_found_exception=not_found_exception,
        ),
        skills=SkillsConfig(
            generate=True,
            output=skills_output,
            overwrite=overwrite,
            services_pattern=services_pattern,
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_scaffold_creates_skill_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        SkillScaffolder(cfg).scaffold()
        assert (Path(tmp) / "implement-tests.md").exists()


def test_scaffold_skips_when_not_configured() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec="openapi.yaml",
            output=OutputConfig(
                models="src/generated/models",
                routers="src/generated/routers",
            ),
            # skills.generate defaults to False
        )
        SkillScaffolder(cfg).scaffold()
        assert not list(Path(tmp).glob("implement-tests.md"))


def test_scaffold_skips_existing_when_overwrite_false(capsys) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, overwrite=True)
        SkillScaffolder(cfg).scaffold()
        skill_file = Path(tmp) / "implement-tests.md"
        skill_file.write_text("# custom", encoding="utf-8")

        cfg2 = _make_config(tmp, overwrite=False)
        SkillScaffolder(cfg2).scaffold()

        assert skill_file.read_text(encoding="utf-8") == "# custom"
        assert "skipped" in capsys.readouterr().out


def test_scaffold_overwrites_when_overwrite_true() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, overwrite=True)
        SkillScaffolder(cfg).scaffold()
        skill_file = Path(tmp) / "implement-tests.md"
        skill_file.write_text("# corrupted", encoding="utf-8")

        SkillScaffolder(cfg).scaffold()
        assert "implement me" in skill_file.read_text(encoding="utf-8")


def test_scaffold_output_snapshot(snapshot: SnapshotAssertion) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(
            tmp,
            not_found_exception="HTTPException(status_code=404, detail='Not found')",
            has_services=True,
        )
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "implement-tests.md").read_text(encoding="utf-8")
        assert content == snapshot


def test_not_found_exception_in_skill() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(
            tmp,
            not_found_exception="HTTPException(status_code=404, detail='Not found')",
        )
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "implement-tests.md").read_text(encoding="utf-8")
        assert "HTTPException(status_code=404, detail='Not found')" in content


def test_no_not_found_exception_shows_placeholder() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, not_found_exception=None)
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "implement-tests.md").read_text(encoding="utf-8")
        assert "<NotFoundError>" in content


def test_tests_output_path_in_skill() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "implement-tests.md").read_text(encoding="utf-8")
        assert "tests/generated" in content


def test_services_output_in_skill_when_services_enabled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, has_services=True)
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "implement-tests.md").read_text(encoding="utf-8")
        assert "src/services" in content
        assert "client_with_mock" in content


def test_services_section_absent_when_no_services() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, has_services=False)
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "implement-tests.md").read_text(encoding="utf-8")
        assert "client_with_mock" not in content


def test_scaffold_creates_output_dir_if_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        nested = tmp + "/new/subdir"
        cfg = _make_config(nested)
        SkillScaffolder(cfg).scaffold()
        assert (Path(nested) / "implement-tests.md").exists()


def test_scaffold_creates_add_test_case_skill() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        SkillScaffolder(cfg).scaffold()
        assert (Path(tmp) / "add-test-case.md").exists()


def test_scaffold_creates_review_generated_skill() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        SkillScaffolder(cfg).scaffold()
        assert (Path(tmp) / "review-generated.md").exists()


def test_add_test_case_skill_contains_tests_output() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "add-test-case.md").read_text(encoding="utf-8")
        assert "tests/generated" in content


def test_add_test_case_skill_contains_service_mock_when_services_enabled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, has_services=True)
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "add-test-case.md").read_text(encoding="utf-8")
        assert "client_with_mock" in content


def test_add_test_case_skill_no_mock_section_without_services() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, has_services=False)
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "add-test-case.md").read_text(encoding="utf-8")
        assert "client_with_mock" not in content


def test_review_generated_skill_contains_spec_and_paths() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "review-generated.md").read_text(encoding="utf-8")
        assert "openapi.yaml" in content
        assert "src/generated/routers" in content
        assert "src/generated/models" in content


def test_add_test_case_skips_existing_when_overwrite_false(capsys) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, overwrite=True)
        SkillScaffolder(cfg).scaffold()
        skill_file = Path(tmp) / "add-test-case.md"
        skill_file.write_text("# custom", encoding="utf-8")

        cfg2 = _make_config(tmp, overwrite=False)
        SkillScaffolder(cfg2).scaffold()

        assert skill_file.read_text(encoding="utf-8") == "# custom"
        assert "skipped" in capsys.readouterr().out


def test_review_generated_skips_existing_when_overwrite_false(capsys) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, overwrite=True)
        SkillScaffolder(cfg).scaffold()
        skill_file = Path(tmp) / "review-generated.md"
        skill_file.write_text("# custom", encoding="utf-8")

        cfg2 = _make_config(tmp, overwrite=False)
        SkillScaffolder(cfg2).scaffold()

        assert skill_file.read_text(encoding="utf-8") == "# custom"
        assert "skipped" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# implement-services skill
# ---------------------------------------------------------------------------


def test_scaffold_creates_implement_services_skill_when_services_enabled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, has_services=True)
        SkillScaffolder(cfg).scaffold()
        assert (Path(tmp) / "implement-services.md").exists()


def test_scaffold_does_not_create_implement_services_when_no_services() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, has_services=False)
        SkillScaffolder(cfg).scaffold()
        assert not (Path(tmp) / "implement-services.md").exists()


def test_implement_services_skill_contains_services_output() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, has_services=True)
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "implement-services.md").read_text(encoding="utf-8")
        assert "src/services" in content


def test_implement_services_skill_contains_tests_output() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, has_services=True)
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "implement-services.md").read_text(encoding="utf-8")
        assert "tests/generated" in content


def test_implement_services_skips_existing_when_overwrite_false(capsys) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, has_services=True, overwrite=True)
        SkillScaffolder(cfg).scaffold()
        skill_file = Path(tmp) / "implement-services.md"
        skill_file.write_text("# custom", encoding="utf-8")

        cfg2 = _make_config(tmp, has_services=True, overwrite=False)
        SkillScaffolder(cfg2).scaffold()

        assert skill_file.read_text(encoding="utf-8") == "# custom"
        assert "skipped" in capsys.readouterr().out


def test_implement_services_overwrites_when_overwrite_true() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, has_services=True, overwrite=True)
        SkillScaffolder(cfg).scaffold()
        skill_file = Path(tmp) / "implement-services.md"
        skill_file.write_text("# corrupted", encoding="utf-8")

        SkillScaffolder(cfg).scaffold()
        assert "NotImplementedError" in skill_file.read_text(encoding="utf-8")


def test_implement_services_snapshot(snapshot: SnapshotAssertion) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(
            tmp,
            has_services=True,
            not_found_exception="HTTPException(status_code=404, detail='Not found')",
        )
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "implement-services.md").read_text(encoding="utf-8")
        assert content == snapshot


def test_implement_services_repository_pattern_hint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, has_services=True, services_pattern="repository")
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "implement-services.md").read_text(encoding="utf-8")
        assert "repository pattern" in content.lower()
        assert "self._repo" in content


def test_implement_services_no_pattern_hint_for_none() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp, has_services=True, services_pattern="none")
        SkillScaffolder(cfg).scaffold()
        content = (Path(tmp) / "implement-services.md").read_text(encoding="utf-8")
        assert "self._repo" not in content
