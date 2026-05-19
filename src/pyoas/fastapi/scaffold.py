"""
ServiceScaffolder — writes service stub files, adding missing methods on re-runs.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

import typer

from pyoas.core.analysis import (
    build_schema_tag_map,
    collect_inline_schemas,
    detect_generic_groups_global,
    find_split_schema_names,
)
from pyoas.core.config import Config
from pyoas.core.parser import SpecParser
from pyoas.core.renderer import Renderer
from pyoas.core.resolver import resolve_refs
from pyoas.core.result import ScaffoldResult
from pyoas.core.tags import extract_tags
from pyoas.core.utils import (
    derive_import_path,
    generate_function_name,
    tag_to_dirname,
    to_pascal_case,
    to_snake_case,
)
from pyoas.models.types import required_imports

from .generator import (
    _classify_model_imports,
    _extract_model_class_names,
    _has_security,
)
from .params import _annotated_base_type, build_function_params, resolve_response_type

_DEFAULT_TEMPLATES = Path(__file__).parent / "templates"


class ServiceScaffolder:
    def __init__(self, config: Config) -> None:
        self._config = config

    def scaffold(self, tag_filter: list[str] | None = None) -> ScaffoldResult:
        result = ScaffoldResult()
        cfg = self._config
        if not cfg.services.generate and not cfg.services.import_path:
            typer.echo(
                "Service generation is not configured. Set services.generate: true in config."
            )
            return result

        spec_raw = SpecParser(cfg.spec).load()
        spec = resolve_refs(spec_raw, cfg.spec)
        grouped = extract_tags(spec, default_tag=cfg.default_tag)
        grouped_raw = extract_tags(spec_raw, default_tag=cfg.default_tag)

        if tag_filter:
            grouped = {k: v for k, v in grouped.items() if k in tag_filter}
            grouped_raw = {k: v for k, v in grouped_raw.items() if k in tag_filter}

        global_security: list[Any] = spec_raw.get("security") or []
        raw_cs = spec_raw.get("components", {}).get("schemas", {})
        grouped_raw_all = extract_tags(spec_raw, default_tag=cfg.default_tag)
        schema_tag_map = build_schema_tag_map(spec_raw, grouped_raw_all)
        generic_groups = detect_generic_groups_global(raw_cs, schema_tag_map)
        generic_name_map: dict[str, str] = {
            inst["schema_name"]: f"{g.generic_name}[{inst['type_param']}]"
            for g in generic_groups.values()
            for inst in g.instances
        }
        split_schema_names = find_split_schema_names(spec_raw)
        inline_by_tag, _ = collect_inline_schemas(grouped, grouped_raw)
        inline_schema_tag_map: dict[str, str] = {
            entry["name"]: t
            for t, entries in inline_by_tag.items()
            for entry in entries
        }

        renderer = Renderer(default_templates_dir=_DEFAULT_TEMPLATES)
        output_root = Path(cfg.services.output)

        output_root.mkdir(parents=True, exist_ok=True)

        for tag, operations in grouped.items():
            raw_operations = grouped_raw.get(tag, [])
            merged = [
                {**op, "raw_operation": raw_op["operation"]}
                for op, raw_op in zip(operations, raw_operations, strict=True)
            ]
            tag_result = self._scaffold_tag(
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
            )
            result.wrote += tag_result.wrote
            result.appended_items += tag_result.appended_items
            result.appended_files.extend(tag_result.appended_files)

        # Write root __init__.py once (never overwrite — user may customise it)
        root_init = output_root / "__init__.py"
        if not root_init.exists():
            root_init.write_text(
                "# Scaffolded by pyoas — safe to edit.\n", encoding="utf-8"
            )
        return result

    def _scaffold_tag(
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
    ) -> ScaffoldResult:
        import re

        tag_result = ScaffoldResult()
        tag_dirname = tag_to_dirname(tag)
        service_file = output_root / f"{tag_dirname}.py"

        context = _build_service_context(
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

        if not service_file.exists() or self._config.services.overwrite:
            src = renderer.render("service.py.jinja2", context)
            service_file.write_text(src, encoding="utf-8")
            typer.echo(typer.style(f"  wrote  {service_file}", fg=typer.colors.GREEN))
            tag_result.wrote = 1
            return tag_result

        # File exists and overwrite=False — add only missing methods.
        existing_src = service_file.read_text(encoding="utf-8")
        existing_methods = set(
            re.findall(r"^\s{4}async def (\w+)\(", existing_src, re.MULTILINE)
        )
        current_ops = {op["function_name"] for op in context["operations"]}
        orphaned = existing_methods - current_ops
        if orphaned:
            for name in sorted(orphaned):
                typer.echo(
                    f"WARNING: {service_file}: method '{name}' has no matching "
                    f"operation in the spec — it may be orphaned.",
                    err=True,
                )
        # Detect signature drift for methods present in both file and spec.
        shared = existing_methods & current_ops
        if shared:
            ops_by_name = {op["function_name"]: op for op in context["operations"]}
            drift_warnings: list[str] = []
            dep_import_path = context.get("dep_import_path")
            for name in sorted(shared):
                expected = _expected_sig_str(ops_by_name[name], dep_import_path)
                actual = _actual_sig_str(existing_src, name)
                if actual is not None and actual != expected:
                    drift_warnings.append(
                        f"DRIFT: {service_file}::{name} — signature changed\n"
                        f"  expected: {expected}\n"
                        f"  actual:   {actual}"
                    )
            if drift_warnings:
                _emit_drift_warnings(drift_warnings, self._config)
        new_ops = [
            op
            for op in context["operations"]
            if op["function_name"] not in existing_methods
        ]
        if not new_ops:
            return tag_result

        dep_import_path = context.get("dep_import_path")
        stubs = _render_method_stubs(new_ops, dep_import_path=dep_import_path)

        # Ensure AuthContext is imported when new secured methods are being added.
        if dep_import_path and any(op.get("has_security") for op in new_ops):
            import_line = f"from {dep_import_path}.auth import AuthContext"
            if import_line not in existing_src:
                import re as _re

                class_match = _re.search(r"^class \w", existing_src, _re.MULTILINE)
                if class_match:
                    pos = class_match.start()
                    existing_src = (
                        existing_src[:pos] + import_line + "\n\n" + existing_src[pos:]
                    )
                else:
                    existing_src = import_line + "\n\n" + existing_src

        dep_fn = f"async def get_{tag_dirname}_service"
        if dep_fn in existing_src:
            insert_at = existing_src.index(dep_fn)
            updated = existing_src[:insert_at] + stubs + "\n" + existing_src[insert_at:]
        else:
            updated = existing_src.rstrip() + "\n\n" + stubs

        service_file.write_text(updated, encoding="utf-8")
        typer.echo(
            typer.style(
                f"  added  {len(new_ops)} method(s) to {service_file}",
                fg=typer.colors.GREEN,
            )
        )
        tag_result.appended_items = len(new_ops)
        tag_result.appended_files = [tag_dirname]
        return tag_result


@dataclass
class DriftItem:
    """A single drift finding from detect_service_drift."""

    kind: str  # "missing_file" | "missing_method" | "orphaned_method" | "signature_changed"
    file: str
    method: str | None
    detail: str


def detect_service_drift(
    cfg: Any,
    tag_filter: list[str] | None = None,
) -> list[DriftItem]:
    """Read-only: compare service files on disk against the spec.

    Returns DriftItem entries for missing files, missing methods, orphaned
    methods, and signature changes. Never writes anything.
    """
    from pyoas.core.analysis import (
        build_schema_tag_map,
        collect_inline_schemas,
        detect_generic_groups_global,
        find_split_schema_names,
    )
    from pyoas.core.parser import SpecParser
    from pyoas.core.resolver import resolve_refs
    from pyoas.core.tags import extract_tags

    spec_raw = SpecParser(cfg.spec).load()
    spec = resolve_refs(spec_raw, cfg.spec)
    grouped = extract_tags(spec, default_tag=cfg.default_tag)
    grouped_raw = extract_tags(spec_raw, default_tag=cfg.default_tag)
    if tag_filter:
        grouped = {k: v for k, v in grouped.items() if k in tag_filter}
        grouped_raw = {k: v for k, v in grouped_raw.items() if k in tag_filter}

    global_security: list[Any] = spec_raw.get("security") or []
    raw_cs = spec_raw.get("components", {}).get("schemas", {})
    full_grouped_raw = extract_tags(spec_raw, default_tag=cfg.default_tag)
    schema_tag_map = build_schema_tag_map(spec_raw, full_grouped_raw)
    generic_groups = detect_generic_groups_global(raw_cs, schema_tag_map)
    generic_name_map: dict[str, str] = {
        inst["schema_name"]: f"{g.generic_name}[{inst['type_param']}]"
        for g in generic_groups.values()
        for inst in g.instances
    }
    split_schema_names = find_split_schema_names(spec_raw)
    inline_by_tag, _ = collect_inline_schemas(grouped, grouped_raw)
    inline_schema_tag_map: dict[str, str] = {
        entry["name"]: t for t, entries in inline_by_tag.items() for entry in entries
    }

    items: list[DriftItem] = []
    svc_root = Path(cfg.services.output)

    for tag, operations in grouped.items():
        raw_ops = grouped_raw.get(tag, [])
        merged = [
            {**op, "raw_operation": raw_op["operation"]}
            for op, raw_op in zip(operations, raw_ops, strict=True)
        ]
        context = _build_service_context(
            tag,
            merged,
            cfg,
            generic_name_map,
            schema_tag_map=schema_tag_map,
            generic_groups=generic_groups,
            split_schema_names=split_schema_names,
            inline_schema_tag_map=inline_schema_tag_map,
            global_security=global_security,
        )
        tag_dirname = tag_to_dirname(tag)
        svc_file = svc_root / f"{tag_dirname}.py"
        current_ops = {op["function_name"] for op in context["operations"]}

        if not svc_file.exists():
            items.append(
                DriftItem(
                    kind="missing_file",
                    file=str(svc_file),
                    method=None,
                    detail=f"{svc_file} does not exist",
                )
            )
            continue

        existing_src = svc_file.read_text(encoding="utf-8")
        existing_methods = set(
            re.findall(r"^\s{4}async def (\w+)\(", existing_src, re.MULTILINE)
        )
        # Missing methods (in spec but not in file)
        for fn in sorted(current_ops - existing_methods):
            items.append(
                DriftItem(
                    kind="missing_method",
                    file=str(svc_file),
                    method=fn,
                    detail=f"method '{fn}' is in the spec but missing from {svc_file}",
                )
            )
        # Orphaned methods (in file but not in spec)
        for fn in sorted(existing_methods - current_ops):
            items.append(
                DriftItem(
                    kind="orphaned_method",
                    file=str(svc_file),
                    method=fn,
                    detail=f"method '{fn}' has no matching operation in the spec",
                )
            )
        # Signature drift for methods present in both
        shared = existing_methods & current_ops
        if shared:
            ops_by_name = {op["function_name"]: op for op in context["operations"]}
            dep_import_path = context.get("dep_import_path")
            for fn in sorted(shared):
                expected = _expected_sig_str(ops_by_name[fn], dep_import_path)
                actual = _actual_sig_str(existing_src, fn)
                if actual is not None and actual != expected:
                    items.append(
                        DriftItem(
                            kind="signature_changed",
                            file=str(svc_file),
                            method=fn,
                            detail=(
                                f"signature changed\n"
                                f"  expected: {expected}\n"
                                f"  actual:   {actual}"
                            ),
                        )
                    )

    return items


def _expected_sig_str(op: dict[str, Any], dep_import_path: str | None = None) -> str:
    """Build a normalised signature string from a spec operation dict."""
    parts = [
        f"{p['name']}: {p['python_type']}" + (" = None" if not p["required"] else "")
        for p in op["parameters"]
    ]
    if dep_import_path and op.get("has_security"):
        parts.append("auth: AuthContext")
    if parts:
        return f"(self, *, {', '.join(parts)}) -> {op['response_type']}"
    return f"(self) -> {op['response_type']}"


def _actual_sig_str(src: str, fn_name: str) -> str | None:
    """Extract and normalise the signature of `fn_name` from source text using AST."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == fn_name:
            return _service_sig_from_ast(node)
    return None


