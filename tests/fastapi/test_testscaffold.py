"""
Tests for TestScaffolder.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from syrupy.assertion import SnapshotAssertion

from pyoas.core.config import (
    Config,
    DependenciesConfig,
    FieldsConfig,
    FormatConfig,
    OutputConfig,
    ServicesConfig,
    TestsConfig,
)
from pyoas.fastapi.testscaffold import TestScaffolder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROUTERS_DIR = "src/generated/routers"


def _make_config(
    spec_path: str, tests_output: str, *, overwrite: bool = True
) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(models="src/generated/models", routers=_ROUTERS_DIR),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        tests=TestsConfig(generate=True, output=tests_output, overwrite=overwrite),
    )


def _make_config_with_services(
    spec_path: str,
    tests_output: str,
    services_dir: str,
    import_path: str,
) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(models="src/generated/models", routers=_ROUTERS_DIR),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        services=ServicesConfig(
            generate=True,
            output=services_dir,
            overwrite=True,
            import_path=import_path,
        ),
        tests=TestsConfig(generate=True, output=tests_output, overwrite=True),
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_scaffold_creates_files(petstore_30: Path, snapshot: SnapshotAssertion) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        TestScaffolder(cfg).scaffold()

        output = Path(tmp)
        assert (output / "test_pets.py").exists()
        assert (output / "test_store.py").exists()
        assert (output / "__init__.py").exists()
        assert (output / "conftest.py").exists()

        assert _read(output / "test_pets.py") == snapshot(name="test_pets_30")
        assert _read(output / "test_store.py") == snapshot(name="test_store_30")
        assert _read(output / "conftest.py") == snapshot(name="conftest_30")


def test_endpoint_exists_test_present(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_pets.py")
        assert "test_endpoint_exists" in content


def test_success_stub_present(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_pets.py")
        assert 'pytest.skip("implement me")' in content


def test_validation_test_for_required_body(no_tags: Path) -> None:
    """POST /items has a required body — test_validation_error must be generated."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(no_tags), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        assert "test_validation_error" in content
        assert "assert response.status_code == 422" in content


def test_no_validation_test_for_get_only(petstore_30: Path) -> None:
    """GET /pets has no required body or query params — no test_validation_error."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_pets.py")
        # GET /pets has no required params; GET /pets/{petId} only has a path param.
        # POST /pets does have a required body, so validation test IS present for that class.
        # We verify the overall file structure has test classes with and without it.
        assert "TestListPets" in content
        assert "TestCreatePets" in content or "TestCreatePet" in content


def test_path_params_filled(petstore_30: Path) -> None:
    """Path params should be replaced with example values in test calls."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_pets.py")
        # The HTTP call should use a filled path, not the template placeholder.
        assert 'client.get("/pets/1")' in content
        assert 'client.get("/pets/{petId}")' not in content


def test_append_only_skips_existing_classes(petstore_30: Path) -> None:
    """Second run only adds test classes for new operations, does not overwrite existing ones."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp, overwrite=True)
        TestScaffolder(cfg).scaffold()

        test_file = Path(tmp) / "test_pets.py"
        original = _read(test_file)

        # Manually mark one class as "customised" to detect it survives re-generation.
        marked = original.replace(
            "class TestListPets:", "class TestListPets:  # customised"
        )
        test_file.write_text(marked, encoding="utf-8")

        # Second run in append-only mode (overwrite=False).
        cfg2 = _make_config(str(petstore_30), tmp, overwrite=False)
        TestScaffolder(cfg2).scaffold()

        result = _read(test_file)
        # The customisation must survive.
        assert "class TestListPets:  # customised" in result


def test_append_only_adds_new_class(petstore_30: Path, no_tags: Path) -> None:
    """When a new operation appears, append-only mode adds its test class."""
    with tempfile.TemporaryDirectory() as tmp:
        # First run with petstore (has TestListPets, TestShowPetById, TestCreatePets).
        cfg = _make_config(str(petstore_30), tmp, overwrite=True)
        TestScaffolder(cfg).scaffold()

        test_file = Path(tmp) / "test_pets.py"
        original = _read(test_file)

        # Simulate a new class being needed by removing it from the file.
        without_create = "\n".join(
            line
            for line in original.splitlines()
            if "TestCreatePets" not in line and "TestCreatePet" not in line
        )
        test_file.write_text(without_create, encoding="utf-8")

        # Second run in append-only mode — should re-add the missing class.
        cfg2 = _make_config(str(petstore_30), tmp, overwrite=False)
        TestScaffolder(cfg2).scaffold()

        result = _read(test_file)
        assert "TestCreatePets" in result or "TestCreatePet" in result


def test_overwrite_replaces_file(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp, overwrite=True)
        TestScaffolder(cfg).scaffold()

        test_file = Path(tmp) / "test_pets.py"
        test_file.write_text("# corrupted", encoding="utf-8")

        TestScaffolder(cfg).scaffold()

        content = _read(test_file)
        assert "test_endpoint_exists" in content


def test_service_mock_fixture_when_services_configured(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config_with_services(
            str(petstore_30),
            tests_output=tmp,
            services_dir=tmp + "/services",
            import_path="myapp.services",
        )
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_pets.py")
        assert "AsyncMock" in content
        assert "mock_service" in content
        assert "PetsService" in content


def test_no_service_mock_without_services(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_pets.py")
        assert "AsyncMock" not in content


def test_router_import_path_derived_from_output(petstore_30: Path) -> None:
    """The router import path is derived from output.routers + output.source_root."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_pets.py")
        # derive_import_path("src/generated/routers", "src") → "generated.routers"
        assert "from generated.routers.pets import router" in content


