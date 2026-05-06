"""Schema classification helpers for model generation.

Determines which schemas belong to a single tag (tag-local), which are shared
across tags, and which schemas appear only in request bodies.
"""

from __future__ import annotations

from typing import Any

from pyoas.core.tags import HTTP_METHODS


def _direct_schema_refs(content: dict[str, Any]) -> set[str]:
    """Return schema names directly referenced in a requestBody/response content map."""
    names: set[str] = set()
    for media in content.values():
        if not isinstance(media, dict):
            continue
        schema_ref = media.get("schema", {})
        if isinstance(schema_ref, dict) and "$ref" in schema_ref:
            ref = schema_ref["$ref"]
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                names.add(ref.split("/")[-1])
    return names


def _find_request_only_schema_names(spec_raw: dict[str, Any]) -> set[str]:
    """
    Return schema names used *only* in request bodies (never in responses).

    Schemas used in both contexts keep ``extra="ignore"`` so API evolution
    doesn't break response parsing.
    """
    request_names: set[str] = set()
    response_names: set[str] = set()

    for path_item in spec_raw.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            request_body = operation.get("requestBody", {})
            if isinstance(request_body, dict):
                request_names.update(
                    _direct_schema_refs(request_body.get("content", {}))
                )
            for response in operation.get("responses", {}).values():
                if isinstance(response, dict):
                    response_names.update(
                        _direct_schema_refs(response.get("content", {}))
                    )

    return request_names - response_names


def _collect_tag_schemas(
    tag: str,
    spec: dict[str, Any],
    schema_tag_map: dict[str, set[str]],
    raw_components_schemas: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return schemas exclusively owned by this tag (not shared)."""
    components_schemas = spec.get("components", {}).get("schemas", {})
    owned: list[dict[str, Any]] = []
    seen: set[str] = set()

    for name, tags in schema_tag_map.items():
        if tags == {tag} and name not in seen:
            seen.add(name)
            owned.append(
                {
                    "name": name,
                    "schema": components_schemas[name],
                    "raw_schema": raw_components_schemas.get(name),
                }
            )

    return owned


def _collect_shared_schemas(
    spec: dict[str, Any],
    schema_tag_map: dict[str, set[str]],
    raw_components_schemas: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return schemas referenced by more than one tag."""
    components_schemas = spec.get("components", {}).get("schemas", {})
    return [
        {
            "name": name,
            "schema": components_schemas[name],
            "raw_schema": raw_components_schemas.get(name),
        }
        for name, tags in schema_tag_map.items()
        if len(tags) > 1 and name in components_schemas
    ]


def _find_defs_ref_users(
    raw_components_schemas: dict[str, Any],
    parent_name: str,
    def_name: str,
) -> set[str]:
    """Return component schema names that reference ``#/…/{parent_name}/$defs/{def_name}``."""
    target_ref = f"#/components/schemas/{parent_name}/$defs/{def_name}"
    users: set[str] = set()

    def _walk(obj: Any, owner: str) -> None:
        if isinstance(obj, dict):
            if obj.get("$ref") == target_ref:
                users.add(owner)
            else:
                for v in obj.values():
                    _walk(v, owner)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item, owner)

    for schema_name, schema in raw_components_schemas.items():
        _walk(schema, schema_name)

    return users


def _collect_defs_schemas(
    raw_components_schemas: dict[str, Any],
    resolved_components_schemas: dict[str, Any],
    schema_tag_map: dict[str, set[str]],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Collect schemas from ``$defs`` blocks inside component schemas.

    Returns:
        defs_by_tag:  tag_name → list of schema entries (tag-local ``$defs``)
        shared_defs:  list of schema entries (``$defs`` referenced by multiple tags)
    """
    defs_by_tag: dict[str, list[dict[str, Any]]] = {}
    shared_defs: list[dict[str, Any]] = []
    seen_refs: set[str] = set()

    for parent_name, raw_parent in raw_components_schemas.items():
        if not isinstance(raw_parent, dict):
            continue
        defs_block = raw_parent.get("$defs")
        if not isinstance(defs_block, dict):
            continue

        resolved_parent = resolved_components_schemas.get(parent_name) or {}
        resolved_defs_block: dict[str, Any] = (
            resolved_parent.get("$defs") or {}
            if isinstance(resolved_parent, dict)
            else {}
        )

        for def_name, raw_def_schema in defs_block.items():
            ref_path = f"#/components/schemas/{parent_name}/$defs/{def_name}"
            if ref_path in seen_refs:
                continue
            seen_refs.add(ref_path)

            resolved_def_schema = resolved_defs_block.get(def_name, raw_def_schema)

            user_schemas = _find_defs_ref_users(
                raw_components_schemas, parent_name, def_name
            )

            tags_involved: set[str] = set()
            for user_schema_name in user_schemas:
                tags_involved.update(schema_tag_map.get(user_schema_name, set()))

            entry: dict[str, Any] = {
                "name": def_name,
                "schema": resolved_def_schema,
                "raw_schema": raw_def_schema,
            }

            if len(tags_involved) > 1:
                shared_defs.append(entry)
            elif len(tags_involved) == 1:
                tag = next(iter(tags_involved))
                defs_by_tag.setdefault(tag, []).append(entry)
            # Unreferenced $defs (tags_involved == empty) are skipped.

    return defs_by_tag, shared_defs
