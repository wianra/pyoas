from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

import typer

from pyoas import __version__

app = typer.Typer(
    name="pyoas",
    help="Generate Pydantic models and FastAPI routers from an OpenAPI spec.",
    no_args_is_help=True,
)

_CONFIG_OPTION = typer.Option(help="Path to pyoas config file")
_TAGS_OPTION = typer.Option(help="Comma-separated list of tags to generate")
_CLEAN_OPTION = typer.Option(help="Purge output directory before generation")
_QUIET_OPTION = typer.Option(help="Suppress progress output (errors still shown)")
_VERBOSE_OPTION = typer.Option(help="Show per-tag timing alongside progress output")

scaffold_app = typer.Typer(
    help="Scaffold user-owned files (skips existing files by default)."
)
app.add_typer(scaffold_app, name="scaffold")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"pyoas {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool | None = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


def _load_cfg(config: str):  # noqa: ANN201
    from pyoas.core.config import load_config

    return load_config(config)


def _tag_filter(tags: str | None) -> list[str] | None:
    if tags is None:
        return None
    return [t.strip() for t in tags.split(",") if t.strip()]


@app.command()
def init(
    spec: Annotated[str, typer.Argument(help="Path to the OpenAPI spec file")],
    output: Annotated[
        str, typer.Option(help="Path to write the config file")
    ] = "pyoas.yaml",
    force: Annotated[bool, typer.Option(help="Overwrite existing config file")] = False,
) -> None:
    """Generate a starter pyoas.yaml config from an OpenAPI spec path."""
    from pathlib import Path

    out = Path(output)
    if out.exists() and not force:
        typer.echo(
            f"Error: {output} already exists. Use --force to overwrite.", err=True
        )
        raise typer.Exit(1)

    content = f"""\
spec: {spec}
output:
  models: src/generated/models
  routers: src/generated/routers
default_tag: default
model_config:
  extra: ignore
  request_extra: forbid
  frozen: false
  populate_by_name: true
fields:
  snake_case: true
  enums_as_literals: true
format:
  enabled: true
services:
  generate: false
  output: src/services
  overwrite: false
  import_path: ""  # e.g. "src.services"
  drift_log: null
tests:
  generate: false
  output: tests/generated
  overwrite: false
  not_found_exception: null  # e.g. "src.exceptions.NotFound"
dependencies:
  generate: false
  output: src/dependencies
  import_path: ""  # e.g. "src.dependencies"
  overwrite: false
skills:
  generate: false
  output: .claude/commands
  overwrite: false
  services_pattern: none  # none | repository | domain
webhooks:
  generate: false  # set to true to generate code for OAS 3.1 webhooks
# extensions:
#   filters: null  # e.g. "myapp.pyoas_extensions:custom_filters"
#   globals: null  # e.g. "myapp.pyoas_extensions:custom_globals"
"""
    out.write_text(content, encoding="utf-8")
    typer.echo(f"Created {output}")


@app.command()
def models(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
    tags: Annotated[str | None, _TAGS_OPTION] = None,
    clean: Annotated[bool, _CLEAN_OPTION] = False,
    quiet: Annotated[bool, _QUIET_OPTION] = False,
    verbose: Annotated[bool, _VERBOSE_OPTION] = False,
) -> None:
    """Generate Pydantic v2 models from the OpenAPI spec."""
    try:
        from pyoas.models import ModelGenerator
    except ImportError:
        typer.echo(
            "Error: pyoas is not installed. Run: pip install pyoas",
            err=True,
        )
        raise typer.Exit(1)

    callback = None if quiet else lambda msg: typer.echo(msg, err=True)
    written = ModelGenerator(_load_cfg(config)).generate(
        tag_filter=_tag_filter(tags),
        clean=clean,
        progress_callback=callback,
        verbose=verbose,
    )
    if not quiet:
        for path in written:
            typer.echo(typer.style(f"  wrote  {path}", fg=typer.colors.GREEN))


