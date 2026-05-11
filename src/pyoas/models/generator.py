"""
ModelGenerator — orchestrates Pydantic v2 model generation from an OpenAPI spec.
"""

from __future__ import annotations

import json as _json
import re as _re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from pyoas.core.analysis import (
    _GenericGroup,
    build_schema_tag_map,
    collect_inline_schemas,
    detect_generic_groups_global,
)
from pyoas.core.cache import GenerationCache, compute_config_hash, compute_tag_hash
from pyoas.core.config import Config
from pyoas.core.parsed_spec import ParsedSpec
from pyoas.core.renderer import Renderer
from pyoas.core.tags import extract_tags
from pyoas.core.utils import (
    ensure_intermediate_inits,
    format_output,
    spec_hash_of_file,
    tag_to_dirname,
)

from .classifier import (
    _collect_defs_schemas,
    _collect_shared_schemas,
    _collect_tag_schemas,
    _find_request_only_schema_names,
)
from .context import _build_models_context

_DEFAULT_TEMPLATES = Path(__file__).parent / "templates"


def _read_model_names_from_file(path: Path) -> list[str]:
    """Extract class names from an already-written model file (used on cache hit)."""
    if not path.exists():
        return []
    return _re.findall(r"^class (\w+)", path.read_text(encoding="utf-8"), _re.MULTILINE)


