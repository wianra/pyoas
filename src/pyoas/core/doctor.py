"""Pre-flight diagnostic checks for pyoas.

run_doctor_checks() inspects a raw (unresolved) OpenAPI spec and a Config
object and returns a list of DoctorIssue findings without writing any files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pyoas.core.tags import HTTP_METHODS
from pyoas.core.utils import tag_to_dirname


@dataclass
class DoctorIssue:
    """A single diagnostic finding from run_doctor_checks."""

    level: str  # "error" | "warning"
    check: str  # short machine name, e.g. "duplicate_operation_id"
    message: str
    location: str  # e.g. "GET /pets" or "components.schemas.Dog"


def run_doctor_checks(spec_raw: dict[str, Any], cfg: Any) -> list[DoctorIssue]:
    """Run all pre-flight checks against *spec_raw* and *cfg*.

    Returns a list of DoctorIssue objects (errors and warnings). Empty list
    means no issues were found.
    """
    issues: list[DoctorIssue] = []

    issues.extend(_check_operations(spec_raw))
    issues.extend(_check_schemas(spec_raw))
    issues.extend(_check_services_import_path(cfg))

    return issues


# ---------------------------------------------------------------------------
# Operation-level checks
# ---------------------------------------------------------------------------


def _check_operations(spec_raw: dict[str, Any]) -> list[DoctorIssue]:
    """Check 1 (missing_operation_id), 2 (duplicate_operation_id), 3 (tag_collision)."""
    issues: list[DoctorIssue] = []
    op_id_counts: dict[str, int] = {}
    tag_to_original: dict[str, list[str]] = {}  # dirname -> [original_tag, ...]

    for path, path_item in (spec_raw.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue

            location = f"{method.upper()} {path}"
            op_id = operation.get("operationId")

            # Check 1: missing operationId
            if not op_id:
                issues.append(
                    DoctorIssue(
                        level="warning",
                        check="missing_operation_id",
                        message="operationId is missing",
                        location=location,
                    )
                )
            else:
                # Check 2: duplicate operationId
                op_id_counts[op_id] = op_id_counts.get(op_id, 0) + 1

            # Collect tags for check 3
            for tag in operation.get("tags") or []:
                dirname = tag_to_dirname(tag)
                tag_to_original.setdefault(dirname, [])
                if tag not in tag_to_original[dirname]:
                    tag_to_original[dirname].append(tag)

    # Emit duplicate operationId errors
    for op_id, count in op_id_counts.items():
        if count > 1:
            issues.append(
                DoctorIssue(
                    level="error",
                    check="duplicate_operation_id",
                    message=f"operationId '{op_id}' used {count} time(s)",
                    location=f"operationId: {op_id}",
                )
            )

    # Check 3: tag name collision
    for dirname, originals in tag_to_original.items():
        if len(originals) > 1:
            quoted = " and ".join(f"'{t}'" for t in originals)
            issues.append(
                DoctorIssue(
                    level="error",
                    check="tag_collision",
                    message=f"{quoted} both normalize to '{dirname}'",
                    location=f"tags: {', '.join(originals)}",
                )
            )

    return issues


# ---------------------------------------------------------------------------
# Schema-level checks
# ---------------------------------------------------------------------------


def _check_schemas(spec_raw: dict[str, Any]) -> list[DoctorIssue]:
    """Check 4 (ambiguous_schema) and Check 5 (unresolvable_ref)."""
    issues: list[DoctorIssue] = []
    schemas = (spec_raw.get("components") or {}).get("schemas") or {}
    schema_names = set(schemas.keys())

    for name, schema in schemas.items():
        if not isinstance(schema, dict):
            continue

        location = f"components.schemas.{name}"

        # Check 4: ambiguous schema
        has_type = "type" in schema
        has_ref = "$ref" in schema
        has_composition = any(k in schema for k in ("allOf", "anyOf", "oneOf"))
        has_enum = "enum" in schema
        if not (has_type or has_ref or has_composition or has_enum):
            issues.append(
                DoctorIssue(
                    level="warning",
                    check="ambiguous_schema",
                    message="schema has no type, $ref, or composition keyword — will render as Any",
                    location=location,
                )
            )

        # Check 5: unresolvable $ref chains within this schema
        for ref in _collect_local_refs(schema):
            ref_name = ref.split("/")[-1]
            if ref_name not in schema_names:
                issues.append(
                    DoctorIssue(
                        level="error",
                        check="unresolvable_ref",
                        message=f"$ref '{ref}' refers to a schema that does not exist",
                        location=location,
                    )
                )

    return issues


def _collect_local_refs(obj: Any) -> list[str]:
    """Recursively collect all '#/components/schemas/...' $ref values from obj."""
    refs: list[str] = []
    if isinstance(obj, dict):
        ref = obj.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            refs.append(ref)
        for v in obj.values():
            refs.extend(_collect_local_refs(v))
    elif isinstance(obj, list):
        for item in obj:
            refs.extend(_collect_local_refs(item))
    return refs


# ---------------------------------------------------------------------------
# Config-level checks
# ---------------------------------------------------------------------------


def _check_services_import_path(cfg: Any) -> list[DoctorIssue]:
    """Check 6: services.import_path points to a non-existent module."""
    import importlib.util

    issues: list[DoctorIssue] = []
    import_path = getattr(getattr(cfg, "services", None), "import_path", None) or ""
    try:
        found = importlib.util.find_spec(import_path) if import_path else True
    except (ModuleNotFoundError, ValueError):
        found = None

    if import_path and not found:
        issues.append(
            DoctorIssue(
                level="warning",
                check="services_import_path",
                message=(
                    f"services.import_path '{import_path}' could not be found on sys.path"
                ),
                location=f"services.import_path: {import_path}",
            )
        )
    return issues