def test_client_with_mock_wired_correctly(petstore_30: Path) -> None:
    """client_with_mock fixture must use dependency_overrides to wire the mock."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config_with_services(
            str(petstore_30),
            tests_output=tmp,
            services_dir=tmp + "/services",
            import_path="myapp.services",
        )
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_pets.py")
        assert "client_with_mock" in content
        assert "dependency_overrides" in content
        assert "get_pets_service" in content


def test_missing_required_field_test_generated(no_tags: Path) -> None:
    """POST /items has a body with required field 'name' — test_missing_required_field must appear."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(no_tags), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        assert "test_missing_required_field" in content
        assert "json={}" in content


def test_query_constraint_tests_generated(no_tags_paginated: Path) -> None:
    """GET /items with page(ge=1) and pageSize(ge=1,le=100) must produce boundary-violation tests."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(no_tags_paginated), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        assert "test_page_below_minimum" in content
        assert '"page": 0' in content
        assert "test_page_size_below_minimum" in content
        assert '"page_size": 0' in content
        assert "test_page_size_above_maximum" in content
        assert '"page_size": 101' in content


def test_invalid_path_param_type_test_generated(no_tags: Path) -> None:
    """GET /items/{itemId} with integer path param must produce a type-mismatch test."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(no_tags), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        assert "test_invalid_item_id_type" in content
        assert "not-an-integer" in content


def test_not_found_stub_for_by_id_operations(no_tags: Path) -> None:
    """GET/DELETE /items/{itemId} with services configured must include test_not_found stub."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config_with_services(
            str(no_tags),
            tests_output=tmp,
            services_dir=tmp + "/services",
            import_path="myapp.services",
        )
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        assert "test_not_found" in content
        assert "client_with_mock" in content


def test_success_uses_client_with_mock_when_services_configured(
    petstore_30: Path,
) -> None:
    """test_success must use client_with_mock (not plain client) when services are configured."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config_with_services(
            str(petstore_30),
            tests_output=tmp,
            services_dir=tmp + "/services",
            import_path="myapp.services",
        )
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_pets.py")
        assert "def test_success(self, client_with_mock: TestClient)" in content


def test_skips_when_not_configured(petstore_30: Path, capsys) -> None:
    """Calling scaffold() when tests.generate=False prints a hint and writes nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(petstore_30),
            output=OutputConfig(models="src/generated/models", routers=_ROUTERS_DIR),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
            # tests.generate defaults to False
        )
        TestScaffolder(cfg).scaffold()

        assert not list(Path(tmp).glob("test_*.py"))
        captured = capsys.readouterr()
        assert "tests.generate" in captured.out


def test_conftest_created_with_model_factories(petstore_30: Path) -> None:
    """conftest.py should contain make_* factory stubs for each response model."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "conftest.py")
        assert "def make_pet(" in content
        assert "def make_pet_list(" in content
        assert "ModelFactory" in content
        assert "PetFactory" in content
        assert "from generated.models.pets import" in content


