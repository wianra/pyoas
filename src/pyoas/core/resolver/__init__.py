from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonref


def resolve_refs(
    spec: dict[str, Any], spec_path: str | Path | None = None
) -> dict[str, Any]:
    """
    Resolve all ``$ref`` entries in the spec in-place, returning a new dict.

    - OpenAPI 3.0: ``$ref`` replaces the object (siblings ignored per spec)
    - OpenAPI 3.1: ``$ref`` siblings are valid JSON Schema 2020-12 and are
      preserved. ``jsonref`` with ``merge_props=True`` handles this correctly.

    ``spec_path`` is used as the base URI for resolving relative file
    references. Pass the absolute path to the spec file.

    Circular ``$ref`` entries (e.g. a tree node that references itself) are
    detected and replaced with a plain ``{"$ref": "..."}`` dict so that
    downstream code can emit the correct forward-reference type annotation
    instead of recursing infinitely.
    """
    base_uri = ""
    if spec_path is not None:
        base_uri = Path(spec_path).resolve().as_uri()

    resolved = jsonref.replace_refs(
        spec,
        base_uri=base_uri,
        lazy_load=False,
        merge_props=True,
    )
    # jsonref returns a JsonRef proxy; convert to a plain dict so downstream
    # code can use isinstance checks freely.
    return _deep_copy(resolved, set())


def _deep_copy(obj: Any, _seen: set[int]) -> Any:
    """Recursively convert jsonref proxies to plain Python objects.

    ``_seen`` tracks the ids of dicts currently on the call stack (ancestors)
    so that circular ``$ref`` chains are detected before infinite recursion
    occurs.  When a ``jsonref.JsonRef`` proxy is encountered whose underlying
    subject is already being visited, the original ``{"$ref": "..."}`` dict is
    returned instead of recursing.
    """
    if isinstance(obj, dict):
        # JsonRef proxies are dict subclasses — check for circularity before
        # recursing into their contents.
        if isinstance(obj, jsonref.JsonRef):
            subject_id = id(obj.__subject__)  # type: ignore[attr-defined]
            if subject_id in _seen:
                ref_info = obj.__reference__  # type: ignore[attr-defined]
                if isinstance(ref_info, dict) and "$ref" in ref_info:
                    return {"$ref": ref_info["$ref"]}
                return {}

        obj_id = id(obj)
        if obj_id in _seen:
            # Plain dict that is its own ancestor — skip to break the cycle.
            return {}
        _seen.add(obj_id)
        result = {k: _deep_copy(v, _seen) for k, v in obj.items()}
        _seen.discard(obj_id)
        return result
    if isinstance(obj, list):
        return [_deep_copy(item, _seen) for item in obj]
    return obj
