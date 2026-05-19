from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pyoas.core.utils import derive_import_path


@dataclass
class OutputConfig:
    models: str = "src/generated/models"
    routers: str = "src/generated/routers"
    models_import: str | None = (
        None  # explicit import path; derived from models path if omitted
    )
    routers_import: str | None = (
        None  # explicit import path; derived from routers path if omitted
    )
    source_root: str = (
        "src"  # filesystem prefix stripped when deriving Python import paths
    )


@dataclass
class ModelConfig:
    extra: str = "ignore"  # applied to response/shared schemas
    request_extra: str = "forbid"  # applied to request-only schemas
    frozen: bool = False
    populate_by_name: bool = True
    include_unreferenced: bool = False  # generate schemas with no operation references


@dataclass
class FieldsConfig:
    snake_case: bool = True
    enums_as_literals: bool = True
    unique_items_as_set: bool = (
        True  # emit set[T]; False → list[T] with dedup validator
    )


@dataclass
class FormatConfig:
    enabled: bool = True


@dataclass
class TemplatesConfig:
    models: str | None = None
    routers: str | None = None


@dataclass
class ServicesConfig:
    generate: bool = False
    output: str = "src/services"
    overwrite: bool = False
    import_path: str = ""
    drift_log: str | None = None  # path to append drift warnings; None → console only


@dataclass
class TestsConfig:
    generate: bool = False
    output: str = "tests/generated"
    overwrite: bool = False
    not_found_exception: str | None = None


@dataclass
class SkillsConfig:
    generate: bool = False
    output: str = ".claude/commands"
    overwrite: bool = False
    services_pattern: str = "none"  # none | repository | domain


@dataclass
class RouterConfig:
    response_model_exclude_none: bool = False
    response_model_exclude_unset: bool = False


@dataclass
class RouterScaffoldConfig:
    generate: bool = False
    output: str = "src/routers"
    overwrite: bool = False
    drift_log: str | None = None  # path to append drift warnings; None → console only


@dataclass
class ModelScaffoldConfig:
    generate: bool = False
    output: str = "src/models"
    overwrite: bool = False
    drift_log: str | None = None  # path to append drift warnings; None → console only


@dataclass
class DependenciesConfig:
    generate: bool = False
    output: str = "src/dependencies"
    overwrite: bool = False
    import_path: str = ""  # e.g. "src.dependencies"


@dataclass
class WebhooksConfig:
    generate: bool = False


@dataclass
class ExtensionsConfig:
    filters: str | None = None  # "module:attr" returning dict[str, Callable]
    globals: str | None = None  # "module:attr" returning dict[str, Any]


