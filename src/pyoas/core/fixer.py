"""Auto-fix common OpenAPI spec issues detected by pyoas doctor.

fix_spec() is the single public entry point.  It accepts a raw spec dict and
a Config, applies all fixes in a deterministic order, and returns the mutated
spec plus a list of FixAction objects describing every change made.

Mutation order (later steps depend on earlier ones being stable):
  1. assign_missing_operation_ids — add operationId where absent
  2. dedupe_operation_ids         — suffix duplicates with _2, _3, …
  3. normalize_tags               — collapse tag-collision groups to one form
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import yaml

from pyoas.core.tags import HTTP_METHODS
from pyoas.core.utils import generate_function_name, tag_to_dirname


@dataclass
class FixAction:
    """A single mutation applied (or proposed) by the fixer."""

    kind: str  # "assign_operation_id" | "dedupe_operation_id"
    # | "normalize_tag" | "normalize_tags_list"
    location: str  # e.g. "GET /pets" or "spec.tags[0]"
    before: str  # original value
    after: str  # new value
    message: str  # human-readable description


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fix_spec(
    spec_raw: dict[str, Any],
    cfg: Any,  # noqa: ARG001 — reserved for future config-driven fix options
    *,
    tag_casing: str = "title",
) -> tuple[dict[str, Any], list[FixAction]]:
    """Apply all auto-fixes to *spec_raw* and return (fixed_spec, actions).

    The input dict is never mutated; a deep copy is taken at the start.
    *cfg* is accepted for future extensibility but is not read currently.
    *tag_casing* controls canonical tag form: ``"title"`` or ``"lower"``.
    """
    spec = copy.deepcopy(spec_raw)
    actions: list[FixAction] = []

    actions.extend(assign_missing_operation_ids(spec))
    actions.extend(dedupe_operation_ids(spec))
    actions.extend(normalize_tags(spec, casing=tag_casing))

    return spec, actions


# ---------------------------------------------------------------------------
# Fix 1: assign missing operationIds
# ---------------------------------------------------------------------------


def assign_missing_operation_ids(spec: dict[str, Any]) -> list[FixAction]:
    """Mutate *spec* in-place: assign operationId to every operation missing one.

    The candidate name is ``generate_function_name(method, path)``.  If that
    name already exists elsewhere in the spec, a numeric suffix (_2, _3, …) is
    appended until the name is unique.

    Returns a FixAction for each assignment made.
    """
    actions: list[FixAction] = []
    existing_ids = _collect_all_op_ids(spec)

    for method, path, operation in _iter_operations(spec):
        if operation.get("operationId"):
            continue

        candidate = generate_function_name(method, path)
        unique_id = _make_unique(candidate, existing_ids)
        operation["operationId"] = unique_id
        existing_ids.add(unique_id)

        location = f"{method.upper()} {path}"
        actions.append(
            FixAction(
                kind="assign_operation_id",
                location=location,
                before="",
                after=unique_id,
                message=f"assigned operationId '{unique_id}'",
            )
        )

    return actions


# ---------------------------------------------------------------------------
# Fix 2: deduplicate operationIds
# ---------------------------------------------------------------------------


def dedupe_operation_ids(spec: dict[str, Any]) -> list[FixAction]:
    """Mutate *spec* in-place: resolve duplicate operationIds.

    The first occurrence of a duplicated id is left unchanged.  Subsequent
    occurrences are renamed to ``id_2``, ``id_3``, … avoiding any name already
    present in the spec.

    Returns a FixAction for each rename.
    """
    actions: list[FixAction] = []
    seen: set[str] = set()
    all_ids = _collect_all_op_ids(spec)

    for method, path, operation in _iter_operations(spec):
        op_id = operation.get("operationId")
        if not op_id:
            continue

        if op_id not in seen:
            seen.add(op_id)
            continue

        # Duplicate — find a suffixed name not already in the spec
        new_id = _make_unique(op_id, all_ids)
        operation["operationId"] = new_id
        all_ids.add(new_id)
        seen.add(new_id)

        location = f"{method.upper()} {path}"
        actions.append(
            FixAction(
                kind="dedupe_operation_id",
                location=location,
                before=op_id,
                after=new_id,
                message=f"renamed duplicate operationId '{op_id}' → '{new_id}'",
            )
        )

    return actions


# ---------------------------------------------------------------------------
# Fix 3: normalize tags
# ---------------------------------------------------------------------------


def normalize_tags(
    spec: dict[str, Any],
    *,
    casing: str = "title",
) -> list[FixAction]:
    """Mutate *spec* in-place: rewrite tags to a consistent casing form.

    Tags that share the same ``tag_to_dirname()`` value (a collision) are all
    rewritten to the same canonical form: the alphabetically first original tag
    value with *casing* applied.

    Two passes:
    1. Rewrite ``tags[]`` lists inside each operation.
    2. Rewrite ``spec["tags"][].name`` entries at the top level.

    Returns a FixAction for every value that actually changed.
    """
    tag_map = _build_canonical_tag_map(spec, casing)
    actions: list[FixAction] = []

    # Pass 1: operation-level tags
    for method, path, operation in _iter_operations(spec):
        raw_tags: list[Any] = operation.get("tags") or []
        new_tags: list[str] = []
        changed = False
        for tag in raw_tags:
            if not isinstance(tag, str):
                new_tags.append(str(tag))
                continue
            canonical: str = tag_map.get(tag, tag)
            new_tags.append(canonical)
            if canonical != tag:
                changed = True
                actions.append(
                    FixAction(
                        kind="normalize_tag",
                        location=f"{method.upper()} {path}",
                        before=tag,
                        after=canonical,
                        message=f"normalized tag '{tag}' → '{canonical}'",
                    )
                )
        if changed:
            operation["tags"] = new_tags

    # Pass 2: top-level tags array
    for i, tag_obj in enumerate(spec.get("tags") or []):
        if not isinstance(tag_obj, dict):
            continue
        name: str | None = tag_obj.get("name")
        if not isinstance(name, str):
            continue
        tag_canonical: str = tag_map.get(name, name)
        if tag_canonical != name:
            tag_obj["name"] = tag_canonical
            actions.append(
                FixAction(
                    kind="normalize_tags_list",
                    location=f"spec.tags[{i}]",
                    before=name,
                    after=tag_canonical,
                    message=f"normalized top-level tag '{name}' → '{tag_canonical}'",
                )
            )

    return actions


def _build_canonical_tag_map(
    spec: dict[str, Any],
    casing: str,
) -> dict[str, str]:
    """Return {original_tag: canonical_tag} for every tag in the spec.

    Tags that do not collide and are already in the desired casing form map to
    themselves (no change will be emitted for them).  Collision groups pick the
    alphabetically first original tag as the representative, then apply casing.
    """
    # Collect all distinct tag values from operations and top-level tags array
    all_tags: set[str] = set()
    for _, _, operation in _iter_operations(spec):
        for tag in operation.get("tags") or []:
            if isinstance(tag, str):
                all_tags.add(tag)
    for tag_obj in spec.get("tags") or []:
        if isinstance(tag_obj, dict) and isinstance(tag_obj.get("name"), str):
            all_tags.add(tag_obj["name"])

    # Group by dirname
    dirname_to_group: dict[str, list[str]] = {}
    for tag in all_tags:
        key = tag_to_dirname(tag)
        dirname_to_group.setdefault(key, []).append(tag)

    tag_map: dict[str, str] = {}
    for group in dirname_to_group.values():
        if len(group) == 1:
            # No collision — casing-only changes are not applied to non-conflicting tags
            continue
        # Collision group: pick alphabetically first original, apply casing
        representative = sorted(group)[0]
        canonical = _apply_casing(representative, casing)
        for tag in group:
            tag_map[tag] = canonical

    return tag_map


def _apply_casing(tag: str, casing: str) -> str:
    """Apply *casing* transformation to *tag*.

    ``"title"`` → ``str.title()``  (e.g. "pet store" → "Pet Store")
    ``"lower"`` → ``str.lower()``  (e.g. "Pet Store" → "pet store")
    Any other value leaves the tag unchanged.
    """
    if casing == "title":
        return tag.title()
    if casing == "lower":
        return tag.lower()
    return tag


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def serialize_spec(spec: dict[str, Any], suffix: str) -> str:
    """Serialise *spec* to a string in the format implied by *suffix*.

    ``.json`` → ``json.dumps`` with indent 2.
    Anything else → ``yaml.dump`` with block style and unicode preserved.
    """
    if suffix.lower() == ".json":
        return json.dumps(spec, indent=2, ensure_ascii=False)
    return yaml.dump(spec, default_flow_style=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _collect_all_op_ids(spec: dict[str, Any]) -> set[str]:
    """Return the set of all operationIds currently present in *spec*."""
    ids: set[str] = set()
    for _, _, operation in _iter_operations(spec):
        op_id = operation.get("operationId")
        if isinstance(op_id, str) and op_id:
            ids.add(op_id)
    return ids


def _iter_operations(
    spec: dict[str, Any],
) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Yield ``(method, path, operation_dict)`` for every HTTP operation in spec."""
    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue
            yield method, path, operation


def _make_unique(name: str, existing: set[str]) -> str:
    """Return *name* if it is not in *existing*, else append _2, _3, … until free."""
    if name not in existing:
        return name
    i = 2
    while True:
        candidate = f"{name}_{i}"
        if candidate not in existing:
            return candidate
        i += 1
