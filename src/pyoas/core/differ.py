"""Spec diffing and breaking-change classification for ``pyoas migrate``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pyoas.core.tags import HTTP_METHODS

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class OperationRef:
    method: str
    path: str
    operation_id: str | None


@dataclass
class FieldChange:
    field_path: str
    change_type: str  # type_changed | nullable_changed | required_added | required_removed | field_added | field_removed
    old_value: Any = None
    new_value: Any = None


@dataclass
class OperationChange:
    method: str
    path: str
    operation_id: str | None
    request_changes: list[FieldChange] = field(default_factory=list)
    response_changes: list[FieldChange] = field(default_factory=list)


@dataclass
class SchemaChange:
    schema_name: str
    changes: list[FieldChange] = field(default_factory=list)


@dataclass
class SpecDiff:
    added_operations: list[OperationRef] = field(default_factory=list)
    removed_operations: list[OperationRef] = field(default_factory=list)
    changed_operations: list[OperationChange] = field(default_factory=list)
    added_schemas: list[str] = field(default_factory=list)
    removed_schemas: list[str] = field(default_factory=list)
    changed_schemas: list[SchemaChange] = field(default_factory=list)


@dataclass
class MigrationIssue:
    severity: str  # "breaking" | "non_breaking"
    method: str | None
    path: str | None
    operation_id: str | None
    issue: str  # machine-readable key
    description: str


# ---------------------------------------------------------------------------
# Type ordering for widen/narrow detection
# ---------------------------------------------------------------------------

_TYPE_ORDER: dict[str, int] = {"boolean": 0, "integer": 1, "number": 2, "string": 3}


def _is_type_widened(old_type: str, new_type: str) -> bool:
    return _TYPE_ORDER.get(old_type, -1) < _TYPE_ORDER.get(new_type, -1)


def _is_type_narrowed(old_type: str, new_type: str) -> bool:
    return _TYPE_ORDER.get(old_type, -1) > _TYPE_ORDER.get(new_type, -1)


# ---------------------------------------------------------------------------
# Schema diffing helpers
# ---------------------------------------------------------------------------


def _diff_schema(
    old: Any,
    new: Any,
    field_path: str = "",
) -> list[FieldChange]:
    """Recursively diff two resolved schema dicts and return field changes."""
    changes: list[FieldChange] = []

    if old is None and new is None:
        return changes
    if old is None:
        changes.append(FieldChange(field_path, "field_added", None, new))
        return changes
    if new is None:
        changes.append(FieldChange(field_path, "field_removed", old, None))
        return changes

    if not isinstance(old, dict) or not isinstance(new, dict):
        return changes

    # Detect circular-ref stubs ($ref not expanded) and skip deep comparison
    if "$ref" in old or "$ref" in new:
        return changes

    # type change
    old_type = old.get("type")
    new_type = new.get("type")
    if old_type != new_type and old_type is not None and new_type is not None:
        changes.append(FieldChange(field_path, "type_changed", old_type, new_type))

    # nullable change (OAS 3.0 style)
    old_nullable = old.get("nullable", False)
    new_nullable = new.get("nullable", False)
    if old_nullable != new_nullable:
        changes.append(
            FieldChange(field_path, "nullable_changed", old_nullable, new_nullable)
        )

    # required field changes at this object level
    old_required = set(old.get("required") or [])
    new_required = set(new.get("required") or [])

    for req_field in sorted(new_required - old_required):
        sub_path = f"{field_path}.{req_field}" if field_path else req_field
        changes.append(FieldChange(sub_path, "required_added", False, True))

    for req_field in sorted(old_required - new_required):
        sub_path = f"{field_path}.{req_field}" if field_path else req_field
        changes.append(FieldChange(sub_path, "required_removed", True, False))

    # properties diff
    old_props = old.get("properties") or {}
    new_props = new.get("properties") or {}

    for prop_name in sorted(set(old_props) - set(new_props)):
        prop_path = f"{field_path}.{prop_name}" if field_path else prop_name
        changes.append(
            FieldChange(prop_path, "field_removed", old_props[prop_name], None)
        )

    for prop_name in sorted(set(new_props) - set(old_props)):
        prop_path = f"{field_path}.{prop_name}" if field_path else prop_name
        changes.append(
            FieldChange(prop_path, "field_added", None, new_props[prop_name])
        )

    for prop_name in sorted(set(old_props) & set(new_props)):
        prop_path = f"{field_path}.{prop_name}" if field_path else prop_name
        old_prop = old_props[prop_name]
        new_prop = new_props[prop_name]
        if isinstance(old_prop, dict) and isinstance(new_prop, dict):
            changes.extend(_diff_schema(old_prop, new_prop, prop_path))

    return changes


def _get_request_schema(operation: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the request body JSON schema from an operation."""
    content = (operation.get("requestBody") or {}).get("content") or {}
    if "application/json" in content:
        return content["application/json"].get("schema")
    if content:
        return next(iter(content.values())).get("schema")
    return None


