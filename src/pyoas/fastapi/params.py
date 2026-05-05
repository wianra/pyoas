"""
Parameter handling for FastAPI router generation.

Converts OpenAPI path / query / header / cookie / body parameter objects into
typed Python function parameter definitions.
"""

from __future__ import annotations

import re
from typing import Any

from pyoas.core.analysis import CONSTRAINT_ARGS, inline_schema_name
from pyoas.core.utils import to_snake_case
from pyoas.models.types import schema_to_python_type

# Subset of FastAPI constraint keys that represent numeric boundaries (used for test generation).
_NUMERIC_BOUNDARY_KEYS: frozenset[str] = frozenset({"ge", "gt", "le", "lt"})

# OpenAPI parameter location → FastAPI annotation class name.
_LOCATION_CLASS: dict[str, str] = {
    "query": "Query",
    "path": "Path",
    "header": "Header",
    "cookie": "Cookie",
}


def _annotated_base_type(py_type: str) -> str:
    """Strip ``Annotated[T, ...]`` wrapper and return ``T``, or return *py_type* unchanged."""
    if not py_type.startswith("Annotated["):
        return py_type
    inner = py_type[len("Annotated[") :]
    depth = 0
    for i, ch in enumerate(inner):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            return inner[:i].strip()
    return inner.strip()


def extract_numeric_constraints(schema: dict[str, Any]) -> dict[str, Any]:
    """Return {ge, gt, le, lt} boundary constraints from an OpenAPI schema.

    Used by the test scaffolder to generate boundary-violation test cases.
    Only numeric constraints are returned; string/array constraints are ignored.
    """
    result: dict[str, Any] = {}
    for oapi_key, fa_key in CONSTRAINT_ARGS.items():
        if fa_key not in _NUMERIC_BOUNDARY_KEYS:
            continue
        if oapi_key not in schema:
            continue
        val = schema[oapi_key]
        # OAS 3.0 boolean form: exclusiveMinimum/exclusiveMaximum are flags, not values.
        if oapi_key == "exclusiveMinimum" and isinstance(val, bool):
            if val and "minimum" in schema:
                result["gt"] = schema["minimum"]
        elif oapi_key == "exclusiveMaximum" and isinstance(val, bool):
            if val and "maximum" in schema:
                result["lt"] = schema["maximum"]
        else:
            result[fa_key] = val
    return result


def extract_string_constraints(schema: dict[str, Any]) -> dict[str, Any]:
    """Return {min_length, max_length, pattern} string constraints from an OpenAPI schema.

    Used by the test scaffolder to generate string-violation test cases.
    """
    result: dict[str, Any] = {}
    if "minLength" in schema:
        result["min_length"] = schema["minLength"]
    if "maxLength" in schema:
        result["max_length"] = schema["maxLength"]
    if "pattern" in schema:
        result["pattern"] = schema["pattern"]
    return result


def extract_enum_values(schema: dict[str, Any]) -> list[Any] | None:
    """Return the raw enum values list from a schema, or None if not an enum."""
    return schema.get("enum") or None


def _constraint_annotation(
    schema: dict[str, Any], location: str
) -> tuple[str, str] | None:
    """Return ``(fastapi_class, kwargs_str)`` if the schema has constraints, else None."""
    kwargs: dict[str, str] = {}
    for oapi_key, fa_key in CONSTRAINT_ARGS.items():
        if oapi_key not in schema:
            continue
        val = schema[oapi_key]
        # OAS 3.0 boolean form: exclusiveMinimum/exclusiveMaximum are flags, not values.
        if oapi_key == "exclusiveMinimum" and isinstance(val, bool):
            if val and "minimum" in schema:
                kwargs["gt"] = repr(schema["minimum"])
        elif oapi_key == "exclusiveMaximum" and isinstance(val, bool):
            if val and "maximum" in schema:
                kwargs["lt"] = repr(schema["maximum"])
        else:
            kwargs[fa_key] = f'"{val}"' if isinstance(val, str) else repr(val)
    if not kwargs or location not in _LOCATION_CLASS:
        return None
    fastapi_class = _LOCATION_CLASS[location]
    kwargs_str = ", ".join(f"{k}={v}" for k, v in kwargs.items())
    return fastapi_class, kwargs_str