@app.command()
def fastapi(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
    tags: Annotated[str | None, _TAGS_OPTION] = None,
    clean: Annotated[bool, _CLEAN_OPTION] = False,
    quiet: Annotated[bool, _QUIET_OPTION] = False,
    verbose: Annotated[bool, _VERBOSE_OPTION] = False,
) -> None:
    """Generate FastAPI routers from the OpenAPI spec."""
    try:
        from pyoas.fastapi import RouterGenerator
    except ImportError:
        typer.echo(
            'Error: pyoas[fastapi] extra is required. Run: pip install "pyoas[fastapi]"',
            err=True,
        )
        raise typer.Exit(1)

    callback = None if quiet else lambda msg: typer.echo(msg, err=True)
    written = RouterGenerator(_load_cfg(config)).generate(
        tag_filter=_tag_filter(tags),
        clean=clean,
        progress_callback=callback,
        verbose=verbose,
    )
    if not quiet:
        for path in written:
            typer.echo(typer.style(f"  wrote  {path}", fg=typer.colors.GREEN))


def _print_summary(rows: list[tuple[str, str, str]]) -> None:
    """Print a clean aligned summary table."""
    if not rows:
        return
    label_w = max(len(r[0]) for r in rows)
    main_w = max(len(r[1]) for r in rows)
    sep_len = 2 + label_w + 3 + main_w
    details = [r[2] for r in rows if r[2]]
    if details:
        sep_len += 3 + max(len(d) for d in details)
    sep = "─" * sep_len
    typer.echo("")
    typer.echo(sep)
    for label, main, detail in rows:
        try:
            count = int(main.split()[0])
            main_color: str | None = typer.colors.GREEN if count > 0 else None
        except (ValueError, IndexError):
            main_color = None
        label_part = label.ljust(label_w)
        main_part = typer.style(main.ljust(main_w), fg=main_color)
        line = f"  {label_part}   " + main_part
        if detail:
            line += "   " + typer.style(detail, fg=typer.colors.YELLOW)
        typer.echo(line)
    typer.echo(sep)


@app.command()
def generate(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
    tags: Annotated[str | None, _TAGS_OPTION] = None,
    clean: Annotated[bool, _CLEAN_OPTION] = False,
    quiet: Annotated[bool, _QUIET_OPTION] = False,
    verbose: Annotated[bool, _VERBOSE_OPTION] = False,
) -> None:
    """Generate both Pydantic models and FastAPI routers."""
    missing: list[str] = []
    try:
        from pyoas.models import ModelGenerator
    except ImportError:
        missing.append("pyoas")

    try:
        from pyoas.fastapi import RouterGenerator
    except ImportError:
        missing.append("pyoas[fastapi]")

    if missing:
        for pkg in missing:
            typer.echo(
                f"Error: {pkg} is not installed. Run: pip install {pkg}", err=True
            )
        raise typer.Exit(1)

    from pyoas.core.parsed_spec import ParsedSpec

    cfg = _load_cfg(config)
    tag_filter = _tag_filter(tags)
    parsed = ParsedSpec.from_config(cfg)
    callback = None if quiet else lambda msg: typer.echo(msg, err=True)

    model_gen = ModelGenerator(cfg)  # type: ignore[possibly-undefined]
    model_written = model_gen.generate(
        tag_filter=tag_filter,
        clean=clean,
        parsed_spec=parsed,
        progress_callback=callback,
        verbose=verbose,
    )
    router_gen = RouterGenerator(cfg)  # type: ignore[possibly-undefined]
    router_written = router_gen.generate(
        tag_filter=tag_filter,
        clean=clean,
        parsed_spec=parsed,
        progress_callback=callback,
        verbose=verbose,
    )
    if not quiet:
        for path in model_written + router_written:
            typer.echo(typer.style(f"  wrote  {path}", fg=typer.colors.GREEN))

    summary: list[tuple[str, str, str]] = []
    warn_count = model_gen.unreferenced_count
    summary.append(
        (
            "models",
            f"{len(model_written)} wrote",
            f"{warn_count} warning(s)" if warn_count else "",
        )
    )
    summary.append(("routers", f"{len(router_written)} wrote", ""))

    if cfg.dependencies.generate:
        from pyoas.fastapi import DependencyScaffolder

        dep_result = DependencyScaffolder(cfg).scaffold()
        detail = f"{dep_result.skipped} skipped" if dep_result.skipped else ""
        summary.append(("dependencies", f"{dep_result.wrote} wrote", detail))

    if cfg.services.generate:
        from pyoas.fastapi import ServiceScaffolder

        svc_result = ServiceScaffolder(cfg).scaffold(tag_filter=tag_filter)
        detail = ""
        if svc_result.appended_items:
            files_str = ", ".join(svc_result.appended_files)
            detail = f"{svc_result.appended_items} added to {len(svc_result.appended_files)} file(s) ({files_str})"
        summary.append(("services", f"{svc_result.wrote} wrote", detail))

    if cfg.tests.generate:
        from pyoas.fastapi import ServiceTestScaffolder, TestScaffolder

        test_result = TestScaffolder(cfg).scaffold(tag_filter=tag_filter)
        svc_test_result = ServiceTestScaffolder(cfg).scaffold(tag_filter=tag_filter)

        detail = ""
        if test_result.appended_items:
            files_str = ", ".join(test_result.appended_files)
            detail = f"{test_result.appended_items} added to {len(test_result.appended_files)} file(s) ({files_str})"
        summary.append(("tests", f"{test_result.wrote} wrote", detail))

        detail = ""
        if svc_test_result.appended_items:
            files_str = ", ".join(svc_test_result.appended_files)
            detail = f"{svc_test_result.appended_items} added to {len(svc_test_result.appended_files)} file(s) ({files_str})"
        summary.append(("service tests", f"{svc_test_result.wrote} wrote", detail))

    if cfg.skills.generate:
        try:
            from pyoas.claude import SkillScaffolder

            skill_result = SkillScaffolder(cfg).scaffold()
            detail = f"{skill_result.skipped} skipped" if skill_result.skipped else ""
            summary.append(("skills", f"{skill_result.wrote} wrote", detail))
        except ImportError:
            typer.echo(
                'Run: pip install "pyoas[claude]" to generate Claude skills.', err=True
            )

    _print_summary(summary)


