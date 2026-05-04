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
