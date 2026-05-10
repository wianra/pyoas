"""Tests for pyoas core differ — diff_specs(), classify_changes(), and the migrate CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from pyoas.core.cli import app
from pyoas.core.differ import (
    FieldChange,
    OperationChange,
    OperationRef,
    SpecDiff,
    classify_changes,
    diff_specs,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
runner = CliRunner()


# ---------------------------------------------------------------------------
# Spec-building helpers (no file I/O needed for unit tests)
# ---------------------------------------------------------------------------


def _spec(
    paths: dict[str, Any], schemas: dict[str, Any] | None = None
) -> dict[str, Any]:
    s: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "paths": paths,
    }
    if schemas:
        s["components"] = {"schemas": schemas}
    return s


def _get_op(response_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "operationId": "testOp",
        "responses": {
            "200": {
                "content": {"application/json": {"schema": response_schema}},
                "description": "ok",
            }
        },
    }


def _post_op(
    request_schema: dict[str, Any],
    response_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    op: dict[str, Any] = {
        "operationId": "testPost",
        "requestBody": {
            "content": {"application/json": {"schema": request_schema}},
            "required": True,
        },
        "responses": {"201": {"description": "created"}},
    }
    if response_schema:
        op["responses"]["201"]["content"] = {
            "application/json": {"schema": response_schema}
        }
    return op


# ---------------------------------------------------------------------------
# Unit tests — diff_specs()
# ---------------------------------------------------------------------------


def test_diff_detects_removed_operation() -> None:
    old = _spec({"/pets": {"get": _get_op({"type": "object"})}})
    new = _spec({})
    d = diff_specs(old, new)
    assert len(d.removed_operations) == 1
    assert d.removed_operations[0].path == "/pets"
    assert d.removed_operations[0].method == "get"


def test_diff_detects_added_operation() -> None:
    old = _spec({})
    new = _spec({"/pets/search": {"get": _get_op({"type": "object"})}})
    d = diff_specs(old, new)
    assert len(d.added_operations) == 1
    assert d.added_operations[0].path == "/pets/search"


def test_diff_no_change_returns_empty() -> None:
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    spec = _spec({"/pets": {"get": _get_op(schema)}})
    d = diff_specs(spec, spec)
    assert d.removed_operations == []
    assert d.added_operations == []
    assert d.changed_operations == []
    assert d.changed_schemas == []


def test_diff_detects_required_field_added_to_request() -> None:
    old_req = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": [],
    }
    new_req = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    old = _spec({"/items": {"post": _post_op(old_req)}})
    new = _spec({"/items": {"post": _post_op(new_req)}})
    d = diff_specs(old, new)
    assert len(d.changed_operations) == 1
    assert any(
        fc.change_type == "required_added" and "name" in fc.field_path
        for fc in d.changed_operations[0].request_changes
    )


def test_diff_detects_required_field_removed_from_request() -> None:
    old_req = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    new_req = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": [],
    }
    old = _spec({"/items": {"post": _post_op(old_req)}})
    new = _spec({"/items": {"post": _post_op(new_req)}})
    d = diff_specs(old, new)
    assert any(
        fc.change_type == "required_removed" and "name" in fc.field_path
        for fc in d.changed_operations[0].request_changes
    )


def test_diff_detects_response_field_added() -> None:
    old_resp = {"type": "object", "properties": {"id": {"type": "integer"}}}
    new_resp = {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "breed": {"type": "string"}},
    }
    old = _spec({"/pets/{id}": {"get": _get_op(old_resp)}})
    new = _spec({"/pets/{id}": {"get": _get_op(new_resp)}})
    d = diff_specs(old, new)
    assert any(
        fc.change_type == "field_added" and "breed" in fc.field_path
        for fc in d.changed_operations[0].response_changes
    )


def test_diff_detects_type_changed() -> None:
    old_resp = {"type": "object", "properties": {"count": {"type": "number"}}}
    new_resp = {"type": "object", "properties": {"count": {"type": "integer"}}}
    old = _spec({"/stats": {"get": _get_op(old_resp)}})
    new = _spec({"/stats": {"get": _get_op(new_resp)}})
    d = diff_specs(old, new)
    assert any(
        fc.change_type == "type_changed"
        and fc.old_value == "number"
        and fc.new_value == "integer"
        for fc in d.changed_operations[0].response_changes
    )


def test_diff_detects_nullable_changed() -> None:
    old_resp = {
        "type": "object",
        "properties": {"tag": {"type": "string", "nullable": True}},
    }
    new_resp = {"type": "object", "properties": {"tag": {"type": "string"}}}
    old = _spec({"/pets": {"get": _get_op(old_resp)}})
    new = _spec({"/pets": {"get": _get_op(new_resp)}})
    d = diff_specs(old, new)
    assert any(
        fc.change_type == "nullable_changed"
        and fc.old_value is True
        and fc.new_value is False
        for fc in d.changed_operations[0].response_changes
    )


# ---------------------------------------------------------------------------
# Unit tests — classify_changes()
# ---------------------------------------------------------------------------


def test_classify_operation_removed_is_breaking() -> None:
    diff = SpecDiff(
        removed_operations=[OperationRef("delete", "/pets/{id}", "deletePet")]
    )
    issues = classify_changes(diff)
    assert any(
        i.issue == "operation_removed" and i.severity == "breaking" for i in issues
    )


def test_classify_operation_added_is_non_breaking() -> None:
    diff = SpecDiff(
        added_operations=[OperationRef("get", "/pets/search", "searchPets")]
    )
    issues = classify_changes(diff)
    assert any(
        i.issue == "operation_added" and i.severity == "non_breaking" for i in issues
    )


def test_classify_required_request_field_removed_is_breaking() -> None:
    op_change = OperationChange(
        "post",
        "/items",
        "createItem",
        request_changes=[FieldChange("name", "required_removed", True, False)],
        response_changes=[],
    )
    diff = SpecDiff(changed_operations=[op_change])
    issues = classify_changes(diff)
    assert any(
        i.issue == "required_request_field_removed" and i.severity == "breaking"
        for i in issues
    )


def test_classify_new_required_request_field_is_breaking() -> None:
    op_change = OperationChange(
        "post",
        "/items",
        "createItem",
        request_changes=[FieldChange("category", "required_added", False, True)],
        response_changes=[],
    )
    diff = SpecDiff(changed_operations=[op_change])
    issues = classify_changes(diff)
    assert any(
        i.issue == "new_required_request_field" and i.severity == "breaking"
        for i in issues
    )


def test_classify_response_type_narrowed_is_breaking() -> None:
    op_change = OperationChange(
        "get",
        "/stats",
        "getStats",
        request_changes=[],
        response_changes=[FieldChange("count", "type_changed", "number", "integer")],
    )
    diff = SpecDiff(changed_operations=[op_change])
    issues = classify_changes(diff)
    assert any(
        i.issue == "response_type_narrowed" and i.severity == "breaking" for i in issues
    )


def test_classify_response_type_widened_is_non_breaking() -> None:
    op_change = OperationChange(
        "get",
        "/stats",
        "getStats",
        request_changes=[],
        response_changes=[FieldChange("count", "type_changed", "integer", "number")],
    )
    diff = SpecDiff(changed_operations=[op_change])
    issues = classify_changes(diff)
    assert any(
        i.issue == "response_type_widened" and i.severity == "non_breaking"
        for i in issues
    )


def test_classify_response_nullable_removed_is_breaking() -> None:
    op_change = OperationChange(
        "get",
        "/pets",
        "listPets",
        request_changes=[],
        response_changes=[FieldChange("tag", "nullable_changed", True, False)],
    )
    diff = SpecDiff(changed_operations=[op_change])
    issues = classify_changes(diff)
    assert any(
        i.issue == "response_nullable_removed" and i.severity == "breaking"
        for i in issues
    )


def test_classify_response_nullable_added_is_non_breaking() -> None:
    op_change = OperationChange(
        "get",
        "/pets",
        "listPets",
        request_changes=[],
        response_changes=[FieldChange("tag", "nullable_changed", False, True)],
    )
    diff = SpecDiff(changed_operations=[op_change])
    issues = classify_changes(diff)
    assert any(
        i.issue == "response_nullable_added" and i.severity == "non_breaking"
        for i in issues
    )


def test_classify_optional_request_field_added_is_non_breaking() -> None:
    op_change = OperationChange(
        "post",
        "/items",
        "createItem",
        request_changes=[FieldChange("color", "field_added", None, {"type": "string"})],
        response_changes=[],
    )
    diff = SpecDiff(changed_operations=[op_change])
    issues = classify_changes(diff)
    assert any(
        i.issue == "optional_request_field_added" and i.severity == "non_breaking"
        for i in issues
    )


def test_classify_optional_response_field_added_is_non_breaking() -> None:
    op_change = OperationChange(
        "get",
        "/pets",
        "listPets",
        request_changes=[],
        response_changes=[
            FieldChange("breed", "field_added", None, {"type": "string"})
        ],
    )
    diff = SpecDiff(changed_operations=[op_change])
    issues = classify_changes(diff)
    assert any(
        i.issue == "optional_response_field_added" and i.severity == "non_breaking"
        for i in issues
    )


def test_classify_description_change_produces_no_issues() -> None:
    old = _spec(
        {
            "/pets": {
                "get": {
                    "operationId": "listPets",
                    "summary": "List pets",
                    "responses": {"200": {"description": "old description"}},
                }
            }
        }
    )
    new = _spec(
        {
            "/pets": {
                "get": {
                    "operationId": "listPets",
                    "summary": "List all pets",
                    "responses": {"200": {"description": "new description"}},
                }
            }
        }
    )
    d = diff_specs(old, new)
    issues = classify_changes(d)
    assert issues == []


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_migrate_no_changes_exits_zero() -> None:
    spec = str(FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["migrate", spec, spec])
    assert result.exit_code == 0


def test_migrate_breaking_changes_exits_one() -> None:
    old = str(FIXTURES / "petstore_3.0.yaml")
    new = str(FIXTURES / "petstore_migrate_v2.yaml")
    result = runner.invoke(app, ["migrate", old, new])
    assert result.exit_code == 1


def test_migrate_text_output_shows_breaking_label() -> None:
    old = str(FIXTURES / "petstore_3.0.yaml")
    new = str(FIXTURES / "petstore_migrate_v2.yaml")
    result = runner.invoke(app, ["migrate", old, new])
    assert "[BREAKING]" in result.output


def test_migrate_json_output_structure() -> None:
    spec = str(FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["migrate", "--json", spec, spec])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "breaking" in data
    assert "non_breaking" in data
    assert "summary" in data
    assert data["summary"]["breaking"] == 0


def test_migrate_json_breaking_exits_one_and_summary_count() -> None:
    old = str(FIXTURES / "petstore_3.0.yaml")
    new = str(FIXTURES / "petstore_migrate_v2.yaml")
    result = runner.invoke(app, ["migrate", "--json", old, new])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["summary"]["breaking"] > 0


def test_migrate_breaking_only_suppresses_non_breaking() -> None:
    old = str(FIXTURES / "petstore_3.0.yaml")
    new = str(FIXTURES / "petstore_migrate_v2.yaml")
    result = runner.invoke(app, ["migrate", "--breaking-only", old, new])
    assert "[NON-BREAKING]" not in result.output


def test_migrate_missing_spec_exits_nonzero(tmp_path: Path) -> None:
    spec = str(FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["migrate", spec, str(tmp_path / "nonexistent.yaml")])
    assert result.exit_code != 0