class ModelGenerator:
    def __init__(self, config: Config) -> None:
        self._config = config
        self.unreferenced_count: int = 0
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
        Generate Pydantic v2 models for all tags (or a subset via ``tag_filter``).

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
        # Use raw spec for schema-tag mapping so $ref strings are still intact.
        grouped_raw = extract_tags(
            spec_raw, default_tag=cfg.default_tag, include_webhooks=include_webhooks
        )
        # Keep the unfiltered grouped_raw so unreferenced detection is not confused
        # by schemas that are referenced by non-filtered tags.
        grouped_raw_all = grouped_raw

        if tag_filter:
            grouped = {k: v for k, v in grouped.items() if k in tag_filter}
            grouped_raw = {k: v for k, v in grouped_raw.items() if k in tag_filter}

        user_tmpl_dir = Path(cfg.templates.models) if cfg.templates.models else None
        renderer = Renderer(
            default_templates_dir=_DEFAULT_TEMPLATES,
            user_templates_dir=user_tmpl_dir,
            extensions_config=cfg.extensions,
        )

        output_root = Path(cfg.output.models)
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

        raw_components_schemas = spec_raw.get("components", {}).get("schemas", {})
        schema_tag_map = build_schema_tag_map(spec_raw, grouped_raw)
        request_only_names = _find_request_only_schema_names(spec_raw)

        resolved_components_schemas = spec.get("components", {}).get("schemas", {})
        defs_by_tag, shared_defs = _collect_defs_schemas(
            raw_components_schemas, resolved_components_schemas, schema_tag_map
        )

        inline_by_tag, inline_request_names = collect_inline_schemas(
            grouped, grouped_raw
        )
        request_only_names |= inline_request_names

        # Detect generic groups globally so we know placement (tag vs shared).
        generic_groups = detect_generic_groups_global(
            raw_components_schemas, schema_tag_map
        )

        # Build a lookup from schema_name → (resolved schema, raw schema) for
        # constructing virtual base schema entries.
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

        written: list[Path] = []
        tag_model_names: dict[str, list[str]] = {}
        for tag in grouped:
            tag_schemas = _collect_tag_schemas(
                tag, spec, schema_tag_map, raw_components_schemas
            )
            # Inject base schema entries for generics whose home is this tag.
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
            _tag_hash = ""
            if use_cache:
                _tag_schema_names = [s["name"] for s in all_schemas]
                _tag_raw_schemas = {
                    name: raw_components_schemas[name]
                    for name in _tag_schema_names
                    if name in raw_components_schemas
                }
                _content_json = _json.dumps(
                    {"tag": tag, "schemas": _tag_raw_schemas},
                    sort_keys=True,
                    default=str,
                )
                _tag_hash = compute_tag_hash(tag, _content_json, config_hash)
                _out_file = output_root / f"{tag_to_dirname(tag)}.py"
                if cache.is_current(tag, _tag_hash) and _out_file.exists():
                    if progress_callback:
                        progress_callback(f"[models]  {tag} (unchanged, skipped)")
                    tag_model_names[tag] = _read_model_names_from_file(_out_file)
                    written.append(_out_file)
                    continue
            _t0 = time.perf_counter()
            tag_model_names[tag] = self._write_tag(
                tag,
                all_schemas,
                renderer,
                output_root,
                schema_tag_map,
                request_only_names,
                generic_groups,
                spec_hash=spec_hash,
                shared_defs_names=_shared_defs_names,
            )
            written.append(output_root / f"{tag_to_dirname(tag)}.py")
            if use_cache:
                cache.update(tag, _tag_hash)
            if progress_callback:
                msg = f"[models]  {tag} ({len(all_schemas)} schemas)"
                if verbose:
                    msg += f"  {int((time.perf_counter() - _t0) * 1000)}ms"
                progress_callback(msg)

        shared_schemas = shared_defs + _collect_shared_schemas(
            spec, schema_tag_map, raw_components_schemas
        )

        # Warn about schemas not referenced by any operation.
        # Use the full (unfiltered) schema_tag_map so schemas belonging to
        # non-filtered tags are not incorrectly treated as unreferenced.
        _full_schema_tag_map = (
            build_schema_tag_map(spec_raw, grouped_raw_all)
            if tag_filter
            else schema_tag_map
        )
        unreferenced = sorted(set(raw_components_schemas) - set(_full_schema_tag_map))
        self.unreferenced_count = len(unreferenced)
        for name in unreferenced:
            typer.echo(
                typer.style(
                    f"  warning  Schema '{name}' not referenced by any operation"
                    " — skipped (set model_config.include_unreferenced: true to include it)",
                    fg=typer.colors.YELLOW,
                ),
                err=True,
            )
        if cfg.model_config.include_unreferenced and unreferenced:
            resolved_components = spec.get("components", {}).get("schemas", {})
            already_named = {s["name"] for s in shared_schemas}
            for name in unreferenced:
                if name not in already_named and name in resolved_components:
                    shared_schemas.append(
                        {
                            "name": name,
                            "schema": resolved_components[name],
                            "raw_schema": raw_components_schemas.get(name),
                        }
                    )

        # Inject generic bases whose home is shared.
        shared_base_entries = [
            _make_base_entry(g) for g in generic_groups.values() if g.home_tag is None
        ]
        if shared_schemas or shared_base_entries:
            _shared_all = shared_base_entries + shared_schemas
            _write_shared = True
            _shared_hash = ""
            if use_cache:
                _shared_raw_schemas = {
                    s["name"]: raw_components_schemas[s["name"]]
                    for s in _shared_all
                    if s["name"] in raw_components_schemas
                }
                _shared_content = _json.dumps(
                    {"tag": "shared", "schemas": _shared_raw_schemas},
                    sort_keys=True,
                    default=str,
                )
                _shared_hash = compute_tag_hash("shared", _shared_content, config_hash)
                _shared_file = output_root / "shared.py"
                if cache.is_current("shared", _shared_hash) and _shared_file.exists():
                    tag_model_names["shared"] = _read_model_names_from_file(
                        _shared_file
                    )
                    written.append(_shared_file)
                    _write_shared = False
            if _write_shared:
                tag_model_names["shared"] = self._write_tag(
                    "shared",
                    _shared_all,
                    renderer,
                    output_root,
                    schema_tag_map,
                    request_only_names,
                    generic_groups,
                    spec_hash=spec_hash,
                )
                written.append(output_root / "shared.py")
                if use_cache:
                    cache.update("shared", _shared_hash)

        has_shared = bool(shared_schemas or shared_base_entries)
        all_tags = list(grouped.keys()) + (["shared"] if has_shared else [])
        tag_entries = [
            {
                "dirname": tag_to_dirname(t),
                "model_names": sorted(tag_model_names.get(t, [])),
            }
            for t in all_tags
        ]
        root_init = renderer.render(
            "init.py.jinja2",
            {"tags": tag_entries, "is_root_models": True, "spec_hash": spec_hash},
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
        schemas: list[dict[str, Any]],
        renderer: Renderer,
        output_root: Path,
        schema_tag_map: dict[str, set[str]],
        request_only_names: set[str],
        generic_groups: dict[str, _GenericGroup] | None = None,
        spec_hash: str = "",
        shared_defs_names: set[str] | None = None,
    ) -> list[str]:
        """Write {tag}.py for one tag. Returns rendered class names."""
        context = _build_models_context(
            tag,
            schemas,
            self._config,
            schema_tag_map,
            request_only_names,
            generic_groups or {},
            shared_defs_names=shared_defs_names,
        )
        context["spec_hash"] = spec_hash
        model_names = [
            rs["name"] for rs in context["schemas"] if not rs.get("is_internal")
        ]
        models_src = renderer.render("model.py.jinja2", context)
        out_path = output_root / f"{tag_to_dirname(tag)}.py"
        for plugin in self._plugins:
            result = plugin.on_model_file_written(tag, str(out_path), models_src)
            if not result:
                from pyoas.core.plugins import PluginError

                raise PluginError(
                    f"Plugin {plugin.name!r} returned empty content from"
                    f" on_model_file_written for tag {tag!r}"
                )
            models_src = result
        out_path.write_text(models_src, encoding="utf-8")
        return model_names
