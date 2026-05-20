from __future__ import annotations

import warnings
from typing import Any

HTTP_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
)

# Matcher value for a skip_extensions entry:
#   None              → presence/truthy match (skip if op[key] is truthy)
#   frozenset(values) → equality match (skip if op[key] is in the set)
SkipMatcher = frozenset[Any] | None
SkipExtensions = dict[str, SkipMatcher]


def normalize_skip_extensions(
    value: Any,
) -> SkipExtensions:
    """Normalize a user-supplied skip_extensions value into the internal form.

    Accepts:
      * ``None`` or empty list/dict → no filtering.
      * ``list[str]`` (legacy) → each entry is a presence/truthy check.
      * ``dict[str, ...]`` → value-aware matching, where the value may be:
          - ``True``  → presence/truthy check.
          - a scalar (``str``/``int``/``float``) → equality match.
          - a list of scalars → match if op[key] is in the list.

    Raises ``ValueError`` with a clear message for any other shape (including
    ``False``, ``None``, or nested mappings as values) so misconfigured YAML
    fails loudly rather than silently doing nothing.
    """
    if value is None:
        return {}
    if isinstance(value, (list, tuple)):
        result: SkipExtensions = {}
        for entry in value:
            if not isinstance(entry, str):
                raise ValueError(
                    "skip_extensions list entries must be strings; got "
                    f"{type(entry).__name__}"
                )
            result[entry] = None
        return result
    if isinstance(value, dict):
        result = {}
        for key, raw in value.items():
            if not isinstance(key, str):
                raise ValueError(
                    f"skip_extensions keys must be strings; got {type(key).__name__}"
                )
            if raw is True:
                result[key] = None
            elif isinstance(raw, bool):
                raise ValueError(
                    f"skip_extensions[{key!r}] = false is ambiguous; either "
                    "remove the entry to disable it or use `true` for a "
                    "presence check"
                )
            elif isinstance(raw, (str, int, float)):
                result[key] = frozenset({raw})
            elif isinstance(raw, list):
                try:
                    result[key] = frozenset(raw)
                except TypeError as exc:
                    raise ValueError(
                        f"skip_extensions[{key!r}] list contains unhashable values"
                    ) from exc
            else:
                raise ValueError(
                    f"skip_extensions[{key!r}] must be `true`, a scalar, or a "
                    f"list of scalars; got {type(raw).__name__}"
                )
        return result
    raise ValueError(
        f"skip_extensions must be a list or mapping; got {type(value).__name__}"
    )


def _matches_skip(operation: dict[str, Any], skip: SkipExtensions) -> bool:
    """Return True if the operation matches any configured skip rule (OR)."""
    for key, allowed in skip.items():
        value = operation.get(key)
        if allowed is None:
            if value:
                return True
        else:
            try:
                if value in allowed:
                    return True
            except TypeError:
                # unhashable op value (e.g. list/dict) — cannot match by equality
                continue
    return False


def extract_tags(
    spec: dict[str, Any],
    default_tag: str = "default",
    include_webhooks: bool = False,
    skip_extensions: SkipExtensions | list[str] | tuple[str, ...] = (),
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

    skip_filter: SkipExtensions = (
        skip_extensions
        if isinstance(skip_extensions, dict)
        else {key: None for key in skip_extensions}
    )

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

            if skip_filter and _matches_skip(operation, skip_filter):
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
