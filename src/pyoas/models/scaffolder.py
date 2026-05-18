"""
ModelScaffolder — writes model stub files, adding missing schemas on re-runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from pyoas.core.analysis import (
    _GenericGroup,
    build_schema_tag_map,
    collect_inline_schemas,
    detect_generic_groups_global,
)
from pyoas.core.config import Config
from pyoas.core.parsed_spec import ParsedSpec
from pyoas.core.renderer import Renderer
from pyoas.core.result import ScaffoldResult
from pyoas.core.tags import extract_tags
from pyoas.core.utils import format_output, tag_to_dirname

from .classifier import (
    _collect_defs_schemas,
    _collect_shared_schemas,
    _collect_tag_schemas,
    _find_request_only_schema_names,
)
from .context import _build_models_context

_DEFAULT_TEMPLATES = Path(__file__).parent / "templates"


class ModelScaffolder:
    def __init__(self, config: Config) -> None:
        self._config = config

    def scaffold(self, tag_filter: list[str] | None = None) -> ScaffoldResult:
        result = ScaffoldResult()
        cfg = self._config
        if not cfg.model_scaffold.generate:
            typer.echo(
                "Model scaffold is not configured. Set model_scaffold.generate: true in config."
            )
            return result

        parsed_spec = ParsedSpec.from_config(cfg)
        spec_raw: dict = parsed_spec.raw
        spec: dict = parsed_spec.resolved

        include_webhooks = cfg.webhooks.generate
        grouped = extract_tags(
            spec, default_tag=cfg.default_tag, include_webhooks=include_webhooks
        )
        grouped_raw = extract_tags(
            spec_raw, default_tag=cfg.default_tag, include_webhooks=include_webhooks
        )
        grouped_raw_all = grouped_raw

        if tag_filter:
            grouped = {k: v for k, v in grouped.items() if k in tag_filter}
            grouped_raw = {k: v for k, v in grouped_raw.items() if k in tag_filter}

        renderer = Renderer(default_templates_dir=_DEFAULT_TEMPLATES)
        output_root = Path(cfg.model_scaffold.output)
        output_root.mkdir(parents=True, exist_ok=True)

        raw_components_schemas = spec_raw.get("components", {}).get("schemas", {})
        schema_tag_map = build_schema_tag_map(spec_raw, grouped_raw_all)
        request_only_names = _find_request_only_schema_names(spec_raw)

        resolved_components_schemas = spec.get("components", {}).get("schemas", {})
        defs_by_tag, shared_defs = _collect_defs_schemas(
            raw_components_schemas, resolved_components_schemas, schema_tag_map
        )

        inline_by_tag, inline_request_names = collect_inline_schemas(
            grouped, grouped_raw
        )
        request_only_names |= inline_request_names

        generic_groups = detect_generic_groups_global(
            raw_components_schemas, schema_tag_map
        )

        resolved_schemas_map = spec.get("components", {}).get("schemas", {})

        def _make_base_entry(group: _GenericGroup) -> dict[str, Any]:
            tmpl_name = group.template_schema_name
            return {
                "name": group.generic_name,
                "schema": resolved_schemas_map.get(tmpl_name, {}),
                "raw_schema": raw_components_schemas.get(tmpl_name),
                "_is_generic_base": True,
                "_group": group,
            }

        _shared_defs_names: set[str] = {e["name"] for e in shared_defs}

        for tag in grouped:
            tag_schemas = _collect_tag_schemas(
                tag, spec, schema_tag_map, raw_components_schemas
            )
            base_entries = [
                _make_base_entry(g)
                for g in generic_groups.values()
                if g.home_tag == tag
            ]
            all_schemas = (
                base_entries
                + defs_by_tag.get(tag, [])
                + tag_schemas
                + inline_by_tag.get(tag, [])
            )
            tag_result = self._scaffold_tag(
                tag,
                all_schemas,
                renderer,
                output_root,
                schema_tag_map,
                request_only_names,
                generic_groups,
                shared_defs_names=_shared_defs_names,
            )
            result.wrote += tag_result.wrote
            result.appended_items += tag_result.appended_items
            result.appended_files.extend(tag_result.appended_files)

        # Handle shared.py if not tag-filtered (shared spans all tags)
        if not tag_filter:
            shared_schemas = shared_defs + _collect_shared_schemas(
                spec, schema_tag_map, raw_components_schemas
            )
            shared_base_entries = [
                _make_base_entry(g)
                for g in generic_groups.values()
                if g.home_tag is None
            ]
            if shared_schemas or shared_base_entries:
                _shared_all = shared_base_entries + shared_schemas
                shared_result = self._scaffold_tag(
                    "shared",
                    _shared_all,
                    renderer,
                    output_root,
                    schema_tag_map,
                    request_only_names,
                    generic_groups,
                    shared_defs_names=_shared_defs_names,
                )
                result.wrote += shared_result.wrote
                result.appended_items += shared_result.appended_items
                result.appended_files.extend(shared_result.appended_files)

        # Write root __init__.py once (never overwrite — user may customise it)
        root_init = output_root / "__init__.py"
        if not root_init.exists():
            root_init.write_text(
                "# Scaffolded by pyoas — safe to edit.\n", encoding="utf-8"
            )

        if cfg.format.enabled:
            format_output(output_root)

        return result

    def _scaffold_tag(
        self,
        tag: str,
        schemas: list[dict[str, Any]],
        renderer: Renderer,
        output_root: Path,
        schema_tag_map: dict[str, set[str]],
        request_only_names: set[str],
        generic_groups: dict[str, _GenericGroup] | None = None,
        shared_defs_names: set[str] | None = None,
    ) -> ScaffoldResult:
        tag_result = ScaffoldResult()
        file_name = f"{tag_to_dirname(tag)}.py"
        out_file = output_root / file_name

        context = _build_models_context(
            tag,
            schemas,
            self._config,
            schema_tag_map,
            request_only_names,
            generic_groups or {},
            shared_defs_names=shared_defs_names,
        )

        if not out_file.exists() or self._config.model_scaffold.overwrite:
            src = renderer.render("model_scaffold.py.jinja2", context)
            out_file.write_text(src, encoding="utf-8")
            typer.echo(typer.style(f"  wrote  {out_file}", fg=typer.colors.GREEN))
            tag_result.wrote = 1
            return tag_result

        # File exists and overwrite=False — add only missing schemas.
        existing_src = out_file.read_text(encoding="utf-8")
        existing_names = _extract_schema_names(existing_src)
        current_names = {
            s["name"] for s in context["schemas"] if not s.get("is_internal")
        }

        orphaned = existing_names - current_names
        if orphaned:
            for name in sorted(orphaned):
                typer.echo(
                    f"WARNING: {out_file}: schema '{name}' has no matching "
                    f"definition in the spec — it may be orphaned.",
                    err=True,
                )
            _emit_model_drift_warnings(
                [f"ORPHANED: {out_file}::{n}" for n in sorted(orphaned)],
                self._config,
            )

        new_schema_names = current_names - existing_names
        if not new_schema_names:
            return tag_result

        # Build delta context with only the new schemas.
        delta_context = _build_models_context(
            tag,
            [s for s in schemas if s.get("name") in new_schema_names],
            self._config,
            schema_tag_map,
            request_only_names,
            generic_groups or {},
            shared_defs_names=shared_defs_names,
        )
        delta_src = renderer.render("model_scaffold.py.jinja2", delta_context)

        # Inject any missing imports and TypeVar declarations, then append new classes.
        import_lines, typevar_lines, class_body = _split_delta_src(delta_src)

        # Inject missing imports before first schema definition.
        existing_imports = set(
            re.findall(
                r"^(?:from\s+\S+\s+import\s+.*|import\s+\S+.*)$",
                existing_src,
                re.MULTILINE,
            )
        )
        missing_imports = [
            line
            for line in import_lines
            if line.strip()
            and line.strip() not in existing_imports
            and not line.strip().startswith("from __future__")
        ]
        if missing_imports:
            first_def_m = re.search(
                r"^(?:class \w+|[A-Z]\w+\s*=\s*(?!TypeVar))",
                existing_src,
                re.MULTILINE,
            )
            if first_def_m:
                pos = first_def_m.start()
                existing_src = (
                    existing_src[:pos]
                    + "\n".join(missing_imports)
                    + "\n"
                    + existing_src[pos:]
                )
            else:
                existing_src = (
                    existing_src.rstrip() + "\n" + "\n".join(missing_imports) + "\n"
                )

        # Inject missing TypeVar declarations before first class definition.
        missing_typevars = [
            line
            for line in typevar_lines
            if line.strip() and line.strip() not in existing_src
        ]
        if missing_typevars:
            first_class_m = re.search(r"^class \w+", existing_src, re.MULTILINE)
            if first_class_m:
                pos = first_class_m.start()
                existing_src = (
                    existing_src[:pos]
                    + "\n".join(missing_typevars)
                    + "\n\n"
                    + existing_src[pos:]
                )
            else:
                existing_src = (
                    existing_src.rstrip() + "\n\n" + "\n".join(missing_typevars) + "\n"
                )

        if class_body:
            updated = existing_src.rstrip() + "\n\n\n" + class_body.strip() + "\n"
            out_file.write_text(updated, encoding="utf-8")
            typer.echo(
                typer.style(
                    f"  added  {len(new_schema_names)} schema(s) to {out_file}",
                    fg=typer.colors.GREEN,
                )
            )
            tag_result.appended_items = len(new_schema_names)
            tag_result.appended_files = [tag_to_dirname(tag)]

        return tag_result


@dataclass
class ModelDriftItem:
    """A single drift finding from detect_model_drift."""

    kind: str  # "missing_file" | "missing_class" | "orphaned_class"
    file: str
    schema: str | None
    detail: str


def detect_model_drift(
    cfg: Any,
    tag_filter: list[str] | None = None,
) -> list[ModelDriftItem]:
    """Read-only: compare scaffold model files on disk against the spec.

    Returns ModelDriftItem entries for missing files, missing classes, and
    orphaned classes. Never writes anything.
    """
    parsed_spec = ParsedSpec.from_config(cfg)
    spec_raw: dict = parsed_spec.raw
    spec: dict = parsed_spec.resolved

    include_webhooks = cfg.webhooks.generate
    grouped = extract_tags(
        spec, default_tag=cfg.default_tag, include_webhooks=include_webhooks
    )
    grouped_raw_all = extract_tags(
        spec_raw, default_tag=cfg.default_tag, include_webhooks=include_webhooks
    )
    if tag_filter:
        grouped = {k: v for k, v in grouped.items() if k in tag_filter}

    raw_components_schemas = spec_raw.get("components", {}).get("schemas", {})
    schema_tag_map = build_schema_tag_map(spec_raw, grouped_raw_all)
    request_only_names = _find_request_only_schema_names(spec_raw)
    resolved_components_schemas = spec.get("components", {}).get("schemas", {})
    defs_by_tag, shared_defs = _collect_defs_schemas(
        raw_components_schemas, resolved_components_schemas, schema_tag_map
    )
    inline_by_tag, inline_request_names = collect_inline_schemas(
        grouped,
        extract_tags(
            spec_raw, default_tag=cfg.default_tag, include_webhooks=include_webhooks
        ),
    )
    request_only_names |= inline_request_names
    generic_groups = detect_generic_groups_global(
        raw_components_schemas, schema_tag_map
    )
    resolved_schemas_map = spec.get("components", {}).get("schemas", {})

    def _make_base_entry(group: _GenericGroup) -> dict[str, Any]:
        tmpl_name = group.template_schema_name
        return {
            "name": group.generic_name,
            "schema": resolved_schemas_map.get(tmpl_name, {}),
            "raw_schema": raw_components_schemas.get(tmpl_name),
            "_is_generic_base": True,
            "_group": group,
        }

    _shared_defs_names: set[str] = {e["name"] for e in shared_defs}

    items: list[ModelDriftItem] = []
    model_root = Path(cfg.model_scaffold.output)

    tags_to_check = dict(grouped)
    if not tag_filter:
        shared_schemas = shared_defs + _collect_shared_schemas(
            spec, schema_tag_map, raw_components_schemas
        )
        shared_base_entries = [
            _make_base_entry(g) for g in generic_groups.values() if g.home_tag is None
        ]
        if shared_schemas or shared_base_entries:
            # Add shared as a virtual tag for drift checking
            tags_to_check["__shared__"] = []

    for tag in tags_to_check:
        if tag == "__shared__":
            _shared_all = (
                [
                    _make_base_entry(g)
                    for g in generic_groups.values()
                    if g.home_tag is None
                ]
                + shared_defs
                + _collect_shared_schemas(spec, schema_tag_map, raw_components_schemas)
            )
            context = _build_models_context(
                "shared",
                _shared_all,
                cfg,
                schema_tag_map,
                request_only_names,
                generic_groups,
                shared_defs_names=_shared_defs_names,
            )
            file_tag = "shared"
        else:
            tag_schemas = _collect_tag_schemas(
                tag, spec, schema_tag_map, raw_components_schemas
            )
            base_entries = [
                _make_base_entry(g)
                for g in generic_groups.values()
                if g.home_tag == tag
            ]
            all_schemas = (
                base_entries
                + defs_by_tag.get(tag, [])
                + tag_schemas
                + inline_by_tag.get(tag, [])
            )
            context = _build_models_context(
                tag,
                all_schemas,
                cfg,
                schema_tag_map,
                request_only_names,
                generic_groups,
                shared_defs_names=_shared_defs_names,
            )
            file_tag = tag

        model_file = model_root / f"{tag_to_dirname(file_tag)}.py"
        current_names = {
            s["name"] for s in context["schemas"] if not s.get("is_internal")
        }

        if not model_file.exists():
            items.append(
                ModelDriftItem(
                    kind="missing_file",
                    file=str(model_file),
                    schema=None,
                    detail=f"{model_file} does not exist",
                )
            )
            continue

        existing_names = _extract_schema_names(model_file.read_text(encoding="utf-8"))

        for name in sorted(current_names - existing_names):
            items.append(
                ModelDriftItem(
                    kind="missing_class",
                    file=str(model_file),
                    schema=name,
                    detail=f"schema '{name}' is in the spec but missing from {model_file}",
                )
            )
        for name in sorted(existing_names - current_names):
            items.append(
                ModelDriftItem(
                    kind="orphaned_class",
                    file=str(model_file),
                    schema=name,
                    detail=f"schema '{name}' has no matching definition in the spec",
                )
            )

    return items


def _extract_schema_names(src: str) -> set[str]:
    """Extract top-level class and alias names from Python model source."""
    class_names = set(re.findall(r"^class (\w+)", src, re.MULTILINE))
    alias_names = set(re.findall(r"^([A-Z]\w+)\s*=\s*(?!TypeVar)", src, re.MULTILINE))
    return class_names | alias_names


def _split_delta_src(src: str) -> tuple[list[str], list[str], str]:
    """Split a rendered model file into (import_lines, typevar_lines, class_body).

    Skips the first line (header comment) and ``from __future__ import annotations``.
    class_body is everything from the first class/alias definition to the end.
    """
    lines = src.split("\n")[1:]  # skip header comment
    import_lines: list[str] = []
    typevar_lines: list[str] = []
    class_start: int | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^\w+ = TypeVar\(", stripped):
            typevar_lines.append(line)
        elif stripped.startswith("from ") or stripped.startswith("import "):
            import_lines.append(stripped)
        elif re.match(r"^class \w+", stripped) or re.match(
            r"^[A-Z]\w+\s*=\s*(?!TypeVar)", stripped
        ):
            class_start = i
            break

    if class_start is not None:
        class_body = "\n".join(lines[class_start:])
    else:
        class_body = ""

    return import_lines, typevar_lines, class_body


def _emit_model_drift_warnings(warnings: list[str], config: Config) -> None:
    """Print drift warnings to stderr and optionally append them to a log file."""
    from datetime import datetime

    for w in warnings:
        typer.echo(f"WARNING: {w}", err=True)

    if config.model_scaffold.drift_log:
        log_path = Path(config.model_scaffold.drift_log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {timestamp} ---\n")
            for w in warnings:
                f.write(w + "\n")