@dataclass
class Config:
    spec: str
    output: OutputConfig = field(default_factory=OutputConfig)
    default_tag: str = "default"
    model_config: ModelConfig = field(default_factory=ModelConfig)
    fields: FieldsConfig = field(default_factory=FieldsConfig)
    format: FormatConfig = field(default_factory=FormatConfig)
    templates: TemplatesConfig = field(default_factory=TemplatesConfig)
    services: ServicesConfig = field(default_factory=ServicesConfig)
    tests: TestsConfig = field(default_factory=TestsConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    router: RouterConfig = field(default_factory=RouterConfig)
    dependencies: DependenciesConfig = field(default_factory=DependenciesConfig)
    webhooks: WebhooksConfig = field(default_factory=WebhooksConfig)
    extensions: ExtensionsConfig = field(default_factory=ExtensionsConfig)
    plugins: list[str] = field(default_factory=list)
    router_scaffold: RouterScaffoldConfig = field(default_factory=RouterScaffoldConfig)
    model_scaffold: ModelScaffoldConfig = field(default_factory=ModelScaffoldConfig)


def _parse_config(data: dict[str, Any], base_dir: Path | None = None) -> Config:
    if "spec" not in data:
        raise ValueError(
            "Config must contain a 'spec' key pointing to the OpenAPI file"
        )

    out = data.get("output", {})
    mc = data.get("model_config", {})
    fld = data.get("fields", {})
    fmt = data.get("format", {})
    tmpl = data.get("templates", {})
    svc = data.get("services", {})
    tst = data.get("tests", {})
    skl = data.get("skills", {})
    rtr = data.get("router", {})
    dep = data.get("dependencies", {})
    wh = data.get("webhooks", {})
    ext = data.get("extensions", {})
    plg = data.get("plugins", [])
    rsc = data.get("router_scaffold", {})
    msc = data.get("model_scaffold", {})

    source_root = out.get("source_root", "src")
    models_rel = out.get("models", "src/generated/models")
    routers_rel = out.get("routers", "src/generated/routers")

    # Derive Python import paths from the relative paths before resolving to absolute.
    models_import = out.get("models_import") or derive_import_path(
        models_rel, source_root
    )
    routers_import = out.get("routers_import") or derive_import_path(
        routers_rel, source_root
    )

    def _resolve(rel: str) -> str:
        return str(base_dir / rel) if base_dir is not None else rel

    svc_output = svc.get("output", "src/services")
    tst_output = tst.get("output", "tests/generated")
    skl_output = skl.get("output", ".claude/commands")
    dep_output = dep.get("output", "src/dependencies")
    rsc_output = rsc.get("output", "src/routers")
    msc_output = msc.get("output", "src/models")
    tmpl_models = tmpl.get("models")
    tmpl_routers = tmpl.get("routers")

    return Config(
        spec=_resolve(data["spec"]),
        output=OutputConfig(
            models=_resolve(models_rel),
            routers=_resolve(routers_rel),
            models_import=models_import,
            routers_import=routers_import,
            source_root=source_root,
        ),
        default_tag=data.get("default_tag", "default"),
        model_config=ModelConfig(
            extra=mc.get("extra", "ignore"),
            request_extra=mc.get("request_extra", "forbid"),
            frozen=mc.get("frozen", False),
            populate_by_name=mc.get("populate_by_name", True),
            include_unreferenced=mc.get("include_unreferenced", False),
        ),
        fields=FieldsConfig(
            snake_case=fld.get("snake_case", True),
            enums_as_literals=fld.get("enums_as_literals", True),
            unique_items_as_set=fld.get("unique_items_as_set", True),
        ),
        format=FormatConfig(enabled=fmt.get("enabled", True)),
        templates=TemplatesConfig(
            models=_resolve(tmpl_models) if tmpl_models else None,
            routers=_resolve(tmpl_routers) if tmpl_routers else None,
        ),
        services=ServicesConfig(
            generate=svc.get("generate", False),
            output=_resolve(svc_output),
            overwrite=svc.get("overwrite", False),
            import_path=svc.get("import_path", ""),
            drift_log=_resolve(svc.get("drift_log")) if svc.get("drift_log") else None,
        ),
        tests=TestsConfig(
            generate=tst.get("generate", False),
            output=_resolve(tst_output),
            overwrite=tst.get("overwrite", False),
            not_found_exception=tst.get("not_found_exception"),
        ),
        skills=SkillsConfig(
            generate=skl.get("generate", False),
            output=_resolve(skl_output),
            overwrite=skl.get("overwrite", False),
            services_pattern=skl.get("services_pattern", "none"),
        ),
        router=RouterConfig(
            response_model_exclude_none=rtr.get("response_model_exclude_none", False),
            response_model_exclude_unset=rtr.get("response_model_exclude_unset", False),
        ),
        dependencies=DependenciesConfig(
            generate=dep.get("generate", False),
            output=_resolve(dep_output),
            overwrite=dep.get("overwrite", False),
            import_path=dep.get("import_path", ""),
        ),
        webhooks=WebhooksConfig(
            generate=wh.get("generate", False),
        ),
        extensions=ExtensionsConfig(
            filters=ext.get("filters") if isinstance(ext, dict) else None,
            globals=ext.get("globals") if isinstance(ext, dict) else None,
        ),
        plugins=list(plg) if isinstance(plg, list) else [],
        router_scaffold=RouterScaffoldConfig(
            generate=rsc.get("generate", False),
            output=_resolve(rsc_output),
            overwrite=rsc.get("overwrite", False),
            drift_log=_resolve(rsc.get("drift_log")) if rsc.get("drift_log") else None,
        ),
        model_scaffold=ModelScaffoldConfig(
            generate=msc.get("generate", False),
            output=_resolve(msc_output),
            overwrite=msc.get("overwrite", False),
            drift_log=_resolve(msc.get("drift_log")) if msc.get("drift_log") else None,
        ),
    )


def load_config(path: str) -> Config:
    """Load a pyoas config file. Paths in the config are resolved relative to
    the config file's directory, so pyoas can be run from any working directory."""
    p = Path(path).resolve()
    base_dir = p.parent
    match p.suffix.lower():
        case ".yaml" | ".yml":
            with p.open() as f:
                data = yaml.safe_load(f)
        case _:
            raise ValueError(
                f"Unsupported config format: {p.suffix!r}. Only YAML (.yaml/.yml) is supported."
            )
    if not isinstance(data, dict):
        raise ValueError("Config file is empty or not valid YAML")
    return _parse_config(data, base_dir=base_dir)