def _get_response_schema(operation: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the first 2xx response JSON schema from an operation."""
    for code, resp_obj in (operation.get("responses") or {}).items():
        if str(code).startswith("2") and isinstance(resp_obj, dict):
            content = resp_obj.get("content") or {}
            if "application/json" in content:
                return content["application/json"].get("schema")
            if content:
                return next(iter(content.values())).get("schema")
    return None


def _build_op_index(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build ``{method:path -> operation_dict}`` index from a spec dict."""
    index: dict[str, dict[str, Any]] = {}
    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() in HTTP_METHODS and isinstance(operation, dict):
                index[f"{method.lower()}:{path}"] = operation
    return index


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diff_specs(old: dict[str, Any], new: dict[str, Any]) -> SpecDiff:
    """Compute a structured diff between two resolved OpenAPI specs."""
    diff = SpecDiff()

    old_ops = _build_op_index(old)
    new_ops = _build_op_index(new)
    old_keys = set(old_ops)
    new_keys = set(new_ops)

    for key in sorted(old_keys - new_keys):
        method, path = key.split(":", 1)
        op = old_ops[key]
        diff.removed_operations.append(
            OperationRef(method=method, path=path, operation_id=op.get("operationId"))
        )

    for key in sorted(new_keys - old_keys):
        method, path = key.split(":", 1)
        op = new_ops[key]
        diff.added_operations.append(
            OperationRef(method=method, path=path, operation_id=op.get("operationId"))
        )

    for key in sorted(old_keys & new_keys):
        method, path = key.split(":", 1)
        old_op = old_ops[key]
        new_op = new_ops[key]

        request_changes = _diff_schema(
            _get_request_schema(old_op), _get_request_schema(new_op)
        )
        response_changes = _diff_schema(
            _get_response_schema(old_op), _get_response_schema(new_op)
        )

        if request_changes or response_changes:
            diff.changed_operations.append(
                OperationChange(
                    method=method,
                    path=path,
                    operation_id=old_op.get("operationId"),
                    request_changes=request_changes,
                    response_changes=response_changes,
                )
            )

    old_schemas = (old.get("components") or {}).get("schemas") or {}
    new_schemas = (new.get("components") or {}).get("schemas") or {}

    diff.removed_schemas = sorted(set(old_schemas) - set(new_schemas))
    diff.added_schemas = sorted(set(new_schemas) - set(old_schemas))

    for name in sorted(set(old_schemas) & set(new_schemas)):
        schema_changes = _diff_schema(old_schemas[name], new_schemas[name], name)
        if schema_changes:
            diff.changed_schemas.append(
                SchemaChange(schema_name=name, changes=schema_changes)
            )

    return diff


def classify_changes(diff: SpecDiff) -> list[MigrationIssue]:
    """Classify all changes in *diff* as breaking or non-breaking."""
    issues: list[MigrationIssue] = []

    for op_ref in diff.removed_operations:
        issues.append(
            MigrationIssue(
                severity="breaking",
                method=op_ref.method.upper(),
                path=op_ref.path,
                operation_id=op_ref.operation_id,
                issue="operation_removed",
                description=f"Operation {op_ref.method.upper()} {op_ref.path} was removed",
            )
        )

    for op_ref in diff.added_operations:
        issues.append(
            MigrationIssue(
                severity="non_breaking",
                method=op_ref.method.upper(),
                path=op_ref.path,
                operation_id=op_ref.operation_id,
                issue="operation_added",
                description=f"Operation {op_ref.method.upper()} {op_ref.path} was added",
            )
        )

    for op_change in diff.changed_operations:
        method = op_change.method.upper()
        path = op_change.path
        op_id = op_change.operation_id

        for fc in op_change.request_changes:
            if fc.change_type == "required_removed":
                issues.append(
                    MigrationIssue(
                        severity="breaking",
                        method=method,
                        path=path,
                        operation_id=op_id,
                        issue="required_request_field_removed",
                        description=f"Required request field '{fc.field_path}' was removed",
                    )
                )
            elif fc.change_type == "required_added":
                issues.append(
                    MigrationIssue(
                        severity="breaking",
                        method=method,
                        path=path,
                        operation_id=op_id,
                        issue="new_required_request_field",
                        description=f"New required request field '{fc.field_path}' was added",
                    )
                )
            elif fc.change_type == "field_added":
                issues.append(
                    MigrationIssue(
                        severity="non_breaking",
                        method=method,
                        path=path,
                        operation_id=op_id,
                        issue="optional_request_field_added",
                        description=f"Optional request field '{fc.field_path}' was added",
                    )
                )

        for fc in op_change.response_changes:
            if fc.change_type == "type_changed":
                old_t = str(fc.old_value or "")
                new_t = str(fc.new_value or "")
                if _is_type_narrowed(old_t, new_t):
                    issues.append(
                        MigrationIssue(
                            severity="breaking",
                            method=method,
                            path=path,
                            operation_id=op_id,
                            issue="response_type_narrowed",
                            description=(
                                f"Response field '{fc.field_path}' type narrowed "
                                f"from '{fc.old_value}' to '{fc.new_value}'"
                            ),
                        )
                    )
                elif _is_type_widened(old_t, new_t):
                    issues.append(
                        MigrationIssue(
                            severity="non_breaking",
                            method=method,
                            path=path,
                            operation_id=op_id,
                            issue="response_type_widened",
                            description=(
                                f"Response field '{fc.field_path}' type widened "
                                f"from '{fc.old_value}' to '{fc.new_value}'"
                            ),
                        )
                    )
                else:
                    issues.append(
                        MigrationIssue(
                            severity="breaking",
                            method=method,
                            path=path,
                            operation_id=op_id,
                            issue="response_schema_type_changed",
                            description=(
                                f"Response field '{fc.field_path}' type changed "
                                f"from '{fc.old_value}' to '{fc.new_value}'"
                            ),
                        )
                    )
            elif fc.change_type == "nullable_changed":
                if fc.old_value is True and fc.new_value is False:
                    issues.append(
                        MigrationIssue(
                            severity="breaking",
                            method=method,
                            path=path,
                            operation_id=op_id,
                            issue="response_nullable_removed",
                            description=f"Response field '{fc.field_path}' is no longer nullable",
                        )
                    )
                elif fc.old_value is False and fc.new_value is True:
                    issues.append(
                        MigrationIssue(
                            severity="non_breaking",
                            method=method,
                            path=path,
                            operation_id=op_id,
                            issue="response_nullable_added",
                            description=f"Response field '{fc.field_path}' is now nullable",
                        )
                    )
            elif fc.change_type == "field_added":
                issues.append(
                    MigrationIssue(
                        severity="non_breaking",
                        method=method,
                        path=path,
                        operation_id=op_id,
                        issue="optional_response_field_added",
                        description=f"Response field '{fc.field_path}' was added",
                    )
                )
            elif fc.change_type == "field_removed":
                issues.append(
                    MigrationIssue(
                        severity="breaking",
                        method=method,
                        path=path,
                        operation_id=op_id,
                        issue="response_field_removed",
                        description=f"Response field '{fc.field_path}' was removed",
                    )
                )

    return issues
