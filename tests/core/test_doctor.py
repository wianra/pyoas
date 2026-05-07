"""
Tests for pyoas doctor — run_doctor_checks() and the CLI command.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from pyoas.core.cli import app
from pyoas.core.config import Config, FieldsConfig, FormatConfig, OutputConfig
from pyoas.core.doctor import run_doctor_checks

FIXTURES = Path(__file__).parents[1] / "fixtures"
runner = CliRunner()


def _write_config(tmp_path: Path, spec: Path | str, **extra) -> Path:
    data: dict = {
        "spec": str(spec),
        "output": {
            "models": str(tmp_path / "models"),
            "routers": str(tmp_path / "routers"),
        },
        "format": {"enabled": False},
    }
    data.update(extra)
    cfg = tmp_path / "pyoas.yaml"
    cfg.write_text(yaml.dump(data), encoding="utf-8")
    return cfg


def _minimal_cfg(spec_path: str) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(models="models", routers="routers"),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
    )


# ---------------------------------------------------------------------------
# Unit tests — run_doctor_checks() directly
# ---------------------------------------------------------------------------


def test_clean_spec_returns_no_issues() -> None:
    """petstore_3.0.yaml has no doctor issues."""
    from pyoas.core.parser import SpecParser

    cfg = _minimal_cfg(str(FIXTURES / "petstore_3.0.yaml"))
    spec_raw = SpecParser(cfg.spec).load()
    issues = run_doctor_checks(spec_raw, cfg)
    errors = [i for i in issues if i.level == "error"]
    assert errors == []


def test_detects_missing_operation_id() -> None:
    spec_raw = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/items": {
                "get": {
                    # No operationId
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    cfg = _minimal_cfg("fake.yaml")
    issues = run_doctor_checks(spec_raw, cfg)
    assert any(
        i.check == "missing_operation_id" and i.level == "warning" for i in issues
    )


def test_detects_duplicate_operation_id() -> None:
    spec_raw = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/a": {
                "get": {
                    "operationId": "getItem",
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/b": {
                "get": {
                    "operationId": "getItem",
                    "responses": {"200": {"description": "ok"}},
                }
            },
        },
    }
    cfg = _minimal_cfg("fake.yaml")
    issues = run_doctor_checks(spec_raw, cfg)
    dupe = [i for i in issues if i.check == "duplicate_operation_id"]
    assert len(dupe) == 1
    assert dupe[0].level == "error"
    assert "getItem" in dupe[0].message


def test_detects_tag_collision() -> None:
    spec_raw = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/a": {
                "get": {
                    "operationId": "opA",
                    "tags": ["my-tag"],
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/b": {
                "get": {
                    "operationId": "opB",
                    "tags": ["my_tag"],
                    "responses": {"200": {"description": "ok"}},
                }
            },
        },
    }
    cfg = _minimal_cfg("fake.yaml")
    issues = run_doctor_checks(spec_raw, cfg)
    collision = [i for i in issues if i.check == "tag_collision"]
    assert len(collision) == 1
    assert collision[0].level == "error"
    assert "my-tag" in collision[0].message or "my_tag" in collision[0].message


def test_detects_ambiguous_schema() -> None:
    spec_raw = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "Mystery": {"description": "no type, no ref, no composition"},
            }
        },
    }
    cfg = _minimal_cfg("fake.yaml")
    issues = run_doctor_checks(spec_raw, cfg)
    ambiguous = [i for i in issues if i.check == "ambiguous_schema"]
    assert len(ambiguous) == 1
    assert ambiguous[0].level == "warning"
    assert "Mystery" in ambiguous[0].location


def test_detects_unresolvable_ref() -> None:
    spec_raw = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "Child": {
                    "type": "object",
                    "properties": {
                        "parent": {"$ref": "#/components/schemas/NonExistent"},
                    },
                }
            }
        },
    }
    cfg = _minimal_cfg("fake.yaml")
    issues = run_doctor_checks(spec_raw, cfg)
    unresolvable = [i for i in issues if i.check == "unresolvable_ref"]
    assert len(unresolvable) == 1
    assert unresolvable[0].level == "error"
    assert "NonExistent" in unresolvable[0].message


def test_schema_with_enum_is_not_ambiguous() -> None:
    """Schemas that have 'enum' but no 'type' should NOT be flagged as ambiguous."""
    spec_raw = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "Status": {"enum": ["active", "inactive"]},
            }
        },
    }
    cfg = _minimal_cfg("fake.yaml")
    issues = run_doctor_checks(spec_raw, cfg)
    ambiguous = [i for i in issues if i.check == "ambiguous_schema"]
    assert ambiguous == []


def test_detects_services_import_path_not_found() -> None:
    from pyoas.core.config import ServicesConfig

    cfg = Config(
        spec="fake.yaml",
        output=OutputConfig(models="models", routers="routers"),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        services=ServicesConfig(
            generate=True,
            output="src/services",
            import_path="nonexistent.module.that.does.not.exist",
        ),
    )
    spec_raw: dict = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
    }
    issues = run_doctor_checks(spec_raw, cfg)
    import_issues = [i for i in issues if i.check == "services_import_path"]
    assert len(import_issues) == 1
    assert import_issues[0].level == "warning"


def test_no_services_import_path_issue_when_empty() -> None:
    """No services_import_path warning when import_path is not set."""
    cfg = _minimal_cfg("fake.yaml")
    spec_raw: dict = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
    }
    issues = run_doctor_checks(spec_raw, cfg)
    import_issues = [i for i in issues if i.check == "services_import_path"]
    assert import_issues == []


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_doctor_exits_zero_on_clean_spec(tmp_path: Path) -> None:
    """doctor exits 0 and prints 'No issues' for a clean spec."""
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "No issues" in result.output


def test_doctor_exits_one_on_error_spec(tmp_path: Path) -> None:
    """doctor exits 1 and shows [ERROR] when spec has errors."""
    cfg = _write_config(tmp_path, FIXTURES / "doctor_issues.yaml")
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 1, result.output
    assert "[ERROR]" in result.output


def test_doctor_shows_warnings_exits_zero(tmp_path: Path) -> None:
    """doctor exits 0 but shows [WARNING] for warning-only spec."""
    # Write a spec with only a missing operationId (warning, not error)
    spec = tmp_path / "warn_only.yaml"
    spec.write_text(
        "openapi: '3.0.0'\n"
        "info: {title: T, version: '1'}\n"
        "paths:\n"
        "  /items:\n"
        "    get:\n"
        "      responses:\n"
        "        '200': {description: ok}\n",
        encoding="utf-8",
    )
    cfg = _write_config(tmp_path, spec)
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "[WARNING]" in result.output


def test_doctor_reports_duplicate_operation_id(tmp_path: Path) -> None:
    """doctor reports duplicate_operation_id in output."""
    cfg = _write_config(tmp_path, FIXTURES / "doctor_issues.yaml")
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert "duplicate_operation_id" in result.output


def test_doctor_reports_unresolvable_ref(tmp_path: Path) -> None:
    """doctor reports unresolvable_ref for BrokenRef schema."""
    cfg = _write_config(tmp_path, FIXTURES / "doctor_issues.yaml")
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert "unresolvable_ref" in result.output


# ---------------------------------------------------------------------------
# --json flag
# ---------------------------------------------------------------------------


def test_doctor_json_clean_spec_emits_ok_status(tmp_path: Path) -> None:
    """doctor --json emits {"status": "ok", "issues": []} for a clean spec."""
    import json

    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["doctor", "--config", str(cfg), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["issues"] == []


def test_doctor_json_error_spec_emits_error_status(tmp_path: Path) -> None:
    """doctor --json emits {"status": "error", "issues": [...]} and exits 1."""
    import json

    cfg = _write_config(tmp_path, FIXTURES / "doctor_issues.yaml")
    result = runner.invoke(app, ["doctor", "--config", str(cfg), "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert any(i["level"] == "error" for i in data["issues"])


def test_doctor_json_issue_shape(tmp_path: Path) -> None:
    """Each issue in --json output has level, check, message, location fields."""
    import json

    cfg = _write_config(tmp_path, FIXTURES / "doctor_issues.yaml")
    result = runner.invoke(app, ["doctor", "--config", str(cfg), "--json"])
    data = json.loads(result.output)
    for issue in data["issues"]:
        assert "level" in issue
        assert "check" in issue
        assert "message" in issue
        assert "location" in issue


def test_doctor_json_warning_exits_zero(tmp_path: Path) -> None:
    """doctor --json exits 0 when only warnings are present."""
    import json

    spec = tmp_path / "warn_only.yaml"
    spec.write_text(
        "openapi: '3.0.0'\n"
        "info: {title: T, version: '1'}\n"
        "paths:\n"
        "  /items:\n"
        "    get:\n"
        "      responses:\n"
        "        '200': {description: ok}\n",
        encoding="utf-8",
    )
    cfg = _write_config(tmp_path, spec)
    result = runner.invoke(app, ["doctor", "--config", str(cfg), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert any(i["level"] == "warning" for i in data["issues"])