@app.command()
def diff(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
    tags: Annotated[str | None, _TAGS_OPTION] = None,
) -> None:
    """Show which generated files would change without writing them (CI-safe dry run).

    Exits with code 1 if any file would be added, modified, or deleted.
    """
    missing: list[str] = []
    try:
        from pyoas.models import ModelGenerator
    except ImportError:
        missing.append("pyoas")

    try:
        from pyoas.fastapi import RouterGenerator
    except ImportError:
        missing.append("pyoas[fastapi]")

    if missing:
        for pkg in missing:
            typer.echo(f"Error: {pkg} is not installed.", err=True)
        raise typer.Exit(1)

    cfg = _load_cfg(config)
    tag_filter = _tag_filter(tags)
    changed: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_models = str(Path(tmp) / "models")
        tmp_routers = str(Path(tmp) / "routers")

        import copy

        tmp_cfg = copy.deepcopy(cfg)
        tmp_cfg.output.models = tmp_models
        tmp_cfg.output.routers = tmp_routers

        ModelGenerator(tmp_cfg).generate(tag_filter=tag_filter)  # type: ignore[possibly-undefined]
        RouterGenerator(tmp_cfg).generate(tag_filter=tag_filter)  # type: ignore[possibly-undefined]

        for target_root, actual_root in (
            (tmp_models, cfg.output.models),
            (tmp_routers, cfg.output.routers),
        ):
            target = Path(target_root)
            actual = Path(actual_root)
            for new_file in sorted(target.rglob("*.py")):
                rel = new_file.relative_to(target)
                existing = actual / rel
                if not existing.exists():
                    typer.echo(f"  [new]      {existing}")
                    changed.append(str(existing))
                elif new_file.read_text() != existing.read_text():
                    typer.echo(f"  [modified] {existing}")
                    changed.append(str(existing))

            # Files that exist on disk but not in new output (would be deleted by --clean)
            if actual.exists():
                for old_file in sorted(actual.rglob("*.py")):
                    rel = old_file.relative_to(actual)
                    if not (target / rel).exists():
                        typer.echo(f"  [removed]  {old_file}")
                        changed.append(str(old_file))

    if cfg.services.generate:
        try:
            for item in _scaffold_service_drift(cfg, tag_filter):
                typer.echo(f"  [missing]  {item}")
                changed.append(item)
        except ImportError:
            pass

    if cfg.tests.generate:
        try:
            for item in _scaffold_test_drift(cfg, tag_filter):
                typer.echo(f"  [missing]  {item}")
                changed.append(item)
        except ImportError:
            pass

    if cfg.dependencies.generate:
        for item in _scaffold_dep_drift(cfg):
            typer.echo(f"  [missing]  {item}")
            changed.append(item)

    if changed:
        typer.echo(
            f"\n{len(changed)} file(s) would change. Run `pyoas generate` to update."
        )
        raise typer.Exit(1)
    else:
        typer.echo("All generated files are up to date.")


