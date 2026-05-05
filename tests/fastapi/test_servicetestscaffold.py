"""
Tests for ServiceTestScaffolder.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml
from syrupy.assertion import SnapshotAssertion

from pyoas.core.config import (
    Config,
    FieldsConfig,
    FormatConfig,
    OutputConfig,
    ServicesConfig,
    TestsConfig,
)
from pyoas.fastapi.servicetestscaffold import ServiceTestScaffolder, _success_test_name

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROUTERS_DIR = "src/generated/routers"


def _make_config(
    spec_path: str,
    tests_output: str,
    *,
    import_path: str = "myapp.services",
    overwrite: bool = True,
) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(models="src/generated/models", routers=_ROUTERS_DIR),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        services=ServicesConfig(
            generate=True,
            output="src/services",
            overwrite=False,
            import_path=import_path,
        ),
        tests=TestsConfig(
            generate=True,
            output=tests_output,
            overwrite=overwrite,
            not_found_exception="HTTPException(status_code=404, detail='Not found')",
        ),
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_spec(tmp: str, spec: dict) -> str:
    path = tmp + "/spec.yaml"
    Path(path).write_text(yaml.dump(spec), encoding="utf-8")
    return path


_PET_SCHEMA = {"$ref": "#/components/schemas/Pet"}
_PET_RESPONSE = {
    "description": "OK",
    "content": {"application/json": {"schema": _PET_SCHEMA}},
}
_PET_LIST_RESPONSE = {
    "description": "OK",
    "content": {
        "application/json": {"schema": {"type": "array", "items": _PET_SCHEMA}}
    },
}
_NO_CONTENT = {"description": "No content"}

_MINIMAL_SPEC: dict = {
    "openapi": "3.0.3",
    "info": {"title": "Test", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "tags": ["pets"],
                "operationId": "list_pets",
                "responses": {"200": _PET_LIST_RESPONSE},
            },
            "post": {
                "tags": ["pets"],
                "operationId": "create_pet",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": _PET_SCHEMA}},
                },
                "responses": {"201": _PET_RESPONSE},
            },
        },
        "/pets/{petId}": {
            "get": {
                "tags": ["pets"],
                "operationId": "get_pet",
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"200": _PET_RESPONSE},
            },
            "delete": {
                "tags": ["pets"],
                "operationId": "delete_pet",
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"204": _NO_CONTENT},
            },
        },
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            }
        }
    },
}

_SECURITY_SCHEMES = {"bearerAuth": {"type": "http", "scheme": "bearer"}}

_SECURED_SPEC: dict = {
    **_MINIMAL_SPEC,
    "security": [{"bearerAuth": []}],
    "components": {
        **_MINIMAL_SPEC["components"],
        "securitySchemes": _SECURITY_SCHEMES,
    },
}

_OP_SECURITY_SPEC: dict = {
    **_MINIMAL_SPEC,
    "paths": {
        "/pets": _MINIMAL_SPEC["paths"]["/pets"],
        "/pets/{petId}": {
            "get": {
                **_MINIMAL_SPEC["paths"]["/pets/{petId}"]["get"],
                "security": [{"bearerAuth": []}],
            },
            "delete": _MINIMAL_SPEC["paths"]["/pets/{petId}"]["delete"],
        },
    },
    "components": {
        **_MINIMAL_SPEC["components"],
        "securitySchemes": _SECURITY_SCHEMES,
    },
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_creates_service_test_files(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        ServiceTestScaffolder(cfg).scaffold()
        assert (Path(tmp) / "test_pets_service.py").exists()
        assert (Path(tmp) / "test_store_service.py").exists()


def test_skips_when_tests_not_configured(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(petstore_30),
            output=OutputConfig(models="src/generated/models", routers=_ROUTERS_DIR),
        )
        ServiceTestScaffolder(cfg).scaffold()
        assert not list(Path(tmp).glob("*_service.py"))


def test_skips_without_services(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(petstore_30),
            output=OutputConfig(models="src/generated/models", routers=_ROUTERS_DIR),
            tests=TestsConfig(generate=True, output=tmp),
            # services.import_path defaults to ""
        )
        ServiceTestScaffolder(cfg).scaffold()
        assert not list(Path(tmp).glob("*_service.py"))


def test_service_fixture_present(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        ServiceTestScaffolder(cfg).scaffold()
        content = _read(Path(tmp) / "test_pets_service.py")
        assert "def service()" in content
        assert "PetsService" in content


def test_success_stub_present(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        ServiceTestScaffolder(cfg).scaffold()
        content = _read(Path(tmp) / "test_pets_service.py")
        assert "test_returns_pet_list" in content  # list_pets
        assert "test_returns_pet" in content  # get_pet_by_id


def test_not_found_stub_for_by_id_get(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        ServiceTestScaffolder(cfg).scaffold()
        content = _read(Path(tmp) / "test_pets_service.py")
        assert "test_raises_not_found_when_missing" in content


def test_no_not_found_for_list_endpoint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = _write_spec(tmp, _MINIMAL_SPEC)
        cfg = _make_config(spec_path, tmp + "/tests")
        ServiceTestScaffolder(cfg).scaffold()
        content = _read(Path(tmp) / "tests" / "test_pets_service.py")
        # list_pets (no id param) should not have not_found stub
        assert "class TestListPetsService" in content
        list_class = content.split("class TestListPetsService")[1].split("\nclass ")[0]
        assert "test_raises_not_found_when_missing" not in list_class


def test_delete_uses_deletes_resource_name() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = _write_spec(tmp, _MINIMAL_SPEC)
        cfg = _make_config(spec_path, tmp + "/tests")
        ServiceTestScaffolder(cfg).scaffold()
        content = _read(Path(tmp) / "tests" / "test_pets_service.py")
        assert "test_deletes_resource" in content


def test_post_uses_creates_resource_name() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = _write_spec(tmp, _MINIMAL_SPEC)
        cfg = _make_config(spec_path, tmp + "/tests")
        ServiceTestScaffolder(cfg).scaffold()
        content = _read(Path(tmp) / "tests" / "test_pets_service.py")
        assert "test_creates_resource" in content


def test_no_security_stubs_without_security() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = _write_spec(tmp, _MINIMAL_SPEC)
        cfg = _make_config(spec_path, tmp + "/tests")
        ServiceTestScaffolder(cfg).scaffold()
        content = _read(Path(tmp) / "tests" / "test_pets_service.py")
        assert "test_raises_unauthorized" not in content
        assert "test_raises_forbidden" not in content


def test_security_stubs_with_global_security() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = _write_spec(tmp, _SECURED_SPEC)
        cfg = _make_config(spec_path, tmp + "/tests")
        ServiceTestScaffolder(cfg).scaffold()
        content = _read(Path(tmp) / "tests" / "test_pets_service.py")
        assert "test_raises_unauthorized_when_unauthenticated" in content


def test_forbidden_stub_only_for_id_operations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = _write_spec(tmp, _SECURED_SPEC)
        cfg = _make_config(spec_path, tmp + "/tests")
        ServiceTestScaffolder(cfg).scaffold()
        content = _read(Path(tmp) / "tests" / "test_pets_service.py")
        # by-ID operations (get_pet, delete_pet) should have forbidden stub
        assert "test_raises_forbidden_when_not_owner" in content
        # list_pets (no id param) should NOT have forbidden stub
        list_class = content.split("class TestListPetsService")[1].split("\nclass ")[0]
        assert "test_raises_forbidden_when_not_owner" not in list_class


def test_security_stubs_with_operation_level_security() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = _write_spec(tmp, _OP_SECURITY_SPEC)
        cfg = _make_config(spec_path, tmp + "/tests")
        ServiceTestScaffolder(cfg).scaffold()
        content = _read(Path(tmp) / "tests" / "test_pets_service.py")
        # get_pet has explicit security → unauthorized stub
        get_class = content.split("class TestGetPetService")[1].split("\nclass ")[0]
        assert "test_raises_unauthorized_when_unauthenticated" in get_class
        # delete_pet has no explicit security → no unauthorized stub
        del_class = content.split("class TestDeletePetService")[1].split("\nclass ")[0]
        assert "test_raises_unauthorized_when_unauthenticated" not in del_class


def test_append_only_skips_existing_classes(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp, overwrite=True)
        ServiceTestScaffolder(cfg).scaffold()
        test_file = Path(tmp) / "test_pets_service.py"
        marked = _read(test_file).replace(
            "class TestListPetsService:", "class TestListPetsService:  # customised"
        )
        test_file.write_text(marked, encoding="utf-8")

        cfg2 = _make_config(str(petstore_30), tmp, overwrite=False)
        ServiceTestScaffolder(cfg2).scaffold()
        assert "class TestListPetsService:  # customised" in _read(test_file)


def test_snapshot(petstore_30: Path, snapshot: SnapshotAssertion) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        ServiceTestScaffolder(cfg).scaffold()
        assert _read(Path(tmp) / "test_pets_service.py") == snapshot(
            name="test_pets_service_30"
        )


# ---------------------------------------------------------------------------
# _success_test_name unit tests
# ---------------------------------------------------------------------------


def test_put_uses_updates_resource_name() -> None:
    assert _success_test_name("put", "Pet") == "test_updates_resource"


def test_patch_uses_updates_resource_name() -> None:
    assert _success_test_name("patch", "Pet") == "test_updates_resource"


def test_get_none_response_uses_returns_empty() -> None:
    assert _success_test_name("get", "None") == "test_returns_empty_response"


# ---------------------------------------------------------------------------
# tag_filter
# ---------------------------------------------------------------------------


def test_tag_filter_restricts_scaffolding(petstore_30: Path) -> None:
    """scaffold(tag_filter=…) only creates files for matching tags."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        ServiceTestScaffolder(cfg).scaffold(tag_filter=["pets"])
        assert (Path(tmp) / "test_pets_service.py").exists()
        assert not (Path(tmp) / "test_store_service.py").exists()


# ---------------------------------------------------------------------------
# append path — renders stubs for new operations
# ---------------------------------------------------------------------------


def test_append_new_operations_renders_stubs() -> None:
    """When a file exists but is missing a class, the scaffolder appends the stub."""
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = _write_spec(tmp, _MINIMAL_SPEC)
        tests_out = tmp + "/tests"
        cfg = _make_config(spec_path, tests_out, overwrite=False)

        # First scaffold: write all classes
        ServiceTestScaffolder(cfg).scaffold()
        test_file = Path(tests_out) / "test_pets_service.py"

        # Remove one class marker so it looks "missing" on the next run
        content = test_file.read_text()
        content = content.replace("class TestGetPetService:", "class __removed__:")
        test_file.write_text(content)

        # Second scaffold: should detect and append the missing class
        result = ServiceTestScaffolder(cfg).scaffold()
        final = test_file.read_text()
        assert "class TestGetPetService:" in final
        assert result.appended_items == 1
