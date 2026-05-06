"""Template context builder for model generation.

Builds the Jinja2 context dict consumed by the model.py.jinja2 template.
"""

from __future__ import annotations

from typing import Any

from pyoas.core.analysis import _GenericGroup, has_circular_refs
from pyoas.core.config import Config

from .schema_renderer import _render_generic_base_schema, _render_schema
from .types import required_imports


def _build_models_context(
    tag: str,
    schemas: list[dict[str, Any]],
    config: Config,
    schema_tag_map: dict[str, set[str]],
    request_only_names: set[str],
    generic_groups: dict[str, _GenericGroup] | None = None,
) -> dict[str, Any]:
    """Build the Jinja2 context dict for the model.py.jinja2 template."""
    generic_groups = generic_groups or {}

    # Build reverse maps: original_schema_name → (_GenericGroup, type_param)
    concrete_to_group: dict[str, _GenericGroup] = {}
    concrete_to_type_param: dict[str, str] = {}
    for group in generic_groups.values():
        for inst in group.instances:
            concrete_to_group[inst["schema_name"]] = group
            concrete_to_type_param[inst["schema_name"]] = inst["type_param"]

    rendered_schemas: list[dict[str, Any]] = []

    for s in schemas:
        schema_extra = (
            config.model_config.request_extra
            if s["name"] in request_only_names
            else config.model_config.extra
        )

        # Virtual generic base schemas are injected directly.
        if s.get("_is_generic_base"):
            generic_group: _GenericGroup = s["_group"]
            base = _render_generic_base_schema(generic_group, s, config)
            base["extra"] = schema_extra
            rendered_schemas.append(base)
            continue

        # Concrete generic schemas become type aliases instead of full classes.
        if s["name"] in concrete_to_group:
            group = concrete_to_group[s["name"]]
            type_param = concrete_to_type_param[s["name"]]
            alias_type = f"{group.generic_name}[{type_param}]"
            clean_name = group.generic_name + type_param

            # Primary clean alias: PaginatedDriverListItem = Paginated[DriverListItem]
            rendered_schemas.append(
                {
                    "name": clean_name,
                    "is_alias": True,
                    "alias_type": alias_type,
                    "description": None,
                    "extra": schema_extra,
                }
            )
            # Spec-compat alias (only when original name differs from clean name).
            # Marked internal so it is not re-exported from __init__.py.
            if s["name"] != clean_name:
                rendered_schemas.append(
                    {
                        "name": s["name"],
                        "is_alias": True,
                        "is_internal": True,
                        "alias_type": clean_name,
                        "description": None,
                        "extra": schema_extra,
                    }
                )
            continue

        # Regular schema — render normally.
        new_schemas = _render_schema(s, config)
        for rs in new_schemas:
            # Write variants are always request schemas regardless of origin.
            if not rs.get("is_alias") and rs["name"].endswith("Write"):
                rs["extra"] = config.model_config.request_extra
            else:
                rs["extra"] = schema_extra
            rs.setdefault("is_generic", False)
            rs.setdefault("type_params", [])
        rendered_schemas.extend(new_schemas)

    # Type aliases are evaluated at import time (not lazy like annotations), so
    # they must appear after all class definitions they reference.
    rendered_schemas.sort(key=lambda rs: 1 if rs.get("is_alias") else 0)

    all_imports: set[str] = set()
    needs_any = False
    needs_literal = False
    needs_annotated = False
    needs_tag_discriminator = False
    needs_generic = any(rs.get("is_generic") for rs in rendered_schemas)
    needs_str_enum = any(
        rs.get("is_enum_class") and rs.get("enum_type") == "StrEnum"
        for rs in rendered_schemas
    )
    needs_int_enum = any(
        rs.get("is_enum_class") and rs.get("enum_type") == "IntEnum"
        for rs in rendered_schemas
    )

    for rs in rendered_schemas:
        if rs.get("is_alias"):
            alias_type = rs.get("alias_type", "")
            if "Any" in alias_type:
                needs_any = True
            if "Literal[" in alias_type:
                needs_literal = True
            if "Annotated[" in alias_type:
                needs_annotated = True
            if "Tag(" in alias_type:
                needs_tag_discriminator = True
            for imp in required_imports(alias_type):
                all_imports.add(imp)
        else:
            for f in rs.get("fields", []):
                for imp in required_imports(f["python_type"]):
                    all_imports.add(imp)
                if "Any" in f["python_type"]:
                    needs_any = True
                if "Literal[" in f["python_type"]:
                    needs_literal = True
                if f["constraints"] or "Annotated[" in f["python_type"]:
                    needs_annotated = True
                if "Tag(" in f["python_type"]:
                    needs_tag_discriminator = True

    # Compute cross-module imports: shared schemas and generic bases referenced
    # by this tag's models.
    shared_imports: list[str] = []
    if tag != "shared":
        shared_schema_names = {n for n, tags in schema_tag_map.items() if len(tags) > 1}
        # Generic bases in shared are virtual — add them manually.
        generic_bases_in_shared = {
            g.generic_name for g in generic_groups.values() if g.home_tag is None
        }
        all_shared_names = shared_schema_names | generic_bases_in_shared

        referenced_shared: set[str] = set()
        for rs in rendered_schemas:
            if rs.get("is_alias"):
                for sname in all_shared_names:
                    if sname in rs.get("alias_type", ""):
                        referenced_shared.add(sname)
            else:
                for f in rs.get("fields", []):
                    for sname in all_shared_names:
                        if sname in f["python_type"]:
                            referenced_shared.add(sname)
                # Also check base class names used in inheritance
                for base_name in rs.get("bases", []):
                    if base_name in all_shared_names:
                        referenced_shared.add(base_name)
        shared_imports = sorted(referenced_shared)

    # Detect circular references using the raw schemas available in this tag.
    # Build a mini components_schemas dict so _find_referenced_schemas can follow $refs.
    mini_components = {
        s["name"]: s["raw_schema"]
        for s in schemas
        if s.get("raw_schema") and not s.get("_is_generic_base")
    }
    has_circular = has_circular_refs(list(mini_components), mini_components)

    return {
        "tag": tag,
        "schemas": rendered_schemas,
        "imports": sorted(all_imports),
        "needs_any": needs_any,
        "needs_literal": needs_literal,
        "needs_annotated": needs_annotated,
        "needs_tag_discriminator": needs_tag_discriminator,
        "needs_generic": needs_generic,
        "needs_str_enum": needs_str_enum,
        "needs_int_enum": needs_int_enum,
        "type_vars": ["T"] if needs_generic else [],
        "model_config": config.model_config,
        "shared_imports": shared_imports,
        "has_circular": has_circular,
    }
