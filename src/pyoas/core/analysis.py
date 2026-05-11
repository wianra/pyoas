"""Spec analysis utilities — pure functions operating on raw OpenAPI dicts.

These functions are the primary candidates for the Rust core. They operate on
raw (unresolved) or resolved spec dicts and have no dependency on code-generation
or template rendering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any

from .utils import to_pascal_case, to_snake_case

# Matches "GenericName[TypeParam]" in schema titles (single-level, word chars only).
_GENERIC_TITLE_RE = re.compile(r"^(\w+)\[(\w+)\]$")

# OpenAPI constraint key → Pydantic v2 / FastAPI annotation kwarg name.
# Single source of truth used by both model generation and router parameter handling.
# Includes `multipleOf` (valid in OpenAPI for both schemas and parameters).
CONSTRAINT_ARGS: dict[str, str] = {
    "minimum": "ge",
    "maximum": "le",
    "exclusiveMinimum": "gt",
    "exclusiveMaximum": "lt",
    "minLength": "min_length",
    "maxLength": "max_length",
    "pattern": "pattern",
    "minItems": "min_length",
    "maxItems": "max_length",
    "multipleOf": "multiple_of",
}


@dataclass
class _GenericGroup:
    """Represents a group of schemas that are concrete instantiations of a generic."""

    generic_name: str  # e.g. "Paginated"
    t_field_name: str  # property name that holds T (e.g. "data")
    t_is_list: bool  # True → field is list[T]; False → field is T
    template_schema_name: str  # concrete schema used as field template
    instances: list[dict[str, str]] = dc_field(default_factory=list)
    # {schema_name: str, type_param: str} per concrete schema
    home_tag: str | None = None  # tag owning the base class; None → shared


def build_schema_tag_map(
    spec_raw: dict[str, Any],
    grouped_raw: dict[str, list[dict[str, Any]]],
) -> dict[str, set[str]]:
    """
    Return a mapping of schema name → set of tags that reference it.

    Uses the *unresolved* spec so that ``$ref`` strings are still present.
    Transitive references (e.g. PetList → Pet) are followed.
    """
    tag_map: dict[str, set[str]] = {}
    components_schemas = spec_raw.get("components", {}).get("schemas", {})

    for tag, operations in grouped_raw.items():
        for op_entry in operations:
            operation = op_entry["operation"]
            for schema_name in _find_referenced_schemas(operation, components_schemas):
                tag_map.setdefault(schema_name, set()).add(tag)

    return tag_map


def _parse_defs_ref(ref: str) -> tuple[str, str] | None:
    """Parse a ``$defs`` ref like ``'#/components/schemas/Pet/$defs/Tag'``.

    Returns ``(parent_schema_name, def_name)`` or ``None`` if not a ``$defs`` ref.
    """
    parts = ref.split("/")
    # Expected: ['#', 'components', 'schemas', '{Parent}', '$defs', '{DefName}']
    if (
        len(parts) == 6
        and parts[1:3] == ["components", "schemas"]
        and parts[4] == "$defs"
    ):
        return parts[3], parts[5]
    return None


def _find_referenced_schemas(
    obj: Any,
    components_schemas: dict[str, Any],
    _visited: set[int] | None = None,
) -> list[str]:
    """
    Recursively find all component schema names referenced from ``obj``.

    Operates on the *raw* (unresolved) spec, following ``$ref`` strings.
    Transitive references are expanded.

    The ``_visited`` set uses Python object ids — dicts in ``spec_raw`` are not
    garbage-collected during traversal, so pointer identity is stable.
    """
    if _visited is None:
        _visited = set()

    if id(obj) in _visited:
        return []
    _visited.add(id(obj))

    names: list[str] = []
    if isinstance(obj, dict):
        if "$ref" in obj:
            ref = obj["$ref"]
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                defs_parsed = _parse_defs_ref(ref)
                if defs_parsed is not None:
                    # $defs ref: explore the $defs sub-schema for transitive
                    # component-schema refs, but do NOT add the parent schema
                    # name itself — the parent is only referenced when a direct
                    # #/components/schemas/{Parent} ref exists.
                    parent_name, def_name = defs_parsed
                    parent_schema = components_schemas.get(parent_name, {})
                    def_schema = (parent_schema.get("$defs") or {}).get(def_name)
                    if def_schema is not None:
                        names.extend(
                            _find_referenced_schemas(
                                def_schema, components_schemas, _visited
                            )
                        )
                else:
                    name = ref.split("/")[-1]
                    if name in components_schemas and name not in names:
                        names.append(name)
                        # Follow transitive references within the referenced schema.
                        names.extend(
                            _find_referenced_schemas(
                                components_schemas[name], components_schemas, _visited
                            )
                        )
        else:
            for v in obj.values():
                names.extend(_find_referenced_schemas(v, components_schemas, _visited))
    elif isinstance(obj, list):
        for item in obj:
            names.extend(_find_referenced_schemas(item, components_schemas, _visited))
    return names


def has_circular_refs(
    schema_names: list[str],
    components_schemas: dict[str, Any],
) -> bool:
    """Return True if any schema in *schema_names* references itself transitively.

    Uses ``_find_referenced_schemas`` with a fresh ``_visited`` set per schema
    so cross-schema cycles are also detected correctly.
    """
    for name in schema_names:
        if name not in components_schemas:
            continue
        referenced = _find_referenced_schemas(
            components_schemas[name], components_schemas
        )
        if name in referenced:
            return True
    return False


def find_split_schema_names(spec_raw: dict[str, Any]) -> set[str]:
    """Return schema names that will be split into Read/Write variants.

    A schema is split when any of its properties carries ``readOnly: true``
    or ``writeOnly: true``.  The router generator uses this set to substitute
    ``{Name}Write`` for request bodies and keep ``{Name}`` (= ``{Name}Read``
    alias) for response types.
    """
    schemas = spec_raw.get("components", {}).get("schemas", {})
    result: set[str] = set()
    for name, schema in schemas.items():
        if not isinstance(schema, dict):
            continue
        for prop_schema in (schema.get("properties") or {}).values():
            if isinstance(prop_schema, dict) and (
                prop_schema.get("readOnly") or prop_schema.get("writeOnly")
            ):
                result.add(name)
                break
    return result


def _find_t_field(
    raw_schema: dict[str, Any] | None,
    type_param: str,
) -> tuple[str, bool] | None:
    """
    Find the property in *raw_schema* that references *type_param* as its type.

    Returns ``(field_name, is_list)`` where ``is_list`` is True if the field is
    ``list[T]`` (array whose items ref the type param) and False if it is ``T``
    directly.  Returns ``None`` if no such field is found.
    """
    if not raw_schema:
        return None
    raw_props = raw_schema.get("properties") or {}
    ref_path = f"#/components/schemas/{type_param}"

    for prop_name, raw_prop in raw_props.items():
        if not isinstance(raw_prop, dict):
            continue
        if raw_prop.get("$ref") == ref_path:
            return prop_name, False
        if (
            raw_prop.get("type") == "array"
            and isinstance(raw_prop.get("items"), dict)
            and raw_prop["items"].get("$ref") == ref_path
        ):
            return prop_name, True
    return None


def detect_generic_groups_global(
    raw_components_schemas: dict[str, Any],
    schema_tag_map: dict[str, set[str]],
) -> dict[str, _GenericGroup]:
    """
    Scan all component schemas for ``title`` values matching ``Name[Param]``.

    Groups them by generic name and determines where the base class should
    live (``home_tag``): ``None`` (shared) if instances span multiple tags,
    otherwise the single tag that owns all instances.
    """
    # First pass: collect candidates
    by_generic: dict[str, list[dict[str, str]]] = {}
    for schema_name, raw_schema in raw_components_schemas.items():
        if not isinstance(raw_schema, dict):
            continue
        title = raw_schema.get("title", "")
        m = _GENERIC_TITLE_RE.match(title)
        if not m:
            continue
        generic_name, type_param = m.group(1), m.group(2)
        # Require the type param itself to be a known component schema
        if type_param not in raw_components_schemas:
            continue
        t_field = _find_t_field(raw_schema, type_param)
        if t_field is None:
            continue
        by_generic.setdefault(generic_name, []).append(
            {"schema_name": schema_name, "type_param": type_param}
        )

    # Fallback pass: mangled-key convention.
    # Handles specs where OpenAPI generators replace "[" → "_" and "]" → "_".
    # Supports two variants:
    #   "{Prefix}_{TypeParam}_"  — NSwag/OpenAPI Generator (trailing underscore)
    #   "{Prefix}_{TypeParam}"   — Spring and other generators (no trailing underscore)
    # Requires at least 2 schemas sharing the same prefix so the generic group
    # is unambiguous.
    already_captured: set[str] = {
        inst["schema_name"] for insts in by_generic.values() for inst in insts
    }
    mangled_candidates: dict[str, list[dict[str, str]]] = {}
    for schema_name, raw_schema in raw_components_schemas.items():
        if schema_name in already_captured:
            continue
        if not isinstance(raw_schema, dict):
            continue
        # Strip any trailing underscores to normalise both naming conventions.
        stripped = schema_name.rstrip("_")
        if "_" not in stripped:
            continue
        # Find the rightmost "_" that yields a valid component schema as suffix.
        found_prefix: str | None = None
        found_type_param: str | None = None
        for i in range(len(stripped) - 1, 0, -1):
            if stripped[i] == "_":
                candidate = stripped[i + 1 :]
                if candidate in raw_components_schemas:
                    found_prefix = stripped[:i]
                    found_type_param = candidate
                    break
        if found_prefix is None or found_type_param is None:
            continue
        if _find_t_field(raw_schema, found_type_param) is None:
            continue
        mangled_candidates.setdefault(found_prefix, []).append(
            {"schema_name": schema_name, "type_param": found_type_param}
        )

    for prefix, instances in mangled_candidates.items():
        # Require at least 2 instances to avoid false-positive single matches.
        if len(instances) < 2:
            continue
        if prefix in by_generic:
            continue  # title-based detection takes precedence
        by_generic[prefix] = instances

    # Second pass: build _GenericGroup objects with home_tag resolved
    groups: dict[str, _GenericGroup] = {}
    for generic_name, instances in by_generic.items():
        # Use first instance as the field template
        first_schema_name = instances[0]["schema_name"]
        first_raw = raw_components_schemas[first_schema_name]
        first_type_param = instances[0]["type_param"]
        t_field_name, t_is_list = _find_t_field(first_raw, first_type_param)  # type: ignore[misc]

        # Collect tags for all instances to determine home_tag
        all_instance_tags: set[str] = set()
        for inst in instances:
            all_instance_tags.update(schema_tag_map.get(inst["schema_name"], set()))

        home_tag: str | None
        if len(all_instance_tags) == 1:
            home_tag = next(iter(all_instance_tags))
        else:
            home_tag = None  # goes to shared

        groups[generic_name] = _GenericGroup(
            generic_name=generic_name,
            t_field_name=t_field_name,
            t_is_list=t_is_list,
            template_schema_name=first_schema_name,
            instances=instances,
            home_tag=home_tag,
        )

    return groups


def inline_schema_name(operation_id: str, suffix: str) -> str:
    """Return a synthesized class name for an inline schema.

    E.g. ``inline_schema_name("listPets", "Body")`` → ``"ListPetsBody"``.
    Handles camelCase, snake_case, and hyphenated operationIds.
    """
    # Sanitise non-identifier chars, then snake_case to handle camelCase
    # transitions, then PascalCase for a valid class name.
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", operation_id)
    return to_pascal_case(to_snake_case(sanitized)) + suffix


def _is_inline_object(
    schema: dict[str, Any] | None, raw_schema: dict[str, Any] | None
) -> bool:
    """True when *schema* is an inline object (not a ``$ref``, has ``properties``)."""
    return (
        schema is not None
        and raw_schema is not None
        and "$ref" not in raw_schema
        and isinstance(schema, dict)
        and schema.get("type") == "object"
        and bool(schema.get("properties"))
    )


def collect_inline_schemas(
    grouped: dict[str, list[dict[str, Any]]],
    grouped_raw: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    """Scan operations for inline object schemas in requestBody and 2xx responses.

    Returns:
        inline_by_tag: tag → list of ``{name, schema, raw_schema}`` entries
        inline_request_names: synthesized names that are request-body-only
    """
    inline_by_tag: dict[str, list[dict[str, Any]]] = {}
    inline_request_names: set[str] = set()
    seen_names: set[str] = set()

    raw_ops: dict[tuple[str, str], dict[str, Any]] = {
        (e["path"], e["method"]): e["operation"]
        for ops in grouped_raw.values()
        for e in ops
    }

    for tag, ops in grouped.items():
        for e in ops:
            operation = e["operation"]
            raw_op = raw_ops.get((e["path"], e["method"]), {})
            operation_id = operation.get("operationId")
            if not operation_id:
                continue

            # Request body
            body = operation.get("requestBody")
            raw_body = raw_op.get("requestBody") or {}
            if body:
                json_schema = (
                    (body.get("content") or {}).get("application/json") or {}
                ).get("schema")
                raw_json = (
                    (raw_body.get("content") or {}).get("application/json") or {}
                ).get("schema")
                if _is_inline_object(json_schema, raw_json):
                    synth = inline_schema_name(operation_id, "Body")
                    if synth not in seen_names:
                        seen_names.add(synth)
                        inline_by_tag.setdefault(tag, []).append(
                            {
                                "name": synth,
                                "schema": json_schema,
                                "raw_schema": raw_json,
                            }
                        )
                        inline_request_names.add(synth)

            # 2xx responses
            for code, resp in (operation.get("responses") or {}).items():
                if not re.match(r"^2\d{2}$", str(code)):
                    continue
                raw_resp = (raw_op.get("responses") or {}).get(code) or {}
                json_schema = (
                    (resp.get("content") or {}).get("application/json") or {}
                ).get("schema")
                raw_json = (
                    (raw_resp.get("content") or {}).get("application/json") or {}
                ).get("schema")
                if _is_inline_object(json_schema, raw_json):
                    synth = inline_schema_name(operation_id, "Response")
                    if synth not in seen_names:
                        seen_names.add(synth)
                        inline_by_tag.setdefault(tag, []).append(
                            {
                                "name": synth,
                                "schema": json_schema,
                                "raw_schema": raw_json,
                            }
                        )

    return inline_by_tag, inline_request_names
