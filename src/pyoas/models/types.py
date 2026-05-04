"""
OpenAPI schema → Python / Pydantic v2 type mapping.

This module is the single authoritative place for converting an OpenAPI schema
object to a Python type annotation string.  It handles:

- Scalar types (string, integer, number, boolean)
- Format-specific overrides (date, date-time, uuid, binary)
- Arrays and plain objects
- Nullable (3.0 ``nullable: true`` and 3.1 ``type: ["T", "null"]``)
- ``allOf`` / ``anyOf`` / ``oneOf`` with optional discriminator
- String and integer enums

The optional ``raw_schema`` parameter is the *unresolved* OpenAPI schema (with
``$ref`` strings intact).  When provided, ``$ref`` entries are used to resolve
component schema names directly instead of introspecting resolved content.
"""

from __future__ import annotations

import warnings
from typing import Any

# Maps (openapi_type, openapi_format) → Python annotation.
# format=None means no format qualifier.
_FORMAT_MAP: dict[tuple[str, str | None], str] = {
    ("string", None): "str",
    ("string", "date"): "datetime.date",
    ("string", "date-time"): "datetime.datetime",
    ("string", "uuid"): "uuid.UUID",
    ("string", "binary"): "bytes",
    ("string", "byte"): "bytes",
    ("string", "password"): "str",
    ("string", "email"): "str",
    ("integer", None): "int",
    ("integer", "int32"): "int",
    ("integer", "int64"): "int",
    ("number", None): "float",
    ("number", "float"): "float",
    ("number", "double"): "float",
    ("boolean", None): "bool",
}

# Required imports for types that reference stdlib modules.
_TYPE_IMPORTS: dict[str, str] = {
    "datetime.date": "import datetime",
    "datetime.datetime": "import datetime",
    "uuid.UUID": "import uuid",
}


def schema_to_python_type(
    schema: dict[str, Any],
    *,
    enums_as_literals: bool = True,
    context_name: str = "",
    raw_schema: dict[str, Any] | None = None,
    generic_name_map: dict[str, str] | None = None,
) -> str:
    """
    Return a Python type annotation string for the given OpenAPI schema.

    ``raw_schema`` is the corresponding *unresolved* schema object (with
    ``$ref`` strings still present).  When a ``$ref`` is found at the top
    level of ``raw_schema``, the referenced component name is returned
    directly (e.g. ``"Pet"``).

    ``context_name`` is used to derive names for inline object types.

    ``generic_name_map`` maps original spec schema names to their generic
    instantiation strings (e.g. ``{"Paginated_DriverListItem_":
    "Paginated[DriverListItem]"}``).  When provided, component refs that
    match a key are rewritten to the corresponding value.
    """
    # If the raw schema is a direct $ref to a component, use the name.
    # Fall back to the resolved schema carrying a $ref — this happens when
    # _deep_copy broke a circular reference and re-emitted the ref string.
    for ref_holder in (raw_schema, schema):
        if ref_holder and "$ref" in ref_holder:
            ref = ref_holder["$ref"]
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                name = ref.split("/")[-1]
                if generic_name_map and name in generic_name_map:
                    return generic_name_map[name]
                return name
            break

    # Handle nullable at the top level before dispatching.
    is_nullable = _is_nullable(schema)
    base = _base_type(
        schema,
        enums_as_literals=enums_as_literals,
        context_name=context_name,
        raw_schema=raw_schema,
    )

    if is_nullable and base != "None":
        return f"{base} | None"
    return base


def _is_nullable(schema: dict[str, Any]) -> bool:
    """True if the schema allows ``null`` values."""
    # OpenAPI 3.0: nullable: true
    if schema.get("nullable") is True:
        return True
    # OpenAPI 3.1: type: ["T", "null"] or type: "null"
    t = schema.get("type")
    if isinstance(t, list):
        return "null" in t
    if t == "null":
        return True
    # OpenAPI 3.1: anyOf/oneOf with a {type: "null"} entry (FastAPI nullable pattern)
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            for sub in schema[keyword]:
                if isinstance(sub, dict) and sub.get("type") == "null":
                    return True
    return False


def _strip_null(types: list[str]) -> list[str]:
    return [t for t in types if t != "null"]