@app.command()
def validate(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit results as a JSON object to stdout")
    ] = False,
) -> None:
    """Validate the OpenAPI spec referenced in the config and exit non-zero on errors."""
    import json as _json

    from pyoas.core.parser import SpecParser

    cfg = _load_cfg(config)
    try:
        SpecParser(cfg.spec).load()
        if json_output:
            typer.echo(_json.dumps({"status": "ok", "spec": cfg.spec, "error": None}))
        else:
            typer.echo(f"OK  {cfg.spec}")
    except (ValueError, FileNotFoundError) as exc:
        if json_output:
            typer.echo(
                _json.dumps({"status": "error", "spec": cfg.spec, "error": str(exc)})
            )
        else:
            typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


@app.command()
def migrate(
    old_spec: Annotated[
        str, typer.Argument(help="Path or URL of the old (baseline) spec")
    ],
    new_spec: Annotated[str, typer.Argument(help="Path or URL of the new spec")],
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit results as a JSON object to stdout")
    ] = False,
    breaking_only: Annotated[
        bool,
        typer.Option(
            "--breaking-only",
            help="Only report breaking changes (suppress non-breaking)",
        ),
    ] = False,
) -> None:
    """Diff two OpenAPI specs and exit non-zero if breaking changes are found."""
    from pyoas.core.migrate import run_migrate as _run_migrate

    raise typer.Exit(
        _run_migrate(
            old_spec, new_spec, json_output=json_output, breaking_only=breaking_only
        )
    )


@app.command()
def doctor(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit results as a JSON object to stdout")
    ] = False,
) -> None:
    """Run pre-flight diagnostic checks on the spec and config."""
    import json as _json
    from pathlib import Path as _Path

    import yaml as _yaml

    from pyoas.core.doctor import run_doctor_checks

    cfg = _load_cfg(config)
    # Load raw spec without openapi-spec-validator so doctor can check specs that
    # have semantic errors (e.g. duplicate operationIds) and report them nicely.
    try:
        p = _Path(cfg.spec)
        text = p.read_text(encoding="utf-8")
        spec_raw = (
            _json.loads(text) if p.suffix.lower() == ".json" else _yaml.safe_load(text)
        )
    except (FileNotFoundError, OSError) as exc:
        typer.echo(f"Error loading spec: {exc}", err=True)
        raise typer.Exit(1)

    issues = run_doctor_checks(spec_raw, cfg)

    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]

    if json_output:
        data = {
            "status": "error" if errors else "ok",
            "issues": [
                {
                    "level": i.level,
                    "check": i.check,
                    "message": i.message,
                    "location": i.location,
                }
                for i in issues
            ],
        }
        typer.echo(_json.dumps(data))
        if errors:
            raise typer.Exit(1)
        return

    for issue in issues:
        tag = f"[{issue.level.upper()}]"
        color = typer.colors.RED if issue.level == "error" else typer.colors.YELLOW
        styled_tag = typer.style(f"  {tag:<10}", fg=color)
        typer.echo(f"{styled_tag} {issue.check:<30} {issue.location} — {issue.message}")

    if issues:
        typer.echo(f"\n  {len(errors)} error(s), {len(warnings)} warning(s)")
    else:
        typer.echo("  No issues found.")

    if errors:
        raise typer.Exit(1)


