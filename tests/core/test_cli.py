from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest import mock

import yaml
from typer.testing import CliRunner

from pyoas import __version__
from pyoas.core.cli import app

FIXTURES = Path(__file__).parents[1] / "fixtures"
runner = CliRunner()


def _write_config(tmp_path: Path, spec: Path | str, **extra) -> Path:
    """Write a minimal pyoas.yaml to tmp_path and return its path."""
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


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------


def test_version_prints_and_exits_zero() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"pyoas {__version__}" in result.output


def test_version_format_contains_semver() -> None:
    assert re.match(r"\d+\.\d+\.\d+", __version__) is not None


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_creates_config_file(tmp_path: Path) -> None:
    out = tmp_path / "pyoas.yaml"
    result = runner.invoke(
        app, ["init", str(FIXTURES / "petstore_3.0.yaml"), "--output", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "Created" in result.output
    assert out.exists()


def test_init_config_contains_spec_path(tmp_path: Path) -> None:
    spec = FIXTURES / "petstore_3.0.yaml"
    out = tmp_path / "pyoas.yaml"
    runner.invoke(app, ["init", str(spec), "--output", str(out)])
    assert str(spec) in out.read_text()


def test_init_refuses_existing_file_without_force(tmp_path: Path) -> None:
    out = tmp_path / "pyoas.yaml"
    out.write_text("existing")
    result = runner.invoke(app, ["init", "openapi.yaml", "--output", str(out)])
    assert result.exit_code == 1
    assert "already exists" in result.output
    assert out.read_text() == "existing"


def test_init_overwrites_with_force(tmp_path: Path) -> None:
    out = tmp_path / "pyoas.yaml"
    out.write_text("existing")
    result = runner.invoke(
        app, ["init", "openapi.yaml", "--output", str(out), "--force"]
    )
    assert result.exit_code == 0
    assert "Created" in result.output
    assert "spec:" in out.read_text()


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_valid_spec_exits_zero(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["validate", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_validate_missing_spec_file_exits_one(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, tmp_path / "missing.yaml")
    result = runner.invoke(app, ["validate", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_validate_invalid_spec_exits_one(tmp_path: Path) -> None:
    # .txt extension triggers ValueError("Unsupported spec format") which is caught
    spec = tmp_path / "spec.txt"
    spec.write_text("not a spec")
    cfg = _write_config(tmp_path, spec)
    result = runner.invoke(app, ["validate", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "Error" in result.output


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


def test_models_writes_model_files(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["models", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    assert (tmp_path / "models" / "pets.py").exists()


def test_models_tags_filter_restricts_output(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "multi_tag.yaml")
    result = runner.invoke(app, ["models", "--config", str(cfg), "--tags", "users"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "models" / "users.py").exists()
    assert not (tmp_path / "models" / "orders.py").exists()


def test_models_clean_removes_stale_files(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    runner.invoke(app, ["models", "--config", str(cfg)])
    stale = tmp_path / "models" / "stale.py"
    stale.write_text("# stale")
    runner.invoke(app, ["models", "--config", str(cfg), "--clean"])
    assert not stale.exists()
    assert (tmp_path / "models" / "pets.py").exists()


def test_models_missing_package_exits_one(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    with mock.patch.dict(sys.modules, {"pyoas.models": None}):
        result = runner.invoke(app, ["models", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "pip install pyoas" in result.output


# ---------------------------------------------------------------------------
# fastapi
# ---------------------------------------------------------------------------


def test_fastapi_writes_router_files(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["fastapi", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    assert (tmp_path / "routers" / "pets.py").exists()


def test_fastapi_tags_filter_restricts_output(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "multi_tag.yaml")
    result = runner.invoke(app, ["fastapi", "--config", str(cfg), "--tags", "orders"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "routers" / "orders.py").exists()
    assert not (tmp_path / "routers" / "users.py").exists()


def test_fastapi_clean_removes_stale_files(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    runner.invoke(app, ["fastapi", "--config", str(cfg)])
    stale = tmp_path / "routers" / "stale.py"
    stale.write_text("# stale")
    runner.invoke(app, ["fastapi", "--config", str(cfg), "--clean"])
    assert not stale.exists()
    assert (tmp_path / "routers" / "pets.py").exists()


def test_fastapi_missing_extra_exits_one(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    with mock.patch.dict(sys.modules, {"pyoas.fastapi": None}):
        result = runner.invoke(app, ["fastapi", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "pyoas[fastapi]" in result.output


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


def test_generate_writes_models_and_routers(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["generate", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "models" / "pets.py").exists()
    assert (tmp_path / "routers" / "pets.py").exists()


def test_generate_summary_table_contains_separator_lines(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["generate", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "─" in result.output
    assert "models" in result.output
    assert "routers" in result.output


def test_generate_summary_table_with_services(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        services={
            "generate": True,
            "output": str(tmp_path / "services"),
            "import_path": "app.services",
            "overwrite": True,
        },
    )
    result = runner.invoke(app, ["generate", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "services" in result.output
    assert "─" in result.output


def test_generate_with_skills_writes_skill_files(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        skills={
            "generate": True,
            "output": str(tmp_path / "skills"),
            "overwrite": True,
        },
    )
    result = runner.invoke(app, ["generate", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "skills" in result.output
    assert (tmp_path / "skills" / "implement-tests.md").exists()


def test_generate_skills_import_error_continues_not_fails(tmp_path: Path) -> None:
    """generate keeps exit_code 0 when pyoas[claude] is missing — it wraps skills in try/except."""
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        skills={
            "generate": True,
            "output": str(tmp_path / "skills"),
            "overwrite": True,
        },
    )
    with mock.patch.dict(sys.modules, {"pyoas.claude": None}):
        result = runner.invoke(app, ["generate", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "pyoas[claude]" in result.output


def test_generate_missing_models_and_fastapi_exits_one(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    with mock.patch.dict(sys.modules, {"pyoas.models": None, "pyoas.fastapi": None}):
        result = runner.invoke(app, ["generate", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "pip install pyoas" in result.output


# ---------------------------------------------------------------------------
# diff — new coverage (core diff tests already in test_config.py)
# ---------------------------------------------------------------------------


def test_diff_detects_service_drift(tmp_path: Path) -> None:
    """diff exits 1 and reports [missing] when service files haven't been scaffolded."""
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        services={
            "generate": True,
            "output": str(tmp_path / "services"),
            "import_path": "app.services",
        },
    )
    result = runner.invoke(app, ["diff", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "[missing]" in result.output


# ---------------------------------------------------------------------------
# scaffold dependencies
# ---------------------------------------------------------------------------


def test_scaffold_dependencies_writes_auth_file(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "secured.yaml",
        dependencies={
            "generate": True,
            "output": str(tmp_path / "deps"),
            "overwrite": True,
        },
    )
    result = runner.invoke(app, ["scaffold", "dependencies", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    assert (tmp_path / "deps" / "auth.py").exists()


def test_scaffold_dependencies_skips_existing_when_no_overwrite(
    tmp_path: Path,
) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "secured.yaml",
        dependencies={
            "generate": True,
            "output": str(tmp_path / "deps"),
            "overwrite": False,
        },
    )
    # First run: writes the file
    runner.invoke(app, ["scaffold", "dependencies", "--config", str(cfg)])
    assert (tmp_path / "deps" / "auth.py").exists()
    original = (tmp_path / "deps" / "auth.py").read_text()

    # Second run: file exists, overwrite=False → skipped
    result = runner.invoke(app, ["scaffold", "dependencies", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "skipped" in result.output
    assert (tmp_path / "deps" / "auth.py").read_text() == original


def test_scaffold_dependencies_warns_when_no_security(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        dependencies={
            "generate": True,
            "output": str(tmp_path / "deps"),
        },
    )
    result = runner.invoke(app, ["scaffold", "dependencies", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "No secured operations" in result.output


def test_scaffold_dependencies_missing_extra_exits_one(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    with mock.patch.dict(sys.modules, {"pyoas.fastapi": None}):
        result = runner.invoke(app, ["scaffold", "dependencies", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "pyoas[fastapi]" in result.output


# ---------------------------------------------------------------------------
# scaffold services
# ---------------------------------------------------------------------------


def test_scaffold_services_writes_service_files(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        services={
            "generate": True,
            "output": str(tmp_path / "services"),
            "import_path": "app.services",
            "overwrite": True,
        },
    )
    result = runner.invoke(app, ["scaffold", "services", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    assert (tmp_path / "services" / "pets.py").exists()


def test_scaffold_services_warns_when_not_configured(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["scaffold", "services", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "not configured" in result.output


def test_scaffold_services_missing_extra_exits_one(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    with mock.patch.dict(sys.modules, {"pyoas.fastapi": None}):
        result = runner.invoke(app, ["scaffold", "services", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "pyoas[fastapi]" in result.output


# ---------------------------------------------------------------------------
# scaffold tests
# ---------------------------------------------------------------------------


def test_scaffold_tests_writes_test_files(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        tests={
            "generate": True,
            "output": str(tmp_path / "tests"),
            "overwrite": True,
        },
    )
    result = runner.invoke(app, ["scaffold", "tests", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    assert (tmp_path / "tests" / "test_pets.py").exists()


def test_scaffold_tests_with_services_writes_service_tests(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        tests={
            "generate": True,
            "output": str(tmp_path / "tests"),
            "overwrite": True,
        },
        services={
            "generate": True,
            "output": str(tmp_path / "services"),
            "import_path": "app.services",
        },
    )
    result = runner.invoke(app, ["scaffold", "tests", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "tests" / "test_pets_service.py").exists()


def test_scaffold_tests_missing_extra_exits_one(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    with mock.patch.dict(sys.modules, {"pyoas.fastapi": None}):
        result = runner.invoke(app, ["scaffold", "tests", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "pyoas[fastapi]" in result.output


# ---------------------------------------------------------------------------
# scaffold skills
# ---------------------------------------------------------------------------


def test_scaffold_skills_writes_skill_files(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        skills={
            "generate": True,
            "output": str(tmp_path / "skills"),
            "overwrite": True,
        },
    )
    result = runner.invoke(app, ["scaffold", "skills", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    assert (tmp_path / "skills" / "implement-tests.md").exists()


def test_scaffold_skills_writes_multiple_skill_files(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        skills={
            "generate": True,
            "output": str(tmp_path / "skills"),
            "overwrite": True,
        },
    )
    runner.invoke(app, ["scaffold", "skills", "--config", str(cfg)])
    assert (tmp_path / "skills" / "add-test-case.md").exists()
    assert (tmp_path / "skills" / "review-generated.md").exists()


def test_scaffold_skills_missing_extra_exits_one(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    with mock.patch.dict(sys.modules, {"pyoas.claude": None}):
        result = runner.invoke(app, ["scaffold", "skills", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "pyoas[claude]" in result.output


# ---------------------------------------------------------------------------
# generate — optional sub-generators
# ---------------------------------------------------------------------------


def test_generate_with_dependencies_shows_in_summary(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "secured.yaml",
        dependencies={
            "generate": True,
            "output": str(tmp_path / "deps"),
            "overwrite": True,
        },
    )
    result = runner.invoke(app, ["generate", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "dependencies" in result.output


def test_generate_with_tests_shows_in_summary(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        tests={
            "generate": True,
            "output": str(tmp_path / "tests"),
            "overwrite": True,
        },
    )
    result = runner.invoke(app, ["generate", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "tests" in result.output
    assert "service tests" in result.output


# ---------------------------------------------------------------------------
# diff — additional scenarios
# ---------------------------------------------------------------------------


def test_diff_missing_fastapi_exits_one(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    with mock.patch.dict(sys.modules, {"pyoas.fastapi": None}):
        result = runner.invoke(app, ["diff", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_diff_detects_removed_files(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    runner.invoke(app, ["generate", "--config", str(cfg)])
    stale = tmp_path / "routers" / "stale_router.py"
    stale.write_text("# stale")
    result = runner.invoke(app, ["diff", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "[removed]" in result.output


def test_diff_detects_test_drift(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        tests={"generate": True, "output": str(tmp_path / "tests")},
    )
    result = runner.invoke(app, ["diff", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "[missing]" in result.output


def test_diff_detects_dependency_drift(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "secured.yaml",
        dependencies={"generate": True, "output": str(tmp_path / "deps")},
    )
    result = runner.invoke(app, ["diff", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "[missing]" in result.output


def test_diff_service_drift_with_tag_filter(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        FIXTURES / "multi_tag.yaml",
        services={
            "generate": True,
            "output": str(tmp_path / "services"),
            "import_path": "app.services",
        },
    )
    result = runner.invoke(app, ["diff", "--config", str(cfg), "--tags", "users"])
    assert result.exit_code == 1
    assert "users" in result.output
    assert "orders" not in result.output


def test_diff_detects_missing_service_methods(tmp_path: Path) -> None:
    svc_dir = tmp_path / "services"
    svc_dir.mkdir()
    # A stub with only one method present; the spec has more operations
    (svc_dir / "pets.py").write_text(
        "class PetsService:\n    async def list_pets(self) -> None:\n        pass\n"
    )
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        services={
            "generate": True,
            "output": str(svc_dir),
            "import_path": "app.services",
        },
    )
    result = runner.invoke(app, ["diff", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "::" in result.output  # format: "path/file.py::missing_fn"


# ---------------------------------------------------------------------------
# --quiet / --verbose flags
# ---------------------------------------------------------------------------


def test_models_quiet_suppresses_progress_and_file_listing(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["models", "--config", str(cfg), "--quiet"])
    assert result.exit_code == 0, result.output
    assert "wrote" not in result.output
    assert "[models]" not in result.output
    assert (tmp_path / "models" / "pets.py").exists()


def test_models_verbose_shows_timing(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["models", "--config", str(cfg), "--verbose"])
    assert result.exit_code == 0, result.output
    assert "ms" in result.output


def test_fastapi_quiet_suppresses_output(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["fastapi", "--config", str(cfg), "--quiet"])
    assert result.exit_code == 0, result.output
    assert "wrote" not in result.output
    assert "[routers]" not in result.output
    assert (tmp_path / "routers" / "pets.py").exists()


def test_generate_quiet_suppresses_progress(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["generate", "--config", str(cfg), "--quiet"])
    assert result.exit_code == 0, result.output
    assert "[models]" not in result.output
    assert "[routers]" not in result.output
    assert (tmp_path / "models" / "pets.py").exists()
    assert (tmp_path / "routers" / "pets.py").exists()


def test_generate_verbose_shows_timing(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["generate", "--config", str(cfg), "--verbose"])
    assert result.exit_code == 0, result.output
    assert "ms" in result.output


# ---------------------------------------------------------------------------
# validate --json
# ---------------------------------------------------------------------------


def test_validate_json_valid_spec_emits_ok(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["validate", "--config", str(cfg), "--json"])
    assert result.exit_code == 0, result.output
    import json

    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["error"] is None


def test_validate_json_missing_spec_emits_error(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, tmp_path / "missing.yaml")
    result = runner.invoke(app, ["validate", "--config", str(cfg), "--json"])
    assert result.exit_code == 1
    import json

    data = json.loads(result.output)
    assert data["status"] == "error"
    assert data["error"] is not None


# ---------------------------------------------------------------------------
# Webhook warning
# ---------------------------------------------------------------------------


def test_models_emits_webhook_warning_when_disabled(tmp_path: Path) -> None:
    """pyoas models warns on stderr when spec has webhooks but webhooks.generate is false."""
    cfg = _write_config(tmp_path, FIXTURES / "webhooks_3.1.yaml")
    result = runner.invoke(app, ["models", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "webhooks" in result.output.lower()


def test_models_no_webhook_warning_when_enabled(tmp_path: Path) -> None:
    """pyoas models does NOT warn when webhooks.generate is true."""
    cfg = _write_config(
        tmp_path, FIXTURES / "webhooks_3.1.yaml", webhooks={"generate": True}
    )
    result = runner.invoke(app, ["models", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "not being generated" not in result.output


def test_init_config_contains_webhooks_section(tmp_path: Path) -> None:
    """pyoas init emits webhooks.generate: false in the starter config."""
    out = tmp_path / "pyoas.yaml"
    runner.invoke(
        app, ["init", str(FIXTURES / "petstore_3.0.yaml"), "--output", str(out)]
    )
    content = out.read_text()
    assert "webhooks:" in content
    assert "generate: false" in content


# ---------------------------------------------------------------------------
# drift
# ---------------------------------------------------------------------------


def test_drift_exits_zero_when_services_not_configured(tmp_path: Path) -> None:
    """drift exits 0 and prints info when services are not configured."""
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["drift", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "not configured" in result.output


def test_drift_exits_one_on_missing_service_file(tmp_path: Path) -> None:
    """drift exits 1 and shows [missing file] when service file doesn't exist."""
    (tmp_path / "services").mkdir()
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        services={
            "generate": True,
            "output": str(tmp_path / "services"),
            "import_path": "app.services",
        },
    )
    result = runner.invoke(app, ["drift", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "[missing file]" in result.output


def test_drift_exits_one_on_missing_method(tmp_path: Path) -> None:
    """drift exits 1 and shows [missing method] when a method is absent."""
    svc_dir = tmp_path / "services"
    svc_dir.mkdir()
    (svc_dir / "pets.py").write_text(
        "class PetsService:\n    async def list_pets(self) -> None:\n        pass\n"
    )
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        services={
            "generate": True,
            "output": str(svc_dir),
            "import_path": "app.services",
        },
    )
    result = runner.invoke(app, ["drift", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "[missing method]" in result.output


def test_drift_exits_zero_when_up_to_date(tmp_path: Path) -> None:
    """drift exits 0 when service files match the spec."""
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        services={
            "generate": True,
            "output": str(tmp_path / "services"),
            "import_path": "app.services",
        },
    )
    # Scaffold services first so they match the spec
    runner.invoke(app, ["scaffold", "services", "--config", str(cfg)])
    result = runner.invoke(app, ["drift", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "No drift" in result.output


def test_drift_tag_filter_restricts_check(tmp_path: Path) -> None:
    """drift --tags only checks the specified tag."""
    (tmp_path / "services").mkdir()
    cfg = _write_config(
        tmp_path,
        FIXTURES / "multi_tag.yaml",
        services={
            "generate": True,
            "output": str(tmp_path / "services"),
            "import_path": "app.services",
        },
    )
    result = runner.invoke(app, ["drift", "--config", str(cfg), "--tags", "users"])
    assert result.exit_code == 1
    assert "users" in result.output
    assert "orders" not in result.output


# ---------------------------------------------------------------------------
# scaffold webhooks
# ---------------------------------------------------------------------------


def test_scaffold_webhooks_exits_zero_when_enabled(tmp_path: Path) -> None:
    """scaffold webhooks prints mount instructions when webhooks.generate is true."""
    cfg = _write_config(
        tmp_path,
        FIXTURES / "webhooks_3.1.yaml",
        webhooks={"generate": True},
    )
    result = runner.invoke(app, ["scaffold", "webhooks", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "include_router" in result.output


def test_scaffold_webhooks_warns_when_not_configured(tmp_path: Path) -> None:
    """scaffold webhooks exits 0 with an informative message when not enabled."""
    cfg = _write_config(tmp_path, FIXTURES / "webhooks_3.1.yaml")
    result = runner.invoke(app, ["scaffold", "webhooks", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "not enabled" in result.output


def test_scaffold_webhooks_no_webhooks_in_spec(tmp_path: Path) -> None:
    """scaffold webhooks exits 0 with info when spec has no webhook operations."""
    cfg = _write_config(
        tmp_path,
        FIXTURES / "petstore_3.0.yaml",
        webhooks={"generate": True},
    )
    result = runner.invoke(app, ["scaffold", "webhooks", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "No webhook" in result.output


# ---------------------------------------------------------------------------
# generation cache (T3-E)
# ---------------------------------------------------------------------------


def test_models_skips_unchanged_tags_on_second_run(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    first = runner.invoke(app, ["models", "--config", str(cfg)])
    assert first.exit_code == 0, first.output

    second = runner.invoke(app, ["models", "--config", str(cfg)])
    assert second.exit_code == 0, second.output
    assert "unchanged, skipped" in second.output


def test_models_clean_bypasses_cache(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    runner.invoke(app, ["models", "--config", str(cfg)])

    second = runner.invoke(app, ["models", "--config", str(cfg), "--clean"])
    assert second.exit_code == 0, second.output
    assert "unchanged, skipped" not in second.output


def test_generate_skips_both_generators_on_second_run(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    first = runner.invoke(app, ["generate", "--config", str(cfg)])
    assert first.exit_code == 0, first.output

    second = runner.invoke(app, ["generate", "--config", str(cfg)])
    assert second.exit_code == 0, second.output
    assert "[models]" in second.output
    assert "[routers]" in second.output
    assert "unchanged, skipped" in second.output
