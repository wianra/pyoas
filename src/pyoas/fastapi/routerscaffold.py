"""
RouterScaffolder — writes router stub files, adding missing endpoints on re-runs.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from pyoas.core.utils import tag_to_dirname

from .generator import _build_router_context

_DEFAULT_TEMPLATES = Path(__file__).parent / "templates"


class RouterScaffolder:
    def __init__(self, config: Config) -> None:
        self._config = config

    def scaffold(self, tag_filter: list[str] | None = None) -> ScaffoldResult:
        result = ScaffoldResult()
        cfg = self._config
        if not cfg.router_scaffold.generate:
            typer.echo(
                "Router scaffold is not configured. Set router_scaffold.generate: true in config."
            )
            return result

        spec_raw = SpecParser(cfg.spec).load()
        spec = resolve_refs(spec_raw, cfg.spec)
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

        global_security: list[Any] = spec_raw.get("security") or []
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
        inline_by_tag, _ = collect_inline_schemas(grouped, grouped_raw)
        inline_schema_tag_map: dict[str, str] = {
            entry["name"]: t
            for t, entries in inline_by_tag.items()
            for entry in entries
        }

        renderer = Renderer(default_templates_dir=_DEFAULT_TEMPLATES)
        output_root = Path(cfg.router_scaffold.output)
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
        tag_result = ScaffoldResult()
        tag_dirname = tag_to_dirname(tag)
        router_file = output_root / f"{tag_dirname}.py"

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
        # Scaffold routers never delegate to a service layer.
        context["service_import_path"] = None

        if not router_file.exists() or self._config.router_scaffold.overwrite:
            src = renderer.render("router_scaffold.py.jinja2", context)
            router_file.write_text(src, encoding="utf-8")
            typer.echo(typer.style(f"  wrote  {router_file}", fg=typer.colors.GREEN))
            tag_result.wrote = 1
            return tag_result

        # File exists and overwrite=False — add only missing endpoints.
        existing_src = router_file.read_text(encoding="utf-8")
        existing_fns = set(
            re.findall(r"^async def (\w+)\(", existing_src, re.MULTILINE)
        )
        current_fns = {op["function_name"] for op in context["operations"]}
        orphaned = existing_fns - current_fns
        if orphaned:
            for name in sorted(orphaned):
                typer.echo(
                    f"WARNING: {router_file}: endpoint '{name}' has no matching "
                    f"operation in the spec — it may be orphaned.",
                    err=True,
                )

        # Detect signature drift for endpoints present in both file and spec.
        shared = existing_fns & current_fns
        if shared:
            ops_by_name = {op["function_name"]: op for op in context["operations"]}
            drift_warnings: list[str] = []
            dep_import_path = context.get("dep_import_path")
            for name in sorted(shared):
                expected = _expected_router_sig_str(ops_by_name[name], dep_import_path)
                actual = _actual_router_sig_str(existing_src, name)
                if actual is not None and actual != expected:
                    drift_warnings.append(
                        f"DRIFT: {router_file}::{name} — signature changed\n"
                        f"  expected: {expected}\n"
                        f"  actual:   {actual}"
                    )
            if drift_warnings:
                _emit_router_drift_warnings(drift_warnings, self._config)

        new_ops = [
            op
            for op in context["operations"]
            if op["function_name"] not in existing_fns
        ]
        if not new_ops:
            return tag_result

        dep_import_path = context.get("dep_import_path")
        stubs = _render_endpoint_stubs(new_ops, dep_import_path=dep_import_path)

        # Ensure AuthContext is imported when new secured endpoints are being added.
        if dep_import_path and any(op.get("has_security") for op in new_ops):
            import_line = (
                f"from {dep_import_path}.auth import AuthContext, get_auth_context"
            )
            if import_line not in existing_src:
                router_decl = re.search(
                    r"^router = APIRouter\(", existing_src, re.MULTILINE
                )
                if router_decl:
                    pos = router_decl.start()
                    existing_src = (
                        existing_src[:pos] + import_line + "\n" + existing_src[pos:]
                    )
                else:
                    existing_src = import_line + "\n\n" + existing_src

        updated = existing_src.rstrip() + "\n\n\n" + stubs
        router_file.write_text(updated, encoding="utf-8")
        typer.echo(
            typer.style(
                f"  added  {len(new_ops)} endpoint(s) to {router_file}",
                fg=typer.colors.GREEN,
            )
        )
        tag_result.appended_items = len(new_ops)
        tag_result.appended_files = [tag_dirname]
        return tag_result


@dataclass
class RouterDriftItem:
    """A single drift finding from detect_router_drift."""

    kind: str  # "missing_file" | "missing_endpoint" | "orphaned_endpoint" | "signature_changed"
    file: str
    endpoint: str | None
    detail: str


def detect_router_drift(
    cfg: Any,
    tag_filter: list[str] | None = None,
) -> list[RouterDriftItem]:
    """Read-only: compare scaffold router files on disk against the spec.

    Returns RouterDriftItem entries for missing files, missing endpoints, orphaned
    endpoints, and signature changes. Never writes anything.
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

    global_security: list[Any] = spec_raw.get("security") or []
    raw_cs = spec_raw.get("components", {}).get("schemas", {})
    full_grouped_raw = extract_tags(
        spec_raw, default_tag=cfg.default_tag, include_webhooks=include_webhooks
    )
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

    items: list[RouterDriftItem] = []
    router_root = Path(cfg.router_scaffold.output)

    for tag, operations in grouped.items():
        raw_ops = grouped_raw.get(tag, [])
        merged = [
            {**op, "raw_operation": raw_op["operation"]}
            for op, raw_op in zip(operations, raw_ops, strict=True)
        ]
        context = _build_router_context(
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
        context["service_import_path"] = None
        tag_dirname = tag_to_dirname(tag)
        router_file = router_root / f"{tag_dirname}.py"
        current_fns = {op["function_name"] for op in context["operations"]}

        if not router_file.exists():
            items.append(
                RouterDriftItem(
                    kind="missing_file",
                    file=str(router_file),
                    endpoint=None,
                    detail=f"{router_file} does not exist",
                )
            )
            continue

        existing_src = router_file.read_text(encoding="utf-8")
        existing_fns = set(
            re.findall(r"^async def (\w+)\(", existing_src, re.MULTILINE)
        )
        # Missing endpoints (in spec but not in file)
        for fn in sorted(current_fns - existing_fns):
            items.append(
                RouterDriftItem(
                    kind="missing_endpoint",
                    file=str(router_file),
                    endpoint=fn,
                    detail=f"endpoint '{fn}' is in the spec but missing from {router_file}",
                )
            )
        # Orphaned endpoints (in file but not in spec)
        for fn in sorted(existing_fns - current_fns):
            items.append(
                RouterDriftItem(
                    kind="orphaned_endpoint",
                    file=str(router_file),
                    endpoint=fn,
                    detail=f"endpoint '{fn}' has no matching operation in the spec",
                )
            )
        # Signature drift for endpoints present in both
        shared = existing_fns & current_fns
        if shared:
            ops_by_name = {op["function_name"]: op for op in context["operations"]}
            dep_import_path = context.get("dep_import_path")
            for fn in sorted(shared):
                expected = _expected_router_sig_str(ops_by_name[fn], dep_import_path)
                actual = _actual_router_sig_str(existing_src, fn)
                if actual is not None and actual != expected:
                    items.append(
                        RouterDriftItem(
                            kind="signature_changed",
                            file=str(router_file),
                            endpoint=fn,
                            detail=(
                                f"signature changed\n"
                                f"  expected: {expected}\n"
                                f"  actual:   {actual}"
                            ),
                        )
                    )

    return items


def _expected_router_sig_str(
    op: dict[str, Any], dep_import_path: str | None = None
) -> str:
    """Build a normalised signature string from a router operation dict."""
    parts = [
        f"{p['name']}: {p['python_type']}" + (" = None" if not p["required"] else "")
        for p in op["parameters"]
    ]
    if dep_import_path and op.get("has_security"):
        parts.append("current_user: AuthContext = Depends(get_auth_context)")
    if parts:
        return f"(*, {', '.join(parts)}) -> {op['response_type']}"
    return f"() -> {op['response_type']}"


def _actual_router_sig_str(src: str, fn_name: str) -> str | None:
    """Extract and normalise the signature of a module-level async def using AST."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == fn_name:
            return _router_sig_from_ast(node)
    return None


def _router_sig_from_ast(func: ast.AsyncFunctionDef) -> str:
    parts = []
    for arg, default in zip(func.args.kwonlyargs, func.args.kw_defaults):
        if arg.arg == "service":
            continue  # injected by scaffolder, not part of spec
        ann = ast.unparse(arg.annotation).strip() if arg.annotation else ""
        part = f"{arg.arg}: {ann}" if ann else arg.arg
        if default is not None:
            part += f" = {ast.unparse(default)}"
        parts.append(part)
    ret = ast.unparse(func.returns).strip() if func.returns else "None"
    if parts:
        return f"(*, {', '.join(parts)}) -> {ret}"
    return f"() -> {ret}"


def _emit_router_drift_warnings(warnings: list[str], config: Config) -> None:
    """Print drift warnings to stderr and optionally append them to a log file."""
    from datetime import datetime

    for w in warnings:
        typer.echo(f"WARNING: {w}", err=True)

    if config.router_scaffold.drift_log:
        log_path = Path(config.router_scaffold.drift_log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {timestamp} ---\n")
            for w in warnings:
                f.write(w + "\n")


def _render_endpoint_stubs(
    operations: list[dict[str, Any]], dep_import_path: str | None = None
) -> str:
    """Render new endpoint stubs as a plain string for append-only inserts."""
    lines: list[str] = []
    for op in operations:
        if op.get("required_scopes"):
            lines.append(f"# Required scopes: {', '.join(op['required_scopes'])}")
        # Build decorator
        dec = f'@{"webhooks" if op.get("is_webhook") else "router"}.{op["method"]}("{op["path"]}"'
        extras: list[str] = []
        if op["response_type"] and op["response_type"] not in ("None", "Response"):
            extras.append(f"response_model={op['response_type']}")
        if op.get("status_code", 200) != 200:
            extras.append(f"status_code={op['status_code']}")
        if op.get("deprecated"):
            extras.append("deprecated=True")
        if op.get("summary"):
            escaped = op["summary"].replace('"', '\\"')
            extras.append(f'summary="{escaped}"')
        dec += (", " + ", ".join(extras) if extras else "") + ")"
        lines.append(dec)

        has_kwonly = bool(op["parameters"]) or bool(
            dep_import_path and op.get("has_security")
        )
        lines.append(f"async def {op['function_name']}(")
        if has_kwonly:
            lines.append("    *,")
        for param in op["parameters"]:
            if param.get("default_repr") is not None:
                default = f" = {param['default_repr']}"
            elif not param["required"]:
                default = " = None"
            else:
                default = ""
            lines.append(f"    {param['name']}: {param['python_type']}{default},")
        if op.get("has_security"):
            if dep_import_path:
                lines.append(
                    "    current_user: AuthContext = Depends(get_auth_context),"
                )
            else:
                lines.append(
                    "    # TODO: add authentication dependency, "
                    "e.g.: current_user = Depends(get_auth_context)"
                )
        lines.append(f") -> {op['response_type'] or 'None'}:")
        if op.get("description"):
            lines.append(f'    """{op["description"]}"""')
        lines.append("    raise NotImplementedError")
        lines.append("")
        lines.append("")
    return "\n".join(lines)