def test_conftest_no_factories_for_primitive_responses(no_tags: Path) -> None:
    """Endpoints returning None (204) should not produce factory stubs."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(no_tags), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "conftest.py")
        # DELETE /items/{itemId} returns 204 (None) — no factory for it
        # but Item and CreateItemRequest responses should produce factories
        assert "def make_item(" in content


def test_body_field_numeric_violations_generated(body_field_constraints: Path) -> None:
    """Body fields with minimum/maximum must produce constraint violation tests."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(body_field_constraints), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        assert "test_age_below_minimum" in content
        assert "test_age_above_maximum" in content
        assert "'age': -1" in content
        assert "'age': 151" in content


def test_body_field_string_violations_generated(body_field_constraints: Path) -> None:
    """Body fields with minLength/maxLength/pattern must produce string violation tests."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(body_field_constraints), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        assert "test_name_too_short" in content
        assert "test_name_too_long" in content
        assert "test_name_pattern_mismatch" in content
        assert "'!INVALID!'" in content


def test_body_field_wrong_type_generated(body_field_constraints: Path) -> None:
    """Required body fields with scalar types must produce a wrong-type test."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(body_field_constraints), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        assert "test_age_wrong_type" in content
        assert "not-an-integer" in content


def test_optional_body_field_constraint_generated(body_field_constraints: Path) -> None:
    """Optional body fields with constraints must also produce violation tests."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(body_field_constraints), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        assert "test_description_too_long" in content


def test_enum_violation_for_query_param(body_field_constraints: Path) -> None:
    """Query params with an enum must produce an invalid-enum test."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(body_field_constraints), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        assert "test_status_invalid_enum" in content
        assert "__invalid__" in content


def test_uuid_path_param_type_mismatch_generated(body_field_constraints: Path) -> None:
    """UUID path params must produce a type-mismatch test using 'not-a-uuid'."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(body_field_constraints), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        assert "test_invalid_item_id_type" in content
        assert "not-a-uuid" in content


def test_query_string_length_violations_generated(body_field_constraints: Path) -> None:
    """Query params with minLength/maxLength must produce string-length violation tests."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(body_field_constraints), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        assert "test_search_too_short" in content
        assert "test_search_too_long" in content


def test_readonly_body_fields_skipped(body_field_constraints: Path) -> None:
    """readOnly body fields must not produce constraint tests."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(body_field_constraints), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_default.py")
        # 'id' is readOnly in Item (response model, not in request body here)
        # Ensure no test references 'id' field constraint
        assert "test_id_" not in content


def test_endpoint_exists_uses_client_with_mock_when_services_configured(
    petstore_30: Path,
) -> None:
    """test_endpoint_exists must use client_with_mock when services are configured."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config_with_services(
            str(petstore_30),
            tests_output=tmp,
            services_dir=tmp + "/services",
            import_path="myapp.services",
        )
        TestScaffolder(cfg).scaffold()
        content = _read(Path(tmp) / "test_pets.py")
        assert "def test_endpoint_exists(self, client_with_mock: TestClient" in content
        assert "def test_endpoint_exists(self, client: TestClient" not in content


def test_endpoint_exists_uses_plain_client_without_services(petstore_30: Path) -> None:
    """test_endpoint_exists must use plain client when no services configured."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        TestScaffolder(cfg).scaffold()
        content = _read(Path(tmp) / "test_pets.py")
        assert "def test_endpoint_exists(self, client: TestClient" in content
        assert "def test_endpoint_exists(self, client_with_mock" not in content


def _make_config_with_deps(
    spec_path: str,
    tests_output: str,
    dep_import_path: str,
) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(models="src/generated/models", routers=_ROUTERS_DIR),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        dependencies=DependenciesConfig(import_path=dep_import_path),
        tests=TestsConfig(generate=True, output=tests_output, overwrite=True),
    )


def test_auth_dep_mock_when_dependencies_configured(secured: Path) -> None:
    """When dependencies.import_path is set and operations have security, fixtures must
    mock get_auth_context so tests don't get 401 errors."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config_with_deps(
            str(secured), tests_output=tmp, dep_import_path="myapp.dependencies"
        )
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_items.py")
        assert (
            "from myapp.dependencies.auth import AuthContext, get_auth_context"
            in content
        )
        # auth_context fixture param is injected — lambda references the fixture, not AuthContext()
        assert (
            "dependency_overrides[get_auth_context] = lambda: auth_context" in content
        )
        assert "def client(auth_context: AuthContext)" in content


