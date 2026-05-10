"""
RouterGenerator — orchestrates FastAPI router generation from an OpenAPI spec.

Milestone 3 will fill in the complete implementation.
"""

from __future__ import annotations

import json as _json
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from pyoas.core.analysis import (
    build_schema_tag_map,
    collect_inline_schemas,
    detect_generic_groups_global,
    find_split_schema_names,
)
from pyoas.core.cache import GenerationCache, compute_config_hash, compute_tag_hash
from pyoas.core.config import Config
from pyoas.core.parsed_spec import ParsedSpec
from pyoas.core.renderer import Renderer
from pyoas.core.tags import extract_tags
from pyoas.core.utils import (
    derive_import_path,
    ensure_intermediate_inits,
    format_output,
    generate_function_name,
    spec_hash_of_file,
    tag_to_dirname,
    to_pascal_case,
    to_snake_case,
)
from pyoas.models.types import required_imports

from .params import (
    build_function_params,
    resolve_response_status_code,
    resolve_response_type,
)

_DEFAULT_TEMPLATES = Path(__file__).parent / "templates"


class RouterGenerator:
    def __init__(self, config: Config) -> None:
        self._config = config
        from pyoas.core.plugins import load_plugins

        self._plugins = load_plugins(config)

    def generate(
        self,
        tag_filter: list[str] | None = None,
        clean: bool = False,
        *,
        parsed_spec: ParsedSpec | None = None,
        progress_callback: Callable[[str], None] | None = None,
        verbose: bool = False,
    ) -> list[Path]:
        """
        Generate FastAPI routers for all tags (or a subset via ``tag_filter``).

        All files under the configured output directory are fully overwritten.
        If ``clean`` is True, the output directory is purged before generation.
        Pass a pre-built ``ParsedSpec`` via *parsed_spec* to avoid loading and
        resolving the spec file twice when running ``generate`` (which calls both
        ModelGenerator and RouterGenerator).
        Returns the list of files written.
        """
        cfg = self._config
        spec_hash = spec_hash_of_file(cfg.spec)
        if parsed_spec is None:
            parsed_spec = ParsedSpec.from_config(cfg)
        spec_raw: dict = parsed_spec.raw
        spec: dict = parsed_spec.resolved

        if spec_raw.get("webhooks") and not cfg.webhooks.generate:
            typer.echo(
                "Warning: spec contains webhooks that are not being generated. "
                "Set webhooks.generate: true in pyoas.yaml to enable.",
                err=True,
            )

        include_webhooks = cfg.webhooks.generate
        grouped = extract_tags(
            spec, default_tag=cfg.default_tag, include_webhooks=include_webhooks
        )
        grouped_raw = extract_tags(
            spec_raw, default_tag=cfg.default_tag, include_webhooks=include_webhooks
        )

        if tag_filter:
            grouped = {k: v for k, v in grouped.items() if k in tag_filter}
            grouped_raw = {k: v for k, v in grouped_raw.items() if k in tag_filter}

        # Build generic name map: {mangled_schema_name: "GenericName[TypeParam]"}
        raw_cs = spec_raw.get("components", {}).get("schemas", {})
        grouped_raw_all = extract_tags(
            spec_raw, default_tag=cfg.default_tag, include_webhooks=include_webhooks
        )
        schema_tag_map = build_schema_tag_map(spec_raw, grouped_raw_all)
        generic_groups = detect_generic_groups_global(raw_cs, schema_tag_map)
        generic_name_map: dict[str, str] = {
            inst["schema_name"]: f"{g.generic_name}[{inst['type_param']}]"
            for g in generic_groups.values()
            for inst in g.instances
        }
        split_schema_names = find_split_schema_names(spec_raw)
        global_security: list[Any] = spec_raw.get("security") or []
        inline_by_tag, _ = collect_inline_schemas(grouped, grouped_raw)
        inline_schema_tag_map: dict[str, str] = {
            entry["name"]: tag
            for tag, entries in inline_by_tag.items()
            for entry in entries
        }

        user_tmpl_dir = Path(cfg.templates.routers) if cfg.templates.routers else None
        renderer = Renderer(
            default_templates_dir=_DEFAULT_TEMPLATES,
            user_templates_dir=user_tmpl_dir,
            extensions_config=cfg.extensions,
        )

        output_root = Path(cfg.output.routers)
        if clean and output_root.exists():
            if tag_filter:
                # Selective clean: only remove the files for the filtered tags so
                # other tags' output is not destroyed.
                for tag in tag_filter:
                    (output_root / f"{tag_to_dirname(tag)}.py").unlink(missing_ok=True)
            else:
                shutil.rmtree(output_root, ignore_errors=True)

        output_root.mkdir(parents=True, exist_ok=True)

        use_cache = not clean
        cache = (
            GenerationCache.load(output_root / ".pyoas_cache.json")
            if use_cache
            else GenerationCache(output_root / ".pyoas_cache.json")
        )
        config_hash = compute_config_hash(cfg) if use_cache else ""

        written: list[Path] = []
        for tag, operations in grouped.items():
            raw_operations = grouped_raw.get(tag, [])
            # Attach the raw (unresolved) operation so params can recover $ref names.
            merged = [
                {**op, "raw_operation": raw_op["operation"]}
                for op, raw_op in zip(operations, raw_operations)
            ]
            _tag_hash = ""
            if use_cache:
                _content_json = _json.dumps(
                    {"tag": tag, "operations": raw_operations},
                    sort_keys=True,
                    default=str,
                )
                _tag_hash = compute_tag_hash(tag, _content_json, config_hash)
                _out_file = output_root / f"{tag_to_dirname(tag)}.py"
                if cache.is_current(tag, _tag_hash) and _out_file.exists():
                    if progress_callback:
                        progress_callback(f"[routers] {tag} (unchanged, skipped)")
                    written.append(_out_file)
                    continue
            _t0 = time.perf_counter()
            self._write_tag(
                tag,
                merged,
                renderer,
                output_root,
                generic_name_map,
                schema_tag_map=schema_tag_map,
                generic_groups=generic_groups,
                split_schema_names=split_schema_names,
                inline_schema_tag_map=inline_schema_tag_map,
                global_security=global_security,
                spec_hash=spec_hash,
            )
            written.append(output_root / f"{tag_to_dirname(tag)}.py")
            if use_cache:
                cache.update(tag, _tag_hash)
            if progress_callback:
                msg = f"[routers] {tag} ({len(merged)} endpoints)"
                if verbose:
                    msg += f"  {int((time.perf_counter() - _t0) * 1000)}ms"
                progress_callback(msg)

        all_tags = list(grouped.keys())
        webhook_tag_set: set[str] = (
            {
                tag
                for tag, ops in grouped.items()
                if any(op.get("is_webhook") for op in ops)
            }
            if include_webhooks
            else set()
        )
        tag_entries = [
            {
                "name": t,
                "dirname": tag_to_dirname(t),
                "has_webhooks": t in webhook_tag_set,
            }
            for t in all_tags
        ]
        root_init = renderer.render(
            "init.py.jinja2",
            {"tags": tag_entries, "is_root": True, "spec_hash": spec_hash},
        )
        init_path = output_root / "__init__.py"
        init_path.write_text(root_init, encoding="utf-8")
        written.append(init_path)
        ensure_intermediate_inits(
            output_root,
            cfg.output.source_root,
            project_root=Path(cfg.spec).parent,
        )

        if use_cache:
            cache.save()

        if cfg.format.enabled:
            format_output(output_root)

        return written

    def _write_tag(
        self,
        tag: str,
        operations: list[dict[str, Any]],
        renderer: Renderer,
        output_root: Path,
        generic_name_map: dict[str, str] | None = None,
        schema_tag_map: dict[str, set[str]] | None = None,
        generic_groups: dict[str, Any] | None = None,
        split_schema_names: set[str] | None = None,
        inline_schema_tag_map: dict[str, str] | None = None,
        global_security: list[Any] | None = None,
        spec_hash: str = "",
    ) -> None:
        context = _build_router_context(
            tag,
            operations,
            self._config,
            generic_name_map,
            schema_tag_map=schema_tag_map,
            generic_groups=generic_groups,
            split_schema_names=split_schema_names,
            inline_schema_tag_map=inline_schema_tag_map,
            global_security=global_security,
        )
        context["spec_hash"] = spec_hash
        router_src = renderer.render("router.py.jinja2", context)
        out_path = output_root / f"{tag_to_dirname(tag)}.py"
        for plugin in self._plugins:
            result = plugin.on_router_file_written(tag, str(out_path), router_src)
            if not result:
                from pyoas.core.plugins import PluginError

                raise PluginError(
                    f"Plugin {plugin.name!r} returned empty content from"
                    f" on_router_file_written for tag {tag!r}"
                )
            router_src = result
        out_path.write_text(router_src, encoding="utf-8")