@app.command()
def fix(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Print proposed changes without writing the spec"
        ),
    ] = False,
    tag_casing: Annotated[
        str,
        typer.Option(
            help="Canonical tag casing: 'title' (e.g. Pet Store) or 'lower' (e.g. pet store)"
        ),
    ] = "title",
) -> None:
    """Auto-fix common spec issues: assign operationIds, deduplicate, normalize tags."""
    import difflib
    import json as _json
    from pathlib import Path as _Path

    import yaml as _yaml

    from pyoas.core.doctor import run_doctor_checks
    from pyoas.core.fixer import fix_spec, serialize_spec

    cfg = _load_cfg(config)
    try:
        p = _Path(cfg.spec)
        original_text = p.read_text(encoding="utf-8")
        spec_raw = (
            _json.loads(original_text)
            if p.suffix.lower() == ".json"
            else _yaml.safe_load(original_text)
        )
    except (FileNotFoundError, OSError) as exc:
        typer.echo(f"Error loading spec: {exc}", err=True)
        raise typer.Exit(1)

    fixed_spec, actions = fix_spec(spec_raw, cfg, tag_casing=tag_casing)

    if not actions:
        typer.echo("  No fixable issues found.")
        return

    # Print action summary
    kind_color: dict[str, str] = {
        "assign_operation_id": typer.colors.GREEN,
        "dedupe_operation_id": typer.colors.YELLOW,
        "normalize_tag": typer.colors.CYAN,
        "normalize_tags_list": typer.colors.CYAN,
    }
    for action in actions:
        color = kind_color.get(action.kind, typer.colors.WHITE)
        styled = typer.style("  [FIXED]", fg=color)
        typer.echo(f"{styled}  {action.kind:<25} {action.location} — {action.message}")

    new_text = serialize_spec(fixed_spec, p.suffix)

    if dry_run:
        diff = list(
            difflib.unified_diff(
                original_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"{cfg.spec} (before)",
                tofile=f"{cfg.spec} (after)",
            )
        )
        typer.echo("")
        for line in diff:
            typer.echo(line, nl=False)
        typer.echo(
            f"\n  {len(actions)} fix(es) would be applied. Re-run without --dry-run to write."
        )
        return

    p.write_text(new_text, encoding="utf-8")
    typer.echo(f"\n  {len(actions)} fix(es) applied. Spec updated: {cfg.spec}")

    # Re-run doctor to confirm resolution
    issues = run_doctor_checks(fixed_spec, cfg)
    remaining_errors = [i for i in issues if i.level == "error"]
    if remaining_errors:
        typer.echo(
            f"\n  {len(remaining_errors)} error(s) remain that fix cannot resolve:",
            err=True,
        )
        for issue in remaining_errors:
            typer.echo(
                f"    [{issue.check}] {issue.location} — {issue.message}", err=True
            )
        raise typer.Exit(1)
    else:
        typer.echo("  Doctor: all fixable issues resolved.")


@app.command()
def drift(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
    tags: Annotated[str | None, _TAGS_OPTION] = None,
) -> None:
    """Report service method drift without writing anything. Exits 1 if drift is found."""
    try:
        from pyoas.fastapi.scaffold import detect_service_drift
    except ImportError:
        typer.echo(
            'Error: pyoas[fastapi] extra is required. Run: pip install "pyoas[fastapi]"',
            err=True,
        )
        raise typer.Exit(1)

    cfg = _load_cfg(config)
    tag_filter = _tag_filter(tags)

    if not cfg.services.generate and not cfg.services.import_path:
        typer.echo(
            "Service generation is not configured. Set services.generate: true in config."
        )
        return

    items = detect_service_drift(cfg, tag_filter=tag_filter)

    for item in items:
        if item.kind == "missing_file":
            typer.echo(f"  [missing file]   {item.file}")
        elif item.kind == "missing_method":
            typer.echo(f"  [missing method] {item.file}::{item.method}")
        elif item.kind == "orphaned_method":
            typer.echo(f"  [orphaned]       {item.file}::{item.method}")
        elif item.kind == "signature_changed":
            typer.echo(f"  [sig changed]    {item.file}::{item.method}")
            for line in item.detail.split("\n")[1:]:
                typer.echo(f"    {line.strip()}")

    if items:
        typer.echo(
            f"\n  {len(items)} drift item(s) found. Run pyoas scaffold services to fix."
        )
        raise typer.Exit(1)
    else:
        typer.echo("No drift detected.")


