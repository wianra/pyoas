"""Schema rendering helpers for model generation.

Converts OpenAPI schema dicts into model/alias descriptor dicts for use with
the Jinja2 model template.
"""

from __future__ import annotations

import re
from typing import Any

from pyoas.core.analysis import CONSTRAINT_ARGS, _GenericGroup
from pyoas.core.config import Config
from pyoas.core.utils import to_snake_case

from .types import schema_to_python_type


def _build_fields(
    properties: dict[str, Any],
    raw_properties: dict[str, Any],
    required_props: list[str],
    config: Config,
    *,
    t_field_override: tuple[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """Build field descriptor dicts for a model schema.

    ``t_field_override`` is a ``(field_name, is_list)`` pair. When the current
    property matches *field_name*, its type is replaced with ``list[T]`` or
    ``T`` instead of being resolved from the schema — used by generic base
    class rendering.
    """
    fields: list[dict[str, Any]] = []
    for prop_name, prop_schema in properties.items():
        raw_prop = raw_properties.get(prop_name)
        is_required = prop_name in required_props
        field_name = to_snake_case(prop_name) if config.fields.snake_case else prop_name

        if t_field_override and prop_name == t_field_override[0]:
            py_type = "list[T]" if t_field_override[1] else "T"
        else:
            py_type = schema_to_python_type(
                prop_schema,
                enums_as_literals=config.fields.enums_as_literals,
                raw_schema=raw_prop,
            )
            if (
                not is_required
                and prop_schema.get("default") is None
                and "None" not in py_type
            ):
                py_type = f"{py_type} | None"

        fields.append(
            {
                "name": field_name,
                "alias": prop_name,
                "python_type": py_type,
                "required": is_required,
                "constraints": _extract_constraints(prop_schema),
                "field_kwargs": _build_field_kwargs(
                    prop_name, prop_schema, is_required, field_name=field_name
                ),
                "read_only": prop_schema.get("readOnly", False),
                "write_only": prop_schema.get("writeOnly", False),
            }
        )
    return fields


def _render_enum_class(name: str, schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a StrEnum / IntEnum class descriptor from a component enum schema."""
    raw_type = schema.get("type")
    enum_type = "StrEnum" if raw_type != "integer" else "IntEnum"
    members: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for v in schema.get("enum") or []:
        if v is None:
            continue
        raw_str = str(v)
        member_name = re.sub(r"[^a-zA-Z0-9]+", "_", raw_str).strip("_").upper()
        if not member_name or member_name[0].isdigit():
            member_name = f"VALUE_{member_name}"
        # Deduplicate
        base = member_name
        idx = 1
        while member_name in seen_names:
            member_name = f"{base}_{idx}"
            idx += 1
        seen_names.add(member_name)
        members.append({"name": member_name, "value": repr(v)})
    return [
        {
            "name": name,
            "is_alias": False,
            "is_enum_class": True,
            "enum_type": enum_type,
            "members": members,
            "description": schema.get("description"),
        }
    ]


def _render_schema(
    schema_entry: dict[str, Any],
    config: Config,
) -> list[dict[str, Any]]:
    """
    Render a single component schema into one or more model/alias dicts.

    Returns a list because readOnly/writeOnly schemas produce two variants.
    """
    name = schema_entry["name"]
    schema = schema_entry["schema"]
    raw_schema = schema_entry.get("raw_schema")

    # Component-level enum schema (no properties, has enum values).
    if "enum" in schema and not schema.get("properties"):
        if config.fields.enums_as_literals:
            # Type alias: PetStatus = Literal["available", ...]
            alias_type = schema_to_python_type(
                schema,
                enums_as_literals=True,
                raw_schema=raw_schema,
            )
            return [
                {
                    "name": name,
                    "is_alias": True,
                    "alias_type": alias_type,
                    "description": schema.get("description"),
                }
            ]
        else:
            return _render_enum_class(name, schema)

    # Type alias: oneOf/anyOf at top level without own properties.
    if _is_type_alias(schema):
        alias_type = schema_to_python_type(
            schema,
            enums_as_literals=config.fields.enums_as_literals,
            raw_schema=raw_schema,
        )
        return [
            {
                "name": name,
                "is_alias": True,
                "alias_type": alias_type,
                "description": schema.get("description"),
            }
        ]

    # Regular object schema — collect fields.
    properties = schema.get("properties") or {}
    raw_properties = (raw_schema or {}).get("properties") or {}
    required_props: list[str] = schema.get("required") or []

    fields = _build_fields(properties, raw_properties, required_props, config)

    bases = _find_allof_bases(raw_schema)

    # Split into Read/Write variants when ANY readOnly or writeOnly annotation exists.
    has_read_only = any(f["read_only"] for f in fields)
    has_write_only = any(f["write_only"] for f in fields)

    if has_read_only or has_write_only:
        read_fields = [f for f in fields if not f["write_only"]]
        write_fields = [f for f in fields if not f["read_only"]]
        return [
            {
                "name": f"{name}Read",
                "is_alias": False,
                "fields": read_fields,
                "bases": bases,
                "description": schema.get("description"),
            },
            {
                "name": f"{name}Write",
                "is_alias": False,
                "fields": write_fields,
                "bases": bases,
                "description": schema.get("description"),
            },
            # Alias keeps the original $ref name pointing to the Read variant,
            # so intra-schema references and router imports continue to resolve.
            {
                "name": name,
                "is_alias": True,
                "alias_type": f"{name}Read",
                "description": None,
            },
        ]

    return [
        {
            "name": name,
            "is_alias": False,
            "fields": fields,
            "bases": bases,
            "description": schema.get("description"),
        }
    ]


def _is_type_alias(schema: dict[str, Any]) -> bool:
    """True if this schema should be rendered as a type alias rather than a class."""
    has_composition = "oneOf" in schema or "anyOf" in schema
    has_properties = bool(schema.get("properties"))
    return has_composition and not has_properties


def _find_allof_bases(raw_schema: dict[str, Any] | None) -> list[str]:
    """Extract base class names from allOf $ref entries in the raw schema."""
    if not raw_schema:
        return []
    bases: list[str] = []
    for sub in raw_schema.get("allOf", []):
        if isinstance(sub, dict) and "$ref" in sub:
            ref = sub["$ref"]
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                bases.append(ref.split("/")[-1])
    return bases


def _build_field_kwargs(
    prop_name: str,
    prop_schema: dict[str, Any],
    is_required: bool,
    field_name: str = "",
) -> list[tuple[str, str]]:
    """
    Build the ordered list of ``(kwarg_name, python_value_repr)`` pairs for
    a Pydantic v2 ``Field(...)`` call, excluding constraint kwargs (those go
    inside ``Annotated``).

    Order: default → alias → description → title → examples.
    ``alias`` is only emitted when the Python identifier differs from the
    original JSON property name (i.e. after snake_case conversion).
    """
    kwargs: list[tuple[str, str]] = []

    # default / sentinel
    if "default" in prop_schema:
        kwargs.append(("default", repr(prop_schema["default"])))
    elif not is_required:
        kwargs.append(("default", "None"))
    else:
        kwargs.append(("default", "..."))

    # Only emit alias when the Python field name differs from the JSON key.
    if not field_name or field_name != prop_name:
        kwargs.append(("alias", repr(prop_name)))

    if desc := prop_schema.get("description"):
        kwargs.append(("description", repr(desc)))

    if title := prop_schema.get("title"):
        kwargs.append(("title", repr(title)))

    # OpenAPI 3.1 uses "examples" (list); 3.0 uses "example" (scalar).
    examples = prop_schema.get("examples")
    if examples is None and "example" in prop_schema:
        examples = [prop_schema["example"]]
    if examples:
        kwargs.append(("examples", repr(examples)))

    return kwargs


def _extract_constraints(schema: dict[str, Any]) -> dict[str, str]:
    """Return a dict of Pydantic v2 Field constraint kwargs (as repr strings)."""
    result: dict[str, str] = {}
    for openapi_key, pydantic_key in CONSTRAINT_ARGS.items():
        if openapi_key not in schema:
            continue
        val = schema[openapi_key]
        # OAS 3.0 boolean form: exclusiveMinimum/exclusiveMaximum are flags, not values.
        if openapi_key == "exclusiveMinimum" and isinstance(val, bool):
            if val and "minimum" in schema:
                result["gt"] = repr(schema["minimum"])
        elif openapi_key == "exclusiveMaximum" and isinstance(val, bool):
            if val and "maximum" in schema:
                result["lt"] = repr(schema["maximum"])
        else:
            result[pydantic_key] = repr(val)
    return result


def _render_generic_base_schema(
    group: _GenericGroup,
    template_entry: dict[str, Any],
    config: Config,
) -> dict[str, Any]:
    """
    Build the schema dict for the generic base class.

    Identical to ``_render_schema`` for a normal object except the T field
    gets ``list[T]`` or ``T`` instead of a concrete type reference.
    """
    schema = template_entry["schema"]
    raw_schema = template_entry.get("raw_schema") or {}

    properties = schema.get("properties") or {}
    raw_properties = raw_schema.get("properties") or {}
    required_props: list[str] = schema.get("required") or []

    fields = _build_fields(
        properties,
        raw_properties,
        required_props,
        config,
        t_field_override=(group.t_field_name, group.t_is_list),
    )

    return {
        "name": group.generic_name,
        "is_alias": False,
        "is_generic": True,
        "type_params": ["T"],
        "fields": fields,
        "bases": [],
        "description": schema.get("description"),
    }
