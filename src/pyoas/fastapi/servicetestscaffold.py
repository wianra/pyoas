"""
ServiceTestScaffolder — writes service-layer pytest stub files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, TypedDict

import typer

from pyoas.core.config import Config
from pyoas.core.parser import SpecParser
from pyoas.core.renderer import Renderer
from pyoas.core.resolver import resolve_refs
from pyoas.core.result import ScaffoldResult
from pyoas.core.tags import extract_tags
from pyoas.core.utils import (
    generate_function_name,
    tag_to_dirname,
    to_pascal_case,
    to_snake_case,
)

from .params import build_function_params
from .testscaffold import (
    _annotated_base_type,
    _normalize_response_type,
)

_DEFAULT_TEMPLATES = Path(__file__).parent / "templates"


def _has_security(operation: dict[str, Any], global_security: list[Any]) -> bool:
    """Return True if this operation requires authentication."""
    op_security = operation.get("security")
    if op_security is not None:
        return len(op_security) > 0  # explicit override ([] means no auth)
    return len(global_security) > 0  # inherit global


def _success_test_name(method: str, response_type_str: str) -> str:
    """Derive a meaningful test method name from HTTP method and response type."""
    if method == "delete":
        return "test_deletes_resource"
    if method == "post":
        return "test_creates_resource"
    if method in ("put", "patch"):
        return "test_updates_resource"
    # GET
    ts = response_type_str.strip()
    if ts == "None":
        return "test_returns_empty_response"
    m = re.match(r"^list\[(.+)\]$", ts)
    if m:
        return f"test_returns_{to_snake_case(m.group(1).strip())}_list"
    base_ts = ts.split("[")[0].strip()
    return f"test_returns_{to_snake_case(base_ts)}"


class ServiceTestOperation(TypedDict):
    class_name: str
    function_name: str
    method: str
    path: str
    has_not_found_case: bool
    has_path_id_param: bool
    has_security: bool
    success_test_name: str


class ServiceTestScaffolder:
    def __init__(self, config: Config) -> None:
        self._config = config

    def scaffold(self, tag_filter: list[str] | None = None) -> ScaffoldResult:
        result = ScaffoldResult()
        cfg = self._config
        if not cfg.tests.generate:
            return result
        if not cfg.services.import_path:
            typer.echo(
                "Warning: service tests skipped — set services.import_path in pyoas.yaml "
                "to enable service test generation.",
                err=True,
            )
            return result

        spec_raw = SpecParser(cfg.spec).load()
        spec = resolve_refs(spec_raw, cfg.spec)
        grouped = extract_tags(spec, default_tag=cfg.default_tag)
        grouped_raw = extract_tags(spec_raw, default_tag=cfg.default_tag)

        if tag_filter:
            grouped = {k: v for k, v in grouped.items() if k in tag_filter}
            grouped_raw = {k: v for k, v in grouped_raw.items() if k in tag_filter}
        global_security: list[Any] = spec.get("security") or []

        renderer = Renderer(default_templates_dir=_DEFAULT_TEMPLATES)
        output_root = Path(cfg.tests.output)
        output_root.mkdir(parents=True, exist_ok=True)

        for tag, operations in grouped.items():
            raw_operations = grouped_raw.get(tag, [])
            merged = [
                {**op, "raw_operation": raw_op["operation"]}
                for op, raw_op in zip(operations, raw_operations, strict=True)
            ]
            tag_result = self._scaffold_tag(
                tag, merged, renderer, output_root, global_security
            )
            result.wrote += tag_result.wrote
            result.appended_items += tag_result.appended_items
            result.appended_files.extend(tag_result.appended_files)
        return result

    def _scaffold_tag(
        self,
        tag: str,
        operations: list[dict[str, Any]],
        renderer: Renderer,
        output_root: Path,
        global_security: list[Any],
    ) -> ScaffoldResult:
        tag_result = ScaffoldResult()
        tag_dirname = tag_to_dirname(tag)
        test_file = output_root / f"test_{tag_dirname}_service.py"
        context = _build_service_test_context(
            tag, operations, self._config, global_security
        )

        if not test_file.exists() or self._config.tests.overwrite:
            src = renderer.render("test_service.py.jinja2", context)
            test_file.write_text(src, encoding="utf-8")
            typer.echo(typer.style(f"  wrote  {test_file}", fg=typer.colors.GREEN))
            tag_result.wrote = 1
            return tag_result

        existing_src = test_file.read_text(encoding="utf-8")
        existing_classes = set(
            re.findall(r"^class (Test\w+):", existing_src, re.MULTILINE)
        )
        new_ops = [
            op
            for op in context["operations"]
            if op["class_name"] not in existing_classes
        ]
        if not new_ops:
            return tag_result

        stubs = _render_service_class_stubs(new_ops, context["service_class_name"])
        updated = existing_src.rstrip() + "\n\n" + stubs
        test_file.write_text(updated, encoding="utf-8")
        typer.echo(
            typer.style(
                f"  added  {len(new_ops)} service test class(es) to {test_file}",
                fg=typer.colors.GREEN,
            )
        )
        tag_result.appended_items = len(new_ops)
        tag_result.appended_files = [tag_dirname]
        return tag_result


def _build_service_test_context(
    tag: str,
    operations: list[dict[str, Any]],
    config: Config,
    global_security: list[Any],
) -> dict[str, Any]:
    tag_dirname = tag_to_dirname(tag)
    service_class_name = to_pascal_case(tag_dirname) + "Service"

    test_ops: list[ServiceTestOperation] = []
    for op_entry in operations:
        method: str = op_entry["method"]
        path: str = op_entry["path"]
        operation = op_entry["operation"]
        raw_operation = op_entry.get("raw_operation")

        fn_name = to_snake_case(
            operation.get("operationId") or generate_function_name(method, path)
        )
        class_name = "Test" + to_pascal_case(fn_name) + "Service"

        params = build_function_params(
            operation,
            raw_operation=raw_operation,
            enums_as_literals=config.fields.enums_as_literals,
        )

        has_path_id_param = any(
            p["location"] == "path"
            and _annotated_base_type(p["python_type"]).split("[")[0].strip()
            in ("int", "float", "uuid.UUID")
            for p in params
        )
        has_not_found_case = method in ("get", "patch", "delete") and has_path_id_param
        has_security = _has_security(operation, global_security)

        from .params import resolve_response_type

        response_type_str = resolve_response_type(
            operation,
            raw_operation=raw_operation,
            enums_as_literals=config.fields.enums_as_literals,
        )
        normalized = _normalize_response_type(response_type_str)
        # For the success test name use the raw response_type_str (keeps list[T] info)
        success_name = _success_test_name(
            method, response_type_str if normalized else response_type_str
        )

        test_ops.append(
            ServiceTestOperation(
                class_name=class_name,
                function_name=fn_name,
                method=method,
                path=path,
                has_not_found_case=has_not_found_case,
                has_path_id_param=has_path_id_param,
                has_security=has_security,
                success_test_name=success_name,
            )
        )

    return {
        "tag": tag,
        "tag_dirname": tag_dirname,
        "service_class_name": service_class_name,
        "service_import_path": config.services.import_path,
        "operations": test_ops,
    }


def _render_service_class_stubs(
    operations: list[dict[str, Any]], service_class_name: str
) -> str:
    """Render service test class stubs for append-only mode."""
    lines: list[str] = []
    for op in operations:
        lines.append(f"class {op['class_name']}:")
        lines.append(f'    """Service tests for {op["method"].upper()} {op["path"]}"""')
        lines.append("")
        lines.append(
            f"    def {op['success_test_name']}(self, service: {service_class_name}) -> None:"
        )
        lines.append(
            '        """Happy path — verify service returns expected result."""'
        )
        lines.append('        pytest.skip("implement me")')
        if op["has_not_found_case"]:
            lines.append("")
            lines.append(
                f"    def test_raises_not_found_when_missing(self, service: {service_class_name}) -> None:"
            )
            lines.append(
                '        """Verify service raises not-found when resource doesn\'t exist."""'
            )
            lines.append('        pytest.skip("implement me")')
        if op["has_security"]:
            lines.append("")
            lines.append(
                f"    def test_raises_unauthorized_when_unauthenticated(self, service: {service_class_name}) -> None:"
            )
            lines.append(
                '        """Verify service raises when no auth is provided."""'
            )
            lines.append('        pytest.skip("implement me")')
            if op["has_path_id_param"]:
                lines.append("")
                lines.append(
                    f"    def test_raises_forbidden_when_not_owner(self, service: {service_class_name}) -> None:"
                )
                lines.append(
                    '        """Verify service enforces ownership / access control."""'
                )
                lines.append('        pytest.skip("implement me")')
        lines.append("")
        lines.append("")
    return "\n".join(lines)