def build_function_params(
    operation: dict[str, Any],
    *,
    raw_operation: dict[str, Any] | None = None,
    enums_as_literals: bool = True,
    generic_name_map: dict[str, str] | None = None,
    split_schema_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Return a list of parameter descriptors for the generated endpoint function.

    Each descriptor has::

        {
            "name":        str,   # Python identifier (snake_case)
            "python_type": str,   # e.g. "int", "str | None"
            "location":    str,   # "path" | "query" | "header" | "cookie" | "body"
            "required":    bool,
            "default":     Any,   # None if no default
            "description": str | None,
            "alias":       str,   # original parameter name
        }

    ``raw_operation`` is the *unresolved* operation object (with ``$ref`` strings
    intact).  When provided, ``$ref`` schemas resolve to their component name
    (e.g. ``"Pet"``) rather than ``dict[str, Any]``.

    ``split_schema_names`` is the set of schema names that have been split into
    Read/Write variants.  When a request body refs a split schema, the Write
    variant (``{Name}Write``) is used instead of the original name.
    """
    params: list[dict[str, Any]] = []

    # Build a name→raw-schema index from the unresolved parameters list.
    raw_params_by_name: dict[str, dict[str, Any]] = {}
    for rp in (raw_operation or {}).get("parameters") or []:
        if isinstance(rp, dict) and "name" in rp:
            raw_params_by_name[rp["name"]] = rp.get("schema") or {}

    for param in operation.get("parameters") or []:
        schema = param.get("schema") or {}
        location = param.get("in", "query")
        raw_schema = raw_params_by_name.get(param.get("name", ""))
        py_type = schema_to_python_type(
            schema,
            enums_as_literals=enums_as_literals,
            raw_schema=raw_schema,
            generic_name_map=generic_name_map,
        )

        required = param.get("required", False)
        if not required:
            py_type = f"{py_type} | None" if "None" not in py_type else py_type

        # Determine if this path param needs an alias due to camelCase → snake_case.
        original_name: str = param["name"]
        snake_name = to_snake_case(original_name)
        needs_alias = location == "path" and snake_name != original_name

        # Wrap type in Annotated[..., Location(constraints)] when constraints exist.
        fastapi_class: str | None = None
        constraint_result = _constraint_annotation(schema, location)
        if constraint_result:
            fastapi_class, kwargs_str = constraint_result
            if needs_alias:
                kwargs_str = f'{kwargs_str}, alias="{original_name}"'
            py_type = f"Annotated[{py_type}, {fastapi_class}({kwargs_str})]"
        elif needs_alias:
            py_type = f'Annotated[{py_type}, Path(alias="{original_name}")]'
            fastapi_class = "Path"

        default = schema.get("default")
        params.append(
            {
                "name": to_snake_case(param["name"]),
                "python_type": py_type,
                "location": location,
                "required": required,
                "default": default,
                "default_repr": repr(default) if default is not None else None,
                "description": param.get("description"),
                "alias": param["name"],
                "fastapi_class": fastapi_class,
                "constraints": extract_numeric_constraints(schema),
                "string_constraints": extract_string_constraints(schema),
                "enum_values": extract_enum_values(schema),
            }
        )

    # Request body
    body = operation.get("requestBody")
    if body:
        content = body.get("content") or {}
        json_schema = (content.get("application/json") or {}).get("schema")
        if json_schema:
            raw_body = (raw_operation or {}).get("requestBody") or {}
            raw_json_schema = (
                (raw_body.get("content") or {}).get("application/json") or {}
            ).get("schema")
            operation_id = operation.get("operationId")
            if (
                operation_id
                and raw_json_schema is not None
                and "$ref" not in raw_json_schema
                and isinstance(json_schema, dict)
                and json_schema.get("type") == "object"
                and json_schema.get("properties")
            ):
                py_type = inline_schema_name(operation_id, "Body")
            else:
                py_type = schema_to_python_type(
                    json_schema,
                    enums_as_literals=enums_as_literals,
                    raw_schema=raw_json_schema,
                    generic_name_map=generic_name_map,
                )
            # For split schemas, use the Write variant in request bodies.
            if split_schema_names and raw_json_schema and "$ref" in raw_json_schema:
                ref_name = raw_json_schema["$ref"].split("/")[-1]
                if ref_name in split_schema_names:
                    py_type = f"{ref_name}Write"
            py_type = f"Annotated[{py_type}, Body()]"
            params.append(
                {
                    "name": "body",
                    "python_type": py_type,
                    "location": "body",
                    "required": body.get("required", False),
                    "default": None,
                    "default_repr": None,
                    "description": body.get("description"),
                    "alias": "body",
                    "fastapi_class": "Body",
                    "constraints": {},
                    "string_constraints": {},
                    "enum_values": None,
                }
            )
        else:
            # multipart/form-data or application/x-www-form-urlencoded
            form_type = (
                "multipart/form-data"
                if "multipart/form-data" in content
                else "application/x-www-form-urlencoded"
                if "application/x-www-form-urlencoded" in content
                else None
            )
            if form_type:
                form_schema = (content[form_type].get("schema")) or {}
                properties: dict[str, Any] = form_schema.get("properties") or {}
                required_fields: set[str] = set(form_schema.get("required") or [])
                if properties:
                    for field_name, field_schema in properties.items():
                        is_file = field_schema.get(
                            "type"
                        ) == "string" and field_schema.get("format") in (
                            "binary",
                            "octet-stream",
                        )
                        if is_file:
                            field_py_type = "UploadFile"
                            fastapi_annotation = "File"
                        else:
                            field_py_type = schema_to_python_type(
                                field_schema,
                                enums_as_literals=enums_as_literals,
                                generic_name_map=generic_name_map,
                            )
                            fastapi_annotation = "Form"
                        field_required = field_name in required_fields
                        if not field_required:
                            field_py_type = f"{field_py_type} | None"
                        field_py_type = (
                            f"Annotated[{field_py_type}, {fastapi_annotation}()]"
                        )
                        field_default = field_schema.get("default")
                        params.append(
                            {
                                "name": to_snake_case(field_name),
                                "python_type": field_py_type,
                                "location": "body",
                                "required": field_required,
                                "default": field_default,
                                "default_repr": repr(field_default)
                                if field_default is not None
                                else None,
                                "description": field_schema.get("description"),
                                "alias": field_name,
                                "fastapi_class": fastapi_annotation,
                                "constraints": extract_numeric_constraints(
                                    field_schema
                                ),
                                "string_constraints": extract_string_constraints(
                                    field_schema
                                ),
                                "enum_values": extract_enum_values(field_schema),
                            }
                        )
                else:
                    # Schema not resolvable to individual fields — fall back to bytes
                    params.append(
                        {
                            "name": "body",
                            "python_type": "Annotated[bytes, Body()]",
                            "location": "body",
                            "required": body.get("required", False),
                            "default": None,
                            "default_repr": None,
                            "description": f"# TODO: {form_type} body — schema not resolved",
                            "alias": "body",
                            "fastapi_class": "Body",
                            "constraints": {},
                            "string_constraints": {},
                            "enum_values": None,
                        }
                    )
            else:
                # Unrecognized content type (e.g. text/plain, application/xml, image/*) —
                # emit bytes placeholder so the endpoint compiles and handles the body.
                unknown_type = next(
                    (ct for ct in content if ct != "application/json"), None
                )
                if unknown_type:
                    params.append(
                        {
                            "name": "body",
                            "python_type": "Annotated[bytes, Body()]",
                            "location": "body",
                            "required": body.get("required", False),
                            "default": None,
                            "default_repr": None,
                            "description": f"# TODO: {unknown_type} request body — map to appropriate type",
                            "alias": "body",
                            "fastapi_class": "Body",
                            "constraints": {},
                            "string_constraints": {},
                            "enum_values": None,
                        }
                    )

    # Required params first, optional last; body always after path/query/header.
    params.sort(key=lambda p: (not p["required"], p["location"] == "body"))

    return params


def resolve_response_status_code(operation: dict[str, Any]) -> int:
    """Return the HTTP status code for the primary 2xx success response.

    Falls back to 200 if no 2xx response code is declared in the spec.
    """
    responses = operation.get("responses") or {}
    success_codes = sorted(
        (code for code in responses if re.match(r"^2\d{2}$", code)),
        key=int,
    )
    return int(success_codes[0]) if success_codes else 200


def resolve_response_type(
    operation: dict[str, Any],
    *,
    raw_operation: dict[str, Any] | None = None,
    enums_as_literals: bool = True,
    generic_name_map: dict[str, str] | None = None,
) -> str:
    """
    Return the Python type for the 2xx success response(s).

    When multiple 2xx codes are present:
    - Identical resolved types are deduplicated → single type.
    - Distinct model types → ``T1 | T2`` union (PEP 604).
    - Empty response (e.g. 204) alongside a typed response → ``T | None``.
    - Binary content mixed with model types → ``Response`` (raw passthrough;
      FastAPI skips serialisation, caller must return a ``Response`` object).

    Falls back to ``"None"`` if no response schema is found anywhere.
    """
    responses = operation.get("responses") or {}
    raw_responses = (raw_operation or {}).get("responses") or {}
    success_codes = sorted(
        (code for code in responses if re.match(r"^2\d{2}$", code)),
        key=int,
    )
    operation_id = (raw_operation or {}).get("operationId")

    # Collect one resolved type string per 2xx status code.
    collected: list[str] = []
    for code in success_codes:
        resp = responses[code]
        content = resp.get("content") or {}
        schema = (content.get("application/json") or {}).get("schema")
        if schema:
            raw_resp = raw_responses.get(code) or {}
            raw_schema = (
                (raw_resp.get("content") or {}).get("application/json") or {}
            ).get("schema")
            if (
                operation_id
                and raw_schema is not None
                and "$ref" not in raw_schema
                and isinstance(schema, dict)
                and schema.get("type") == "object"
                and schema.get("properties")
            ):
                collected.append(inline_schema_name(operation_id, "Response"))
            else:
                collected.append(
                    schema_to_python_type(
                        schema,
                        enums_as_literals=enums_as_literals,
                        raw_schema=raw_schema,
                        generic_name_map=generic_name_map,
                    )
                )
        elif content:
            # Non-JSON content (e.g. text/csv, application/pdf, image/*).
            collected.append("bytes")
        else:
            # No content body (e.g. 204 No Content).
            collected.append("None")

    # Order-preserving deduplication.
    seen: set[str] = set()
    unique = [t for t in collected if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]

    if not unique or unique == ["None"]:
        return "None"
    if len(unique) == 1:
        return unique[0]

    non_none = [t for t in unique if t != "None"]
    has_empty = "None" in unique
    model_types = [t for t in non_none if t != "bytes"]

    # bytes mixed with model types → cannot unify; fall back to raw Response.
    if "bytes" in non_none and model_types:
        return "Response"

    parts = non_none + (["None"] if has_empty else [])
    return parts[0] if len(parts) == 1 else " | ".join(parts)