def _service_sig_from_ast(func: ast.AsyncFunctionDef) -> str:
    parts = []
    for arg, default in zip(func.args.kwonlyargs, func.args.kw_defaults):
        ann = ast.unparse(arg.annotation).strip() if arg.annotation else ""
        part = f"{arg.arg}: {ann}" if ann else arg.arg
        if default is not None:
            part += f" = {ast.unparse(default)}"
        parts.append(part)
    ret = ast.unparse(func.returns).strip() if func.returns else "None"
    if parts:
        return f"(self, *, {', '.join(parts)}) -> {ret}"
    return f"(self) -> {ret}"


def _emit_drift_warnings(warnings: list[str], config: Config) -> None:
    """Print drift warnings to stderr and optionally append them to a log file."""
    from datetime import datetime

    for w in warnings:
        typer.echo(f"WARNING: {w}", err=True)

    if config.services.drift_log:
        log_path = Path(config.services.drift_log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {timestamp} ---\n")
            for w in warnings:
                f.write(w + "\n")


def _render_method_stubs(
    operations: list[dict[str, Any]], dep_import_path: str | None = None
) -> str:
    lines: list[str] = []
    for op in operations:
        has_auth = bool(dep_import_path and op.get("has_security"))
        lines.append(f"    async def {op['function_name']}(")
        lines.append("        self,")
        if op["parameters"] or has_auth:
            lines.append("        *,")
        for param in op["parameters"]:
            default = " = None" if not param["required"] else ""
            lines.append(f"        {param['name']}: {param['python_type']}{default},")
        if has_auth:
            lines.append("        auth: AuthContext,")
        lines.append(f"    ) -> {op['response_type']}:")
        docstring = op.get("summary") or op.get("description")
        if docstring:
            lines.append(f'        """{docstring}"""')
        lines.append("        raise NotImplementedError")
        lines.append("")
    return "\n".join(lines) + "\n"


class RenderedOperation(TypedDict):
    function_name: str
    parameters: list[dict[str, Any]]
    response_type: str
    summary: str
    description: str
    has_security: bool


def _build_service_context(
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
    rendered_ops: list[RenderedOperation] = []
    for op_entry in operations:
        operation = op_entry["operation"]
        raw_operation = op_entry.get("raw_operation")
        fn_name = to_snake_case(
            operation.get("operationId")
            or generate_function_name(op_entry["method"], op_entry["path"])
        )
        raw_params = build_function_params(
            operation,
            raw_operation=raw_operation,
            enums_as_literals=config.fields.enums_as_literals,
            generic_name_map=generic_name_map,
            split_schema_names=split_schema_names,
        )
        # Strip FastAPI-specific Annotated wrappers (Body, Form, File, Query, Path, …)
        # so service methods are framework-agnostic.
        params = [
            {
                **p,
                "python_type": _annotated_base_type(p["python_type"]),
                "fastapi_class": None,
            }
            for p in raw_params
        ]
        response_type = resolve_response_type(
            operation,
            raw_operation=raw_operation,
            enums_as_literals=config.fields.enums_as_literals,
            generic_name_map=generic_name_map,
        )
        rendered_ops.append(
            {
                "function_name": fn_name,
                "parameters": params,
                "response_type": response_type,
                "summary": operation.get("summary", ""),
                "description": operation.get("description", ""),
                "has_security": _has_security(operation, global_security or []),
            }
        )

    all_type_strings = [op["response_type"] for op in rendered_ops]
    for op in rendered_ops:
        all_type_strings.extend(p["python_type"] for p in op["parameters"])
    combined = " ".join(all_type_strings)
    needs_any = "Any" in combined
    needs_annotated = "Annotated[" in combined
    stdlib_imports = sorted(set(required_imports(combined)))
    # fastapi_class is cleared after stripping; only UploadFile remains as a plain type import.
    fastapi_param_classes: list[str] = sorted(
        {"UploadFile"} if "UploadFile" in combined else set()
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
        inline_schema_tag_map=inline_schema_tag_map,
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

    dep_import_path = config.dependencies.import_path or None
    has_any_security = any(op["has_security"] for op in rendered_ops)

    return {
        "tag": tag,
        "operations": rendered_ops,
        "needs_any": needs_any,
        "needs_annotated": needs_annotated,
        "fastapi_param_classes": fastapi_param_classes,
        "stdlib_imports": stdlib_imports,
        "tag_model_imports": tag_model_imports,
        "shared_model_imports": shared_model_imports,
        "service_class_name": service_class_name,
        "service_dep_fn": service_dep_fn,
        "dep_import_path": dep_import_path,
        "has_any_security": has_any_security,
    }