# ---------------------------------------------------------------------------
# Model import helpers
# ---------------------------------------------------------------------------

_STDLIB_NAMES: frozenset[str] = frozenset(
    {
        "Any",
        "None",
        "Optional",
        "Union",
        "Annotated",
        "Generic",
        "TypeVar",
        "List",
        "Dict",
        "Tuple",
        "Set",
        "FrozenSet",
    }
)


def _extract_model_class_names(type_strings: list[str]) -> set[str]:
    """Return PascalCase identifiers from type annotation strings.

    Strips ``Literal[...]`` substrings first so that enum values like
    ``Literal["available", "pending"]`` don't contribute tokens.
    """
    combined = " ".join(type_strings)
    combined = re.sub(r"Literal\[[^\]]*\]", "", combined)
    return {
        t
        for t in re.findall(r"\b([A-Z][A-Za-z0-9_]*)\b", combined)
        if t not in _STDLIB_NAMES
    }


def _classify_model_imports(
    class_names: set[str],
    tag: str,
    schema_tag_map: dict[str, set[str]],
    generic_groups: dict[str, Any],
    split_schema_names: set[str] | None = None,
    inline_schema_tag_map: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Partition *class_names* into ``(tag_local, shared)``.

    Classification rules (in order):
    - Generic group base names (e.g. ``Paginated``) whose home_tag == tag → tag-local
    - Generic group base names whose home_tag is None or != tag → shared
    - In schema_tag_map with >1 tags → shared
    - In schema_tag_map with exactly 1 tag == *tag* → tag-local
    - In schema_tag_map with exactly 1 tag != *tag* → shared (cross-tag ref)
    - Not in schema_tag_map → stdlib/builtin, skip entirely

    Split schema variants (``{Name}Read``, ``{Name}Write``) are resolved to
    their base name for tag-map lookup.
    """
    generic_base_names = set(generic_groups.keys())
    tag_local: list[str] = []
    shared: list[str] = []
    for name in sorted(class_names):
        # Resolve split schema variants to their base name for lookup.
        lookup_name = name
        if split_schema_names:
            for suffix in ("Read", "Write"):
                if name.endswith(suffix):
                    candidate = name[: -len(suffix)]
                    if candidate in split_schema_names:
                        lookup_name = candidate
                        break

        if lookup_name in generic_base_names:
            if generic_groups[lookup_name].home_tag == tag:
                tag_local.append(name)
            else:
                shared.append(name)
        elif lookup_name in schema_tag_map:
            tags = schema_tag_map[lookup_name]
            if len(tags) > 1:
                shared.append(name)
            elif next(iter(tags)) == tag:
                tag_local.append(name)
            else:
                shared.append(name)
        elif (inline_schema_tag_map or {}).get(lookup_name) == tag:
            tag_local.append(name)
        # else: not a model schema (e.g. uuid.UUID → "UUID") — skip
    return tag_local, shared


# ---------------------------------------------------------------------------
# Template context builder
# ---------------------------------------------------------------------------


def _build_router_context(
    tag: str,
    operations: list[dict[str, Any]],
    config: Config,
    generic_name_map: dict[str, str] | None = None,
    schema_tag_map: dict[str, set[str]] | None = None,
    generic_groups: dict[str, Any] | None = None,
    split_schema_names: set[str] | None = None,
    inline_schema_tag_map: dict[str, str] | None = None,
    global_security: list[Any] | None = None,
) -> dict[str, Any]:
    rendered_ops = [
        _render_operation(
            op, config, generic_name_map, split_schema_names, global_security
        )
        for op in operations
    ]
    # Static path segments must be registered before parameterized ones so FastAPI
    # matches them correctly (e.g. /items/search before /items/{id}).
    rendered_ops.sort(key=lambda op: re.sub(r"\{[^}]+\}", "\xff", op["path"]))

    # Warn on duplicate function names within the tag (usually caused by duplicate operationIds).
    _seen_fn: dict[str, str] = {}
    for op in rendered_ops:
        key = op["function_name"]
        loc = f"{op['method'].upper()} {op['path']}"
        if key in _seen_fn:
            typer.echo(
                f"Warning: duplicate function name '{key}' in tag '{tag}' "
                f"({_seen_fn[key]} and {loc}). Check operationId values.",
                err=True,
            )
        else:
            _seen_fn[key] = loc

    # Collect all type annotation strings to determine stdlib imports and model imports.
    all_type_strings: list[str] = []
    for op in rendered_ops:
        for param in op["parameters"]:
            all_type_strings.append(param["python_type"])
        if op["response_type"]:
            all_type_strings.append(op["response_type"])

    combined = " ".join(all_type_strings)
    stdlib_imports = sorted(set(required_imports(combined)))
    needs_any = "Any" in combined
    needs_annotated = "Annotated[" in combined
    needs_literal = "Literal[" in combined

    # Collect FastAPI parameter annotation classes (Query, Path, etc.) used by any param.
    # Also include UploadFile when used as a plain type (file upload fields).
    fastapi_param_classes: list[str] = sorted(
        {
            p["fastapi_class"]
            for op in rendered_ops
            for p in op["parameters"]
            if p.get("fastapi_class")
        }
        | ({"UploadFile"} if "UploadFile" in combined else set())
    )

    tag_dirname = tag_to_dirname(tag)
    service_class_name = to_pascal_case(tag_dirname) + "Service"
    service_dep_fn = f"get_{tag_dirname}_service"

    models_import_path = config.output.models_import or derive_import_path(
        config.output.models, config.output.source_root
    )

    class_names = _extract_model_class_names(all_type_strings)
    tag_local_names, shared_names = _classify_model_imports(
        class_names,
        tag,
        schema_tag_map or {},
        generic_groups or {},
        split_schema_names,
        inline_schema_tag_map or {},
    )
    tag_model_imports = (
        [{"module": f"{models_import_path}.{tag_dirname}", "names": tag_local_names}]
        if tag_local_names
        else []
    )
    shared_model_imports = (
        [{"module": f"{models_import_path}.shared", "names": shared_names}]
        if shared_names
        else []
    )

    has_any_security = any(op["has_security"] for op in rendered_ops)
    has_webhooks = any(op.get("is_webhook") for op in rendered_ops)
    needs_fastapi_response = any(
        op["response_type"] == "Response" for op in rendered_ops
    )
    dep_import_path = config.dependencies.import_path or None

    return {
        "tag": tag,
        "has_webhooks": has_webhooks,
        "tag_dirname": tag_dirname,
        "operations": rendered_ops,
        "tag_model_imports": tag_model_imports,
        "shared_model_imports": shared_model_imports,
        "service_import_path": config.services.import_path or None,
        "service_class_name": service_class_name,
        "service_dep_fn": service_dep_fn,
        "dep_import_path": dep_import_path,
        "has_any_security": has_any_security,
        "needs_fastapi_response": needs_fastapi_response,
        "stdlib_imports": stdlib_imports,
        "needs_any": needs_any,
        "needs_annotated": needs_annotated,
        "needs_literal": needs_literal,
        "fastapi_param_classes": fastapi_param_classes,
        "response_model_exclude_none": config.router.response_model_exclude_none,
        "response_model_exclude_unset": config.router.response_model_exclude_unset,
    }


def _has_security(operation: dict[str, Any], global_security: list[Any]) -> bool:
    """Return True if this operation requires authentication."""
    op_security = operation.get("security")
    if op_security is not None:
        return len(op_security) > 0
    return len(global_security) > 0


def _extract_security_scopes(
    operation: dict[str, Any], global_security: list[Any]
) -> list[str]:
    """Return a deduplicated list of OAuth2/scope strings required by this operation.

    Falls back to *global_security* when the operation has no ``security`` key.
    Returns ``[]`` when ``security: []`` is set (explicit opt-out of auth).
    """
    op_security = operation.get("security")
    effective: list[Any] = op_security if op_security is not None else global_security
    scopes: list[str] = []
    for requirement in effective:
        if not isinstance(requirement, dict):
            continue
        for scope_list in requirement.values():
            if isinstance(scope_list, list):
                for scope in scope_list:
                    if scope not in scopes:
                        scopes.append(scope)
    return scopes


def _render_operation(
    op_entry: dict[str, Any],
    config: Config,
    generic_name_map: dict[str, str] | None = None,
    split_schema_names: set[str] | None = None,
    global_security: list[Any] | None = None,
) -> dict[str, Any]:
    method: str = op_entry["method"]
    path: str = op_entry["path"]
    operation: dict[str, Any] = op_entry["operation"]
    raw_operation: dict[str, Any] | None = op_entry.get("raw_operation")
    is_webhook: bool = op_entry.get("is_webhook", False)

    operation_id = operation.get("operationId")
    if operation_id:
        # Sanitize non-identifier chars (dashes, dots, spaces) before snake_case conversion.
        function_name = to_snake_case(re.sub(r"[^a-zA-Z0-9_]", "_", operation_id))
    else:
        function_name = generate_function_name(method, path)

    params = build_function_params(
        operation,
        raw_operation=raw_operation,
        enums_as_literals=config.fields.enums_as_literals,
        generic_name_map=generic_name_map,
        split_schema_names=split_schema_names,
    )
    response_type = resolve_response_type(
        operation,
        raw_operation=raw_operation,
        enums_as_literals=config.fields.enums_as_literals,
        generic_name_map=generic_name_map,
    )
    status_code = resolve_response_status_code(operation)

    return {
        "method": method,
        "path": path,
        "function_name": function_name,
        "summary": operation.get("summary", ""),
        "description": operation.get("description", ""),
        "parameters": params,
        "response_type": response_type,
        "status_code": status_code,
        "deprecated": operation.get("deprecated", False),
        "operation_id": operation.get("operationId"),
        "has_security": _has_security(operation, global_security or []),
        "required_scopes": _extract_security_scopes(operation, global_security or []),
        "x_extensions": {k: v for k, v in operation.items() if k.startswith("x-")},
        "is_webhook": is_webhook,
    }