@scaffold_app.command("dependencies")
def scaffold_dependencies(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
) -> None:
    """Scaffold dependency stub files (skips existing files unless overwrite: true in config)."""
    try:
        from pyoas.fastapi import DependencyScaffolder
    except ImportError:
        typer.echo(
            'Error: pyoas[fastapi] extra is required. Run: pip install "pyoas[fastapi]"',
            err=True,
        )
        raise typer.Exit(1)

    DependencyScaffolder(_load_cfg(config)).scaffold()


@scaffold_app.command("services")
def scaffold_services(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
) -> None:
    """Scaffold service stub files (skips existing files unless overwrite: true in config)."""
    try:
        from pyoas.fastapi import ServiceScaffolder
    except ImportError:
        typer.echo(
            'Error: pyoas[fastapi] extra is required. Run: pip install "pyoas[fastapi]"',
            err=True,
        )
        raise typer.Exit(1)

    ServiceScaffolder(_load_cfg(config)).scaffold()


@scaffold_app.command("tests")
def scaffold_tests(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
) -> None:
    """Scaffold test stub files (skips existing files unless overwrite: true in config)."""
    try:
        from pyoas.fastapi import ServiceTestScaffolder, TestScaffolder
    except ImportError:
        typer.echo(
            'Error: pyoas[fastapi] extra is required. Run: pip install "pyoas[fastapi]"',
            err=True,
        )
        raise typer.Exit(1)

    cfg = _load_cfg(config)
    TestScaffolder(cfg).scaffold()
    ServiceTestScaffolder(cfg).scaffold()


@scaffold_app.command("skills")
def scaffold_skills(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
) -> None:
    """Scaffold Claude skill files (skips existing files unless overwrite: true in config)."""
    try:
        from pyoas.claude import SkillScaffolder
    except ImportError:
        typer.echo(
            'Run: pip install "pyoas[claude]" to generate Claude skills.', err=True
        )
        raise typer.Exit(1)

    SkillScaffolder(_load_cfg(config)).scaffold()


@scaffold_app.command("webhooks")
def scaffold_webhooks(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
) -> None:
    """Show how to mount generated webhook routers onto your FastAPI app."""
    cfg = _load_cfg(config)

    if not cfg.webhooks.generate:
        typer.echo(
            "Webhook generation is not enabled. "
            "Set webhooks.generate: true in pyoas.yaml to enable."
        )
        return

    from pyoas.core.parsed_spec import ParsedSpec
    from pyoas.core.tags import extract_tags
    from pyoas.core.utils import tag_to_dirname

    spec = ParsedSpec.from_config(cfg).resolved
    grouped = extract_tags(spec, default_tag=cfg.default_tag, include_webhooks=True)

    webhook_tags = [
        tag for tag, ops in grouped.items() if any(op.get("is_webhook") for op in ops)
    ]

    if not webhook_tags:
        typer.echo("No webhook operations found in spec.")
        return

    routers_import = cfg.output.routers_import
    typer.echo("To mount webhook routers in your FastAPI app:\n")
    typer.echo("    from fastapi import FastAPI")
    typer.echo("    app = FastAPI()\n")
    for tag in webhook_tags:
        dirname = tag_to_dirname(tag)
        typer.echo(
            f"    from {routers_import}.{dirname} import webhooks as {dirname}_webhooks"
        )
    typer.echo("")
    for tag in webhook_tags:
        dirname = tag_to_dirname(tag)
        typer.echo(f"    app.webhooks.include_router({dirname}_webhooks)")