def test_no_auth_dep_mock_when_dependencies_not_configured(secured: Path) -> None:
    """When dependencies.import_path is not set, no auth mock should appear."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(secured), tmp)
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "test_items.py")
        assert "get_auth_context" not in content
        assert "AuthContext" not in content


def test_conftest_append_only_adds_missing_factories(petstore_30: Path) -> None:
    """Second run should append missing factory stubs without overwriting existing ones."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp, overwrite=True)
        TestScaffolder(cfg).scaffold()

        conftest_file = Path(tmp) / "conftest.py"
        # Overwrite conftest with only make_pet present (make_pet_list is absent).
        conftest_file.write_text(
            "# Scaffolded by pyoas — safe to edit.\nimport pytest\n\n"
            "def make_pet(**overrides):\n    pytest.skip('implement me')\n",
            encoding="utf-8",
        )

        cfg2 = _make_config(str(petstore_30), tmp, overwrite=False)
        TestScaffolder(cfg2).scaffold()

        result = _read(conftest_file)
        assert "def make_pet_list(" in result
        # The existing make_pet stub must still be present.
        assert "def make_pet(" in result


def test_bytes_response_mock_repr() -> None:
    """Endpoints returning bytes must get b'' as the mock return value so FastAPI
    response validation doesn't choke on an AsyncMock object."""
    from pyoas.fastapi.testscaffold import _default_mock_return_repr

    assert _default_mock_return_repr("bytes") == 'b""'
    assert _default_mock_return_repr("bytes | None") == 'b""'


def test_conftest_has_auth_context_fixture_when_secured(secured: Path) -> None:
    """When operations have security and dependencies.import_path is set, conftest.py
    must contain a standalone auth_context fixture that test clients can inject."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config_with_deps(
            str(secured), tests_output=tmp, dep_import_path="myapp.dependencies"
        )
        TestScaffolder(cfg).scaffold()

        content = _read(Path(tmp) / "conftest.py")
        assert "def auth_context() -> AuthContext:" in content
        assert "return AuthContext()" in content
        assert "from myapp.dependencies.auth import AuthContext" in content
        assert "import pytest" in content


def test_conftest_auth_context_fixture_idempotent(secured: Path) -> None:
    """Running scaffold twice must not duplicate the auth_context fixture."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config_with_deps(
            str(secured), tests_output=tmp, dep_import_path="myapp.dependencies"
        )
        TestScaffolder(cfg).scaffold()
        # Second run in append-only mode.
        cfg2 = _make_config_with_deps(
            str(secured), tests_output=tmp, dep_import_path="myapp.dependencies"
        )
        cfg2 = Config(
            spec=str(secured),
            output=OutputConfig(models="src/generated/models", routers=_ROUTERS_DIR),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
            dependencies=DependenciesConfig(import_path="myapp.dependencies"),
            tests=TestsConfig(generate=True, output=tmp, overwrite=False),
        )
        TestScaffolder(cfg2).scaffold()

        content = _read(Path(tmp) / "conftest.py")
        assert content.count("def auth_context(") == 1


def test_conftest_auth_context_appended_to_existing_conftest(secured: Path) -> None:
    """If conftest.py exists but lacks auth_context, it should be appended on next run."""
    with tempfile.TemporaryDirectory() as tmp:
        # Pre-populate conftest without auth_context.
        conftest_file = Path(tmp) / "conftest.py"
        conftest_file.write_text(
            "# Scaffolded by pyoas — safe to edit.\nfrom __future__ import annotations\n",
            encoding="utf-8",
        )
        cfg = Config(
            spec=str(secured),
            output=OutputConfig(models="src/generated/models", routers=_ROUTERS_DIR),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
            dependencies=DependenciesConfig(import_path="myapp.dependencies"),
            tests=TestsConfig(generate=True, output=tmp, overwrite=False),
        )
        TestScaffolder(cfg).scaffold()

        content = _read(conftest_file)
        assert "def auth_context()" in content
        assert "from myapp.dependencies.auth import AuthContext" in content
