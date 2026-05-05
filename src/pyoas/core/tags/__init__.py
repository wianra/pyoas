from __future__ import annotations

import warnings
from typing import Any

HTTP_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
)


def extract_tags(
    spec: dict[str, Any],
    default_tag: str = "default",
    include_webhooks: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """
    Group all path operations in the spec by their first tag.

    Operations with no tags (or an empty tags list) are placed under
    ``default_tag``. Returns a dict mapping ``tag_name → list[operation]``
    where each operation entry is::

        {
            "method":    "get",
            "path":      "/users/{id}",
            "operation": { ... },   # the raw operation object
            "is_webhook": False,    # True for OAS 3.1 webhook operations
        }

    When ``include_webhooks`` is True, operations from the top-level
    ``webhooks:`` map (OAS 3.1) are included alongside path operations.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}

    declared_tags = {
        t["name"] for t in spec.get("tags", []) if isinstance(t, dict) and "name" in t
    }
    if default_tag in declared_tags:
        warnings.warn(
            f"default_tag '{default_tag}' collides with an explicitly declared tag in "
            "the spec. Untagged operations will be merged into that tag's output.",
            UserWarning,
            stacklevel=2,
        )

    def _process_path_item(
        path_or_name: str,
        path_item: dict[str, Any],
        *,
        is_webhook: bool,
    ) -> None:
        path_level_params: list[dict[str, Any]] = [
            p for p in (path_item.get("parameters") or []) if isinstance(p, dict)
        ]

        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue

            # Merge path-level parameters into the operation. Operation-level
            # parameters with the same (name, in) take precedence per OAS spec.
            if path_level_params:
                op_params: list[dict[str, Any]] = [
                    p
                    for p in (operation.get("parameters") or [])
                    if isinstance(p, dict)
                ]
                op_param_keys = {(p.get("name"), p.get("in")) for p in op_params}
                inherited = [
                    p
                    for p in path_level_params
                    if (p.get("name"), p.get("in")) not in op_param_keys
                ]
                if inherited:
                    operation = {**operation, "parameters": inherited + op_params}

            op_tags: list[str] = operation.get("tags") or []
            tag = op_tags[0] if op_tags else default_tag

            grouped.setdefault(tag, []).append(
                {
                    "method": method,
                    "path": path_or_name,
                    "operation": operation,
                    "is_webhook": is_webhook,
                }
            )

    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        _process_path_item(path, path_item, is_webhook=False)

    if include_webhooks:
        for wh_name, path_item in spec.get("webhooks", {}).items():
            if not isinstance(path_item, dict):
                continue
            _process_path_item(wh_name, path_item, is_webhook=True)

    return grouped


def get_declared_tags(spec: dict[str, Any]) -> list[str]:
    """Return tag names from the top-level ``tags`` array, in order."""
    return [
        t["name"] for t in spec.get("tags", []) if isinstance(t, dict) and "name" in t
    ]