@app.command()
def watch(
    config: Annotated[str, _CONFIG_OPTION] = "pyoas.yaml",
    tags: Annotated[str | None, _TAGS_OPTION] = None,
) -> None:
    """Watch the spec file and re-generate on every change. Press Ctrl+C to stop."""
    try:
        from watchfiles import watch as _watch
    except ImportError:
        typer.echo(
            "Error: watchfiles is not installed. Run: pip install watchfiles", err=True
        )
        raise typer.Exit(1)

    missing: list[str] = []
    try:
        from pyoas.models import ModelGenerator
    except ImportError:
        missing.append("pyoas")

    try:
        from pyoas.fastapi import RouterGenerator
    except ImportError:
        missing.append("pyoas[fastapi]")

    if missing:
        for pkg in missing:
            typer.echo(
                f"Error: {pkg} is not installed. Run: pip install {pkg}", err=True
            )
        raise typer.Exit(1)

    cfg = _load_cfg(config)
    typer.echo(f"Watching {cfg.spec} … (Ctrl+C to stop)")

    for _ in _watch(cfg.spec):
        typer.echo("Change detected — regenerating …")
        try:
            cfg = _load_cfg(config)
            tag_filter = _tag_filter(tags)
            ModelGenerator(cfg).generate(tag_filter=tag_filter)  # type: ignore[possibly-undefined]
            RouterGenerator(cfg).generate(tag_filter=tag_filter)  # type: ignore[possibly-undefined]

            if cfg.dependencies.generate:
                from pyoas.fastapi import DependencyScaffolder

                DependencyScaffolder(cfg).scaffold()

            if cfg.services.generate:
                from pyoas.fastapi import ServiceScaffolder

                ServiceScaffolder(cfg).scaffold(tag_filter=tag_filter)

            if cfg.tests.generate:
                from pyoas.fastapi import ServiceTestScaffolder, TestScaffolder

                TestScaffolder(cfg).scaffold(tag_filter=tag_filter)
                ServiceTestScaffolder(cfg).scaffold(tag_filter=tag_filter)

            if cfg.skills.generate:
                try:
                    from pyoas.claude import SkillScaffolder

                    SkillScaffolder(cfg).scaffold()
                except ImportError:
                    typer.echo(
                        'Run: pip install "pyoas[claude]" to generate Claude skills.',
                        err=True,
                    )

            typer.echo("Done.")
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"Error during generation: {exc}", err=True)


def _scaffold_service_drift(cfg, tag_filter: list[str] | None) -> list[str]:  # noqa: ANN001
    """Return service file paths / method refs that would be created or appended."""
    from pyoas.fastapi.scaffold import detect_service_drift

    items = detect_service_drift(cfg, tag_filter=tag_filter)
    result: list[str] = []
    for item in items:
        if item.kind == "missing_file":
            result.append(item.file)
        elif item.kind == "missing_method":
            result.append(f"{item.file}::{item.method}")
    return result


def _scaffold_test_drift(cfg, tag_filter: list[str] | None) -> list[str]:  # noqa: ANN001
    """Return test file paths / class refs that would be created or appended."""
    import re

    from pyoas.core.parser import SpecParser
    from pyoas.core.resolver import resolve_refs
    from pyoas.core.tags import extract_tags
    from pyoas.fastapi.testscaffold import _build_test_context

    spec_raw = SpecParser(cfg.spec).load()
    spec = resolve_refs(spec_raw, cfg.spec)
    grouped = extract_tags(spec, default_tag=cfg.default_tag)
    grouped_raw = extract_tags(spec_raw, default_tag=cfg.default_tag)
    if tag_filter:
        grouped = {k: v for k, v in grouped.items() if k in tag_filter}

    result: list[str] = []
    test_root = Path(cfg.tests.output)
    for tag, operations in grouped.items():
        raw_ops = grouped_raw.get(tag, [])
        merged = [
            {**op, "raw_operation": raw_op["operation"]}
            for op, raw_op in zip(operations, raw_ops)
        ]
        context = _build_test_context(tag, merged, cfg)
        tag_dirname = re.sub(r"[^a-z0-9_]", "_", tag.lower()).strip("_")
        test_file = test_root / f"test_{tag_dirname}.py"
        expected = {op["class_name"] for op in context["operations"]}
        if not test_file.exists():
            result.append(str(test_file))
        else:
            existing = set(
                re.findall(
                    r"^class (Test\w+):",
                    test_file.read_text(encoding="utf-8"),
                    re.MULTILINE,
                )
            )
            for cls in sorted(expected - existing):
                result.append(f"{test_file}::{cls}")
    return result


def _scaffold_dep_drift(cfg) -> list[str]:  # noqa: ANN001
    """Return dependency file paths that are missing from the configured output."""
    output_root = Path(cfg.dependencies.output)
    missing: list[str] = []
    auth_file = output_root / "auth.py"
    if not auth_file.exists():
        missing.append(str(auth_file))
    return missing