def _base_type(
    schema: dict[str, Any],
    *,
    enums_as_literals: bool,
    context_name: str,
    raw_schema: dict[str, Any] | None = None,
) -> str:
    # OAS 'not' keyword — cannot be expressed as a Python type annotation.
    if "not" in schema:
        warnings.warn(
            "OpenAPI 'not' keyword cannot be expressed as a Python type annotation; "
            "falling back to 'Any'.",
            UserWarning,
            stacklevel=3,
        )
        return "Any"

    # OAS 3.1 prefixItems — fixed-length tuple.
    prefix_items = schema.get("prefixItems")
    if prefix_items and isinstance(prefix_items, list):
        item_types = [
            schema_to_python_type(item, enums_as_literals=enums_as_literals)
            for item in prefix_items
            if isinstance(item, dict)
        ]
        if item_types:
            return f"tuple[{', '.join(item_types)}]"

    # allOf → inheritance / merged model
    if "allOf" in schema:
        raw_items = (raw_schema or {}).get("allOf", [])
        parts = []
        for i, s in enumerate(schema["allOf"]):
            raw_s = raw_items[i] if i < len(raw_items) else None
            parts.append(
                schema_to_python_type(
                    s, enums_as_literals=enums_as_literals, raw_schema=raw_s
                )
            )
        return " | ".join(parts) if len(parts) > 1 else (parts[0] if parts else "Any")

    # anyOf / oneOf → union (with optional discriminator)
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            raw_items = (raw_schema or {}).get(keyword, [])
            parts = []
            for i, s in enumerate(schema[keyword]):
                if isinstance(s, dict) and s.get("type") == "null":
                    continue
                raw_s = raw_items[i] if i < len(raw_items) else None
                parts.append(
                    schema_to_python_type(
                        s, enums_as_literals=enums_as_literals, raw_schema=raw_s
                    )
                )

            if "discriminator" in schema:
                discriminator_prop = schema["discriminator"]["propertyName"]
                union_str = (
                    " | ".join(parts)
                    if len(parts) > 1
                    else (parts[0] if parts else "Any")
                )
                return f'Annotated[{union_str}, Field(discriminator="{discriminator_prop}")]'

            if len(parts) == 1:
                return parts[0]
            return " | ".join(parts)

    raw_type = schema.get("type")

    # 3.1 array type: ["T", "null"] — extract the non-null type
    if isinstance(raw_type, list):
        non_null = _strip_null(raw_type)
        if len(non_null) == 1:
            raw_type = non_null[0]
        elif len(non_null) > 1:
            parts = [
                schema_to_python_type({"type": t}, enums_as_literals=enums_as_literals)
                for t in non_null
            ]
            return " | ".join(parts)
        else:
            return "None"

    fmt = schema.get("format")

    # Enums
    if "enum" in schema:
        return _enum_type(schema["enum"], raw_type, enums_as_literals=enums_as_literals)

    match raw_type:
        case "array":
            items = schema.get("items", {})
            raw_items_schema = (raw_schema or {}).get("items") or None
            item_type = (
                schema_to_python_type(
                    items,
                    enums_as_literals=enums_as_literals,
                    raw_schema=raw_items_schema,
                )
                if items
                else "Any"
            )
            if schema.get("uniqueItems"):
                return f"set[{item_type}]"
            return f"list[{item_type}]"
        case "object":
            props = schema.get("properties")
            if props:
                # Inline object with properties → caller should generate a model class.
                return context_name or "dict[str, Any]"
            additional = schema.get("additionalProperties")
            if isinstance(additional, dict):
                val_type = schema_to_python_type(
                    additional, enums_as_literals=enums_as_literals
                )
                return f"dict[str, {val_type}]"
            return "dict[str, Any]"
        case None:
            # No type — could be a free-form schema
            return "Any"
        case _:
            return _FORMAT_MAP.get(
                (str(raw_type), fmt), _FORMAT_MAP.get((str(raw_type), None), "Any")
            )


def _enum_type(
    values: list[Any], raw_type: str | None, *, enums_as_literals: bool
) -> str:
    if enums_as_literals:
        formatted = ", ".join(_format_literal(v) for v in values if v is not None)
        return f"Literal[{formatted}]"
    # StrEnum / IntEnum class generation is handled by the generator, not here.
    # Return a placeholder.
    return "str" if raw_type == "string" else "int"


def _format_literal(value: Any) -> str:
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return repr(value)


def required_imports(type_annotation: str) -> list[str]:
    """Return stdlib import lines needed for the given type annotation string."""
    imports: list[str] = []
    for type_str, import_line in _TYPE_IMPORTS.items():
        if type_str in type_annotation and import_line not in imports:
            imports.append(import_line)
    return imports
