"""
TestScaffolder — writes pytest test stub files, adding missing test classes on re-runs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, TypedDict

import typer

from pyoas.core.analysis import build_schema_tag_map, detect_generic_groups_global
from pyoas.core.config import Config
from pyoas.core.parser import SpecParser
from pyoas.core.renderer import Renderer
from pyoas.core.resolver import resolve_refs
from pyoas.core.result import ScaffoldResult
from pyoas.core.tags import extract_tags
from pyoas.core.utils import (
    derive_import_path,
    generate_function_name,
    to_pascal_case,
    to_snake_case,
)

from .generator import _has_security
from .params import (
    _annotated_base_type,
    build_function_params,
    resolve_response_status_code,
    resolve_response_type,
)

_DEFAULT_TEMPLATES = Path(__file__).parent / "templates"

_PATH_PARAM_EXAMPLES: dict[str, str] = {
    "int": "1",
    "float": "1.0",
    "str": "example",
    "uuid.UUID": "00000000-0000-0000-0000-000000000001",
    "bool": "true",
}

# Maps a numeric constraint key to a test-name suffix describing the violation.
_CONSTRAINT_SUFFIX: dict[str, str] = {
    "ge": "below_minimum",
    "gt": "at_minimum",
    "le": "above_maximum",
    "lt": "at_maximum",
}

# Sensible default values per JSON/OpenAPI scalar type for body field test construction.
_FIELD_TYPE_DEFAULTS: dict[str, Any] = {
    "integer": 1,
    "number": 1.0,
    "string": "example",
    "boolean": True,
}

# Wrong-type values per field type.  String fields are intentionally omitted:
# Pydantic v2 lax mode coerces integers to strings, so sending 0 for a str field
# would NOT produce a 422.
_WRONG_TYPE_VALUES: dict[str, Any] = {
    "integer": "not-an-integer",
    "number": "not-a-number",
    "boolean": "not-a-boolean",
}

# Primitive Python type names that should not produce model factories.
_PRIMITIVE_TYPES: frozenset[str] = frozenset(
    {"None", "str", "int", "float", "bool", "bytes", "Any"}
)

# Typing/stdlib names that look like classes but are not model factories.
_NON_MODEL_NAMES: frozenset[str] = frozenset(
    {
        "None",
        "Any",
        "Union",
        "Optional",
        "Annotated",
        "Literal",
        "List",
        "Dict",
        "Tuple",
        "Set",
        "Type",
        "Callable",
    }
)


def _constraint_violation(key: str, value: Any) -> Any:
    """Return a value that violates the given boundary constraint by one unit."""
    if key == "ge":
        return value - 1 if isinstance(value, int) else value - 1.0
    if key == "gt":
        return value  # exactly at the exclusive lower bound
    if key == "le":
        return value + 1 if isinstance(value, int) else value + 1.0
    # lt — exactly at the exclusive upper bound
    return value


def _normalize_response_type(type_str: str) -> str | None:
    """Return the concrete model type to generate a factory for, or None if skipped.

    Unwraps ``list[T]`` to ``T`` (the test body constructs ``[make_t()]`` itself).
    Strips ``| None`` optionality.  Returns None for primitives and inline types.
    """
    ts = type_str.strip()
    # Strip | None wrappers.
    ts = re.sub(r"\s*\|\s*None\b", "", ts).strip()
    ts = re.sub(r"\bNone\s*\|\s*", "", ts).strip()
    if not ts or ts in _PRIMITIVE_TYPES:
        return None
    # Unwrap list[T] → T.
    m = re.match(r"^list\[(.+)\]$", ts)
    if m:
        ts = m.group(1).strip()
    # Must start with uppercase to be a named model.
    if not ts or not ts[0].isupper():
        return None
    return ts


def _bare_model_names(type_str: str) -> set[str]:
    """Extract named model class names from a Python type annotation string."""
    names = set(re.findall(r"\b([A-Z][A-Za-z0-9_]*)\b", type_str))
    return names - _NON_MODEL_NAMES


def _type_to_factory_name(type_str: str) -> str:
    """Convert a model type string to a make_* factory function name.

    Examples::

        "Pet"             -> "make_pet"
        "PetList"         -> "make_pet_list"
        "Paginated[Item]" -> "make_paginated_item"
    """
    cleaned = re.sub(r"[\[\],\s]+", " ", type_str).strip()
    parts = [p for p in cleaned.split() if p]
    snake_parts = [to_snake_case(p) for p in parts]
    return "make_" + "_".join(snake_parts)


def _factory_class_name(func_name: str) -> str:
    """Convert a make_* function name to a ModelFactory class name.

    Examples::

        "make_pet"            -> "PetFactory"
        "make_pet_list"       -> "PetListFactory"
        "make_paginated_item" -> "PaginatedItemFactory"
    """
    return to_pascal_case(func_name[len("make_") :]) + "Factory"


def _default_value_for_field(schema: dict[str, Any]) -> Any:
    """Return a sensible valid value for a body field schema.

    Used to construct the 'valid base body' in body-field constraint tests.
    The returned value satisfies all constraints so only the one field under
    test is invalid.
    """
    if "default" in schema:
        return schema["default"]
    if "example" in schema:
        return schema["example"]
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type", "string")
    base: Any = _FIELD_TYPE_DEFAULTS.get(t, "example")
    if t in ("integer", "number"):
        mn = schema.get("minimum")
        if mn is not None:
            base = int(mn) + 1 if t == "integer" else float(mn) + 1.0
    if t == "string":
        ml = schema.get("minLength")
        if ml:
            base = "a" * ml
    return base


def _extract_body_field_tests(body_schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate test entries for body field constraint and type violations.

    Only processes simple object schemas with top-level ``properties``.
    Schemas using ``allOf``/``anyOf``/``oneOf`` are skipped — their shape is
    too complex to construct a reliable 'valid body minus one bad field'.
    """
    if any(k in body_schema for k in ("allOf", "anyOf", "oneOf")):
        return []
    properties: dict[str, Any] = body_schema.get("properties", {})
    if not properties:
        return []
    required_fields = set(body_schema.get("required", []))

    # Build a valid base body from all required fields.
    valid_body_base = {
        fname: _default_value_for_field(fschema)
        for fname, fschema in properties.items()
        if fname in required_fields and not fschema.get("readOnly")
    }

    tests: list[dict[str, Any]] = []
    for field_name, field_schema in properties.items():
        if field_schema.get("readOnly"):
            continue
        snake_name = to_snake_case(field_name)

        def _add(test_name: str, bad_value: Any, docstring: str) -> None:
            merged = {**valid_body_base, field_name: bad_value}
            tests.append(
                {
                    "field_name": snake_name,
                    "test_name": test_name,
                    "docstring": docstring,
                    "json_repr": repr(merged),
                }
            )

        # Numeric constraint violations.
        if "minimum" in field_schema:
            val = field_schema["minimum"]
            bad: Any = (val - 1) if isinstance(val, int) else (val - 1.0)
            _add(
                f"test_{snake_name}_below_minimum",
                bad,
                f"Verify validation rejects {snake_name} below minimum (expects 422).",
            )
        if "maximum" in field_schema:
            val = field_schema["maximum"]
            bad = (val + 1) if isinstance(val, int) else (val + 1.0)
            _add(
                f"test_{snake_name}_above_maximum",
                bad,
                f"Verify validation rejects {snake_name} above maximum (expects 422).",
            )

        # String constraint violations.
        if "minLength" in field_schema:
            n: int = field_schema["minLength"]
            bad = "" if n <= 1 else "a" * (n - 1)
            _add(
                f"test_{snake_name}_too_short",
                bad,
                f"Verify validation rejects {snake_name} that is too short (expects 422).",
            )
        if "maxLength" in field_schema:
            n = field_schema["maxLength"]
            bad = "a" * (n + 1)
            _add(
                f"test_{snake_name}_too_long",
                bad,
                f"Verify validation rejects {snake_name} that is too long (expects 422).",
            )
        if "pattern" in field_schema:
            _add(
                f"test_{snake_name}_pattern_mismatch",
                "!INVALID!",
                f"Verify validation rejects {snake_name} not matching pattern (expects 422).",
            )

        # Wrong-type violations for required scalar fields only.
        if field_name in required_fields:
            ft = field_schema.get("type")
            wrong_val = _WRONG_TYPE_VALUES.get(ft)  # type: ignore[arg-type]
            if wrong_val is not None:
                _add(
                    f"test_{snake_name}_wrong_type",
                    wrong_val,
                    f"Verify validation rejects wrong type for {snake_name} (expects 422).",
                )

    return tests


def _default_mock_return_repr(type_str: str) -> str | None:
    """Return a repr for a sensible mock return value for primitive/generic response types.

    Used when response_factory is None but the return type is not None, to prevent
    AsyncMock from leaking into FastAPI's response serializer.
    Returns None for -> None endpoints (no mock setup needed).
    """
    ts = type_str.strip()
    if not ts or ts == "None":
        return None
    # Strip | None optionality.
    ts = re.sub(r"\s*\|\s*None\b", "", ts).strip()
    ts = re.sub(r"\bNone\s*\|\s*", "", ts).strip()
    if ts.lower().startswith("list[") or ts == "list":
        return "[]"
    if ts.lower().startswith("dict[") or ts == "dict":
        return "{}"
    if ts == "str":
        return '"example"'
    if ts == "int":
        return "0"
    if ts == "float":
        return "0.0"
    if ts == "bool":
        return "True"
    if ts == "bytes":
        return 'b""'
    if ts == "Any":
        return "{}"
    # Named model types are handled by response_factory; return None here.
    return None


def _minimal_body_repr(body_schema: dict[str, Any]) -> str | None:
    """Return repr of a minimal valid body for the given schema, or None if no body."""
    if not body_schema:
        return None
    if any(k in body_schema for k in ("allOf", "anyOf", "oneOf")):
        return repr({})
    properties: dict[str, Any] = body_schema.get("properties", {})
    required_fields = set(body_schema.get("required", []))
    if not required_fields:
        return repr({})
    minimal = {
        fname: _default_value_for_field(fschema)
        for fname, fschema in properties.items()
        if fname in required_fields and not fschema.get("readOnly")
    }
    return repr(minimal)


class TestScaffolder:
    def __init__(self, config: Config) -> None:
        self._config = config

    def scaffold(self, tag_filter: list[str] | None = None) -> ScaffoldResult:
        result = ScaffoldResult()
        cfg = self._config
        if not cfg.tests.generate:
            typer.echo(
                "Test generation is not configured. Set tests.generate: true in config."
            )
            return result

        spec_raw = SpecParser(cfg.spec).load()
        spec = resolve_refs(spec_raw, cfg.spec)
        grouped = extract_tags(spec, default_tag=cfg.default_tag)
        grouped_raw = extract_tags(spec_raw, default_tag=cfg.default_tag)

        if tag_filter:
            grouped = {k: v for k, v in grouped.items() if k in tag_filter}
            # grouped_raw stays full so schema_tag_map correctly identifies shared schemas.

        global_security: list[Any] = spec_raw.get("security") or []
        raw_cs = spec_raw.get("components", {}).get("schemas", {})
        schema_tag_map = build_schema_tag_map(spec_raw, grouped_raw)
        generic_groups = detect_generic_groups_global(raw_cs, schema_tag_map)
        generic_name_map: dict[str, str] = {
            inst["schema_name"]: f"{g.generic_name}[{inst['type_param']}]"
            for g in generic_groups.values()
            for inst in g.instances
        }

        renderer = Renderer(default_templates_dir=_DEFAULT_TEMPLATES)
        output_root = Path(cfg.tests.output)
        output_root.mkdir(parents=True, exist_ok=True)

        all_tag_models: list[dict[str, Any]] = []

        for tag, operations in grouped.items():
            raw_operations = grouped_raw.get(tag, [])
            merged = [
                {**op, "raw_operation": raw_op["operation"]}
                for op, raw_op in zip(operations, raw_operations)
            ]
            context, tag_result = self._scaffold_tag(
                tag, merged, renderer, output_root, generic_name_map, global_security
            )
            result.wrote += tag_result.wrote
            result.appended_items += tag_result.appended_items
            result.appended_files.extend(tag_result.appended_files)
            response_models: list[dict[str, Any]] = context["response_models"]
            if response_models:
                all_tag_models.append(
                    {
                        "tag_dirname": context["tag_dirname"],
                        "factories": response_models,
                        "import_names": sorted(
                            {n for rm in response_models for n in rm["import_names"]}
                        ),
                    }
                )

        root_init = output_root / "__init__.py"
        if not root_init.exists():
            root_init.write_text(
                "# Scaffolded by pyoas — safe to edit.\n", encoding="utf-8"
            )

        # Build a globally deduplicated factory list and correct each model's import
        # module using schema_tag_map.  Schemas referenced by multiple tags live in
        # `shared`; those referenced by exactly one tag live in that tag's module.
        import_groups: dict[str, set[str]] = {}
        seen_factory_types: set[str] = set()
        deduped_factories: list[dict[str, Any]] = []
        for entry in all_tag_models:
            for factory in entry["factories"]:
                for name in factory["import_names"]:
                    tags_for_name = schema_tag_map.get(name, set())
                    if len(tags_for_name) > 1:
                        module = "shared"
                    elif len(tags_for_name) == 1:
                        t = next(iter(tags_for_name))
                        module = re.sub(r"[^a-z0-9_]", "_", t.lower()).strip("_")
                    else:
                        # Inline or generic base — fall back to the entry's tag module.
                        module = entry["tag_dirname"]
                    import_groups.setdefault(module, set()).add(name)
                if factory["type_str"] not in seen_factory_types:
                    seen_factory_types.add(factory["type_str"])
                    deduped_factories.append(factory)
        conftest_import_groups = {
            k: sorted(v) for k, v in sorted(import_groups.items())
        }
        conftest_factories = sorted(deduped_factories, key=lambda f: f["type_str"])

        models_import_path = cfg.output.models_import or derive_import_path(
            cfg.output.models, cfg.output.source_root
        )
        conftest_result = self._scaffold_conftest(
            conftest_factories,
            conftest_import_groups,
            renderer,
            output_root,
            models_import_path,
        )
        result.wrote += conftest_result.wrote
        return result

    def _scaffold_tag(
        self,
        tag: str,
        operations: list[dict[str, Any]],
        renderer: Renderer,
        output_root: Path,
        generic_name_map: dict[str, str] | None = None,
        global_security: list[Any] | None = None,
    ) -> tuple[dict[str, Any], ScaffoldResult]:
        tag_result = ScaffoldResult()
        tag_dirname = re.sub(r"[^a-z0-9_]", "_", tag.lower()).strip("_")
        test_file = output_root / f"test_{tag_dirname}.py"

        context = _build_test_context(
            tag, operations, self._config, generic_name_map, global_security
        )

        if not test_file.exists() or self._config.tests.overwrite:
            src = renderer.render("test.py.jinja2", context)
            test_file.write_text(src, encoding="utf-8")
            typer.echo(typer.style(f"  wrote  {test_file}", fg=typer.colors.GREEN))
            tag_result.wrote = 1
            return context, tag_result

        # File exists and overwrite=False — append only missing test classes.
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
            return context, tag_result

        stubs = _render_class_stubs(new_ops, has_services=context["has_services"])
        updated = existing_src.rstrip() + "\n\n" + stubs
        test_file.write_text(updated, encoding="utf-8")
        typer.echo(
            typer.style(
                f"  added  {len(new_ops)} test class(es) to {test_file}",
                fg=typer.colors.GREEN,
            )
        )
        tag_result.appended_items = len(new_ops)
        tag_result.appended_files = [tag_dirname]
        return context, tag_result

    def _scaffold_conftest(
        self,
        factories: list[dict[str, Any]],
        import_groups: dict[str, list[str]],
        renderer: Renderer,
        output_root: Path,
        models_import_path: str,
    ) -> ScaffoldResult:
        """Write or append conftest.py with model factory stubs."""
        conftest_result = ScaffoldResult()
        if not factories:
            return conftest_result

        conftest_file = output_root / "conftest.py"
        context = {
            "factories": factories,
            "import_groups": import_groups,
            "models_import_path": models_import_path,
        }

        if not conftest_file.exists() or self._config.tests.overwrite:
            src = renderer.render("conftest.py.jinja2", context)
            conftest_file.write_text(src, encoding="utf-8")
            typer.echo(typer.style(f"  wrote  {conftest_file}", fg=typer.colors.GREEN))
            conftest_result.wrote = 1
            return conftest_result

        # Append-only: add only factory functions not already present.
        existing_src = conftest_file.read_text(encoding="utf-8")
        existing_funcs = set(
            re.findall(r"^def (make_\w+)\(", existing_src, re.MULTILINE)
        )
        existing_classes = set(
            re.findall(r"^class (\w+)\(", existing_src, re.MULTILINE)
        )

        # Warn about orphaned factories (exist in file but no longer in spec).
        current_func_names = {f["func_name"] for f in factories}
        for orphan in sorted(existing_funcs - current_func_names):
            typer.echo(
                f"Warning: orphaned factory '{orphan}' in {conftest_file} "
                "(no matching response type in spec).",
                err=True,
            )

        new_lines: list[str] = []
        for factory in factories:
            if factory["func_name"] not in existing_funcs:
                if factory["factory_class_name"] not in existing_classes:
                    new_lines.extend(
                        [
                            "",
                            f"class {factory['factory_class_name']}(ModelFactory):",
                            f"    __model__ = {factory['type_str']}",
                            "",
                        ]
                    )
                new_lines.extend(
                    [
                        "",
                        f"def {factory['func_name']}(**overrides) -> {factory['type_str']}:",
                        f'    """Minimal valid {factory["type_str"]}. Override fields as needed."""',
                        f"    return {factory['factory_class_name']}.build(**overrides)",
                    ]
                )

        if not new_lines:
            return conftest_result

        updated = existing_src.rstrip() + "\n" + "\n".join(new_lines) + "\n"
        conftest_file.write_text(updated, encoding="utf-8")
        count = sum(1 for line in new_lines if line.startswith("def "))
        typer.echo(
            typer.style(
                f"  added  {count} factory stub(s) to {conftest_file}",
                fg=typer.colors.GREEN,
            )
        )
        conftest_result.appended_items = count
        return conftest_result


class TestOperation(TypedDict):
    class_name: str
    function_name: str
    method: str
    path: str
    filled_path: str
    filled_query_params: str | None
    summary: str
    has_required_body: bool
    has_required_body_fields: bool
    needs_validation_test: bool
    parameters: list[dict[str, Any]]
    query_constraint_tests: list[dict[str, Any]]
    enum_violation_tests: list[dict[str, Any]]
    invalid_path_tests: list[dict[str, Any]]
    body_field_tests: list[dict[str, Any]]
    has_not_found_case: bool
    response_type_str: str
    response_factory: str | None
    success_status_code: int
    not_found_exception_expr: str
    not_found_body_repr: str | None
    default_mock_return_repr: str | None
    auto_implement_success: bool


def _build_test_context(
    tag: str,
    operations: list[dict[str, Any]],
    config: Config,
    generic_name_map: dict[str, str] | None = None,
    global_security: list[Any] | None = None,
) -> dict[str, Any]:
    has_services = bool(config.services.import_path)
    test_ops: list[TestOperation] = []

    for op_entry in operations:
        method: str = op_entry["method"]
        path: str = op_entry["path"]
        operation = op_entry["operation"]
        raw_operation = op_entry.get("raw_operation")

        fn_name = to_snake_case(
            operation.get("operationId") or generate_function_name(method, path)
        )
        class_name = "Test" + to_pascal_case(fn_name)

        params = build_function_params(
            operation,
            raw_operation=raw_operation,
            enums_as_literals=config.fields.enums_as_literals,
            generic_name_map=generic_name_map,
        )

        filled_path = _fill_path_params(path, params)
        _req_query = {
            p["name"]: _default_query_param_value(p)
            for p in params
            if p["required"]
            and p["location"] == "query"
            and p.get("default_repr") is None
        }
        filled_query_params = repr(_req_query) if _req_query else None
        has_required_body = any(
            p["required"] and p["location"] == "body" for p in params
        )
        needs_validation_test = any(
            p["required"] and p["location"] in ("body", "query") for p in params
        )

        # Required body fields — does the body schema declare any required properties?
        body_schema = (
            (operation.get("requestBody") or {})
            .get("content", {})
            .get("application/json", {})
            .get("schema", {})
        )
        body_required_fields = body_schema.get("required", []) if body_schema else []
        has_required_body_fields = bool(body_required_fields)

        # Query constraint violation tests — numeric bounds.
        query_constraint_tests: list[dict[str, Any]] = []
        for p in params:
            if p["location"] != "query":
                continue
            for ckey, cval in p.get("constraints", {}).items():
                query_constraint_tests.append(
                    {
                        "param_name": p["name"],
                        "test_name": f"test_{p['name']}_{_CONSTRAINT_SUFFIX[ckey]}",
                        "violation_expr": repr(_constraint_violation(ckey, cval)),
                    }
                )
            # String constraint violations (minLength, maxLength, pattern).
            sc = p.get("string_constraints", {})
            if "min_length" in sc:
                n: int = sc["min_length"]
                violation: Any = "" if n <= 1 else "a" * (n - 1)
                query_constraint_tests.append(
                    {
                        "param_name": p["name"],
                        "test_name": f"test_{p['name']}_too_short",
                        "violation_expr": repr(violation),
                    }
                )
            if "max_length" in sc:
                n = sc["max_length"]
                violation = "a" * (n + 1)
                query_constraint_tests.append(
                    {
                        "param_name": p["name"],
                        "test_name": f"test_{p['name']}_too_long",
                        "violation_expr": repr(violation),
                    }
                )
            if "pattern" in sc:
                query_constraint_tests.append(
                    {
                        "param_name": p["name"],
                        "test_name": f"test_{p['name']}_pattern_mismatch",
                        "violation_expr": repr("!INVALID!"),
                    }
                )

        # Enum violation tests — query and path params with an explicit enum.
        enum_violation_tests: list[dict[str, Any]] = []
        for p in params:
            if p["location"] not in ("query", "path"):
                continue
            ev = p.get("enum_values")
            if not ev:
                continue
            violation = "__invalid__" if isinstance(ev[0], str) else -9999
            if p["location"] == "path":
                invalid_path = path
                for other_p in params:
                    if other_p["location"] != "path":
                        continue
                    if other_p["alias"] == p["alias"]:
                        invalid_path = invalid_path.replace(
                            "{" + p["alias"] + "}", str(violation)
                        )
                    else:
                        other_base = (
                            _annotated_base_type(other_p["python_type"])
                            .split("[")[0]
                            .strip()
                        )
                        example = _PATH_PARAM_EXAMPLES.get(other_base, "1")
                        invalid_path = invalid_path.replace(
                            "{" + other_p["alias"] + "}", example
                        )
                response_call = f'client.{method}("{invalid_path}")'
            else:
                response_call = (
                    f'client.{method}("{filled_path}",'
                    f' params={{"{p["name"]}": {repr(violation)}}})'
                )
            enum_violation_tests.append(
                {
                    "param_name": p["name"],
                    "location": p["location"],
                    "test_name": f"test_{p['name']}_invalid_enum",
                    "violation_expr": repr(violation),
                    "response_call": response_call,
                }
            )

        # Path parameter type-mismatch tests (int/float/uuid params).
        invalid_path_tests: list[dict[str, Any]] = []
        for p in params:
            if p["location"] != "path":
                continue
            base = _annotated_base_type(p["python_type"]).split("[")[0].strip()
            if base not in ("int", "float", "uuid.UUID"):
                continue
            invalid_segment = "not-a-uuid" if base == "uuid.UUID" else "not-an-integer"
            type_description = "non-UUID" if base == "uuid.UUID" else "non-integer"
            # Build the path with this param replaced by an invalid value; fill others.
            invalid_path = path
            for other_p in params:
                if other_p["location"] != "path":
                    continue
                if other_p["alias"] == p["alias"]:
                    invalid_path = invalid_path.replace(
                        "{" + p["alias"] + "}", invalid_segment
                    )
                else:
                    other_base = (
                        _annotated_base_type(other_p["python_type"])
                        .split("[")[0]
                        .strip()
                    )
                    example = _PATH_PARAM_EXAMPLES.get(other_base, "1")
                    invalid_path = invalid_path.replace(
                        "{" + other_p["alias"] + "}", example
                    )
            invalid_path_tests.append(
                {
                    "test_name": f"test_invalid_{p['name']}_type",
                    "invalid_path": invalid_path,
                    "type_description": type_description,
                }
            )

        # Body field constraint / type-violation tests.
        body_field_tests = _extract_body_field_tests(body_schema) if body_schema else []

        # Not-found stub: GET / PATCH / DELETE with at least one integer path param.
        has_not_found_case = method in ("get", "patch", "delete") and any(
            p["location"] == "path"
            and _annotated_base_type(p["python_type"]).split("[")[0].strip()
            in ("int", "float", "uuid.UUID")
            for p in params
        )

        # Hint fields for test_success and test_not_found stubs.
        response_type_str = resolve_response_type(
            operation,
            raw_operation=raw_operation,
            enums_as_literals=config.fields.enums_as_literals,
            generic_name_map=generic_name_map,
        )
        _is_list_resp = bool(
            re.match(r"^list\[", response_type_str.strip(), re.IGNORECASE)
        )
        _normalized_resp = _normalize_response_type(response_type_str)
        if _normalized_resp:
            _factory_fn = _type_to_factory_name(_normalized_resp)
            response_factory: str | None = (
                f"[{_factory_fn}()]" if _is_list_resp else f"{_factory_fn}()"
            )
        else:
            response_factory = None
        success_status_code = resolve_response_status_code(operation)
        not_found_exception_expr = config.tests.not_found_exception or "<NotFoundError>"
        not_found_body_repr = (
            _minimal_body_repr(body_schema) if has_required_body else None
        )
        default_mock_return_repr = (
            _default_mock_return_repr(response_type_str)
            if not response_factory and response_type_str.strip() != "None"
            else None
        )
        auto_implement_success = method in ("get", "delete") and has_services

        test_ops.append(
            TestOperation(
                class_name=class_name,
                function_name=fn_name,
                method=method,
                path=path,
                filled_path=filled_path,
                filled_query_params=filled_query_params,
                summary=operation.get("summary", ""),
                has_required_body=has_required_body,
                has_required_body_fields=has_required_body_fields,
                needs_validation_test=needs_validation_test,
                parameters=params,
                query_constraint_tests=query_constraint_tests,
                enum_violation_tests=enum_violation_tests,
                invalid_path_tests=invalid_path_tests,
                body_field_tests=body_field_tests,
                has_not_found_case=has_not_found_case,
                response_type_str=response_type_str,
                response_factory=response_factory,
                success_status_code=success_status_code,
                not_found_exception_expr=not_found_exception_expr,
                not_found_body_repr=not_found_body_repr,
                default_mock_return_repr=default_mock_return_repr,
                auto_implement_success=auto_implement_success,
            )
        )

    # Collect unique response model types for conftest factory generation.
    seen_types: dict[str, dict[str, Any]] = {}
    for op_entry in operations:
        type_str = resolve_response_type(
            op_entry["operation"],
            raw_operation=op_entry.get("raw_operation"),
            enums_as_literals=config.fields.enums_as_literals,
            generic_name_map=generic_name_map,
        )
        normalized = _normalize_response_type(type_str)
        if normalized and normalized not in seen_types:
            func_name = _type_to_factory_name(normalized)
            seen_types[normalized] = {
                "type_str": normalized,
                "func_name": func_name,
                "factory_class_name": _factory_class_name(func_name),
                "import_names": sorted(_bare_model_names(normalized)),
            }
    response_models = sorted(seen_types.values(), key=lambda x: x["type_str"])

    # Collect factory functions needed by test_endpoint_exists (when has_services)
    # and auto-implemented test_success stubs.
    _auto_fns: set[str] = set()
    for _op in test_ops:
        if has_services and _op["response_factory"]:
            _auto_fns.update(re.findall(r"(make_\w+)", _op["response_factory"]))
    auto_impl_factories = sorted(_auto_fns)

    # Derive conftest import path for the auto-implemented factory calls.
    # Resolve the tests output path relative to the spec/config directory so
    # the import path is stable regardless of the cwd when pyoas is run.
    _tests_rel = config.tests.output
    _tp = Path(_tests_rel)
    if _tp.is_absolute():
        project_root = Path(config.spec).parent
        try:
            _tests_rel = str(_tp.relative_to(project_root))
        except ValueError:
            pass
    conftest_import_path = (
        derive_import_path(_tests_rel, config.output.source_root) + ".conftest"
        if auto_impl_factories
        else None
    )

    needs_http_exception_import = any(
        op["has_not_found_case"] and "HTTPException" in op["not_found_exception_expr"]
        for op in test_ops
    )

    tag_dirname = re.sub(r"[^a-z0-9_]", "_", tag.lower()).strip("_")
    router_import_path = config.output.routers_import or derive_import_path(
        config.output.routers, config.output.source_root
    )
    service_class_name = to_pascal_case(tag_dirname) + "Service"
    service_dep_fn = f"get_{tag_dirname}_service"

    dep_import_path = config.dependencies.import_path or None
    _gs = global_security or []
    has_auth_dep = bool(dep_import_path) and any(
        _has_security(op_entry["operation"], _gs) for op_entry in operations
    )

    return {
        "tag": tag,
        "tag_dirname": tag_dirname,
        "router_import_path": router_import_path,
        "has_services": has_services,
        "has_auth_dep": has_auth_dep,
        "auth_dep_import_path": dep_import_path,
        "needs_http_exception_import": needs_http_exception_import,
        "service_import_path": config.services.import_path or None,
        "service_class_name": service_class_name if has_services else None,
        "service_dep_fn": service_dep_fn if has_services else None,
        "operations": test_ops,
        "response_models": response_models,
        "conftest_import_path": conftest_import_path,
        "auto_impl_factories": auto_impl_factories,
    }


def _default_query_param_value(param: dict[str, Any]) -> Any:
    """Return a sensible default value for a required query param with no default."""
    inner = _annotated_base_type(param["python_type"])
    lit_m = re.match(r"^Literal\[(.+)\]$", inner)
    if lit_m:
        content = lit_m.group(1).strip()
        str_m = re.match(r'^"([^"]*)"', content) or re.match(r"^'([^']*)'", content)
        if str_m:
            return str_m.group(1)
        num_m = re.match(r"^(-?\d+)", content)
        if num_m:
            return int(num_m.group(1))
    base = inner.split("[")[0].strip()
    if base == "int":
        return 1
    if base == "float":
        return 0.0
    if base == "bool":
        return True
    return "example"


def _fill_path_params(path: str, params: list[dict[str, Any]]) -> str:
    result = path
    for p in params:
        if p["location"] == "path":
            # Use first enum value when the param is an enum/Literal type.
            ev = p.get("enum_values")
            if ev:
                example = str(ev[0])
            else:
                # Strip generics / Annotated wrapper for lookup.
                base = _annotated_base_type(p["python_type"]).split("[")[0].strip()
                example = _PATH_PARAM_EXAMPLES.get(base, "1")
            result = result.replace("{" + p["alias"] + "}", example)
    return result


def _render_class_stubs(
    operations: list[dict[str, Any]], *, has_services: bool = False
) -> str:
    """Render test class stubs as a plain string for append-only mode."""
    lines: list[str] = []
    for op in operations:
        lines.append(f"class {op['class_name']}:")
        lines.append(f'    """Tests for {op["method"].upper()} {op["path"]}"""')
        lines.append("")
        body_arg = ", json={}" if op["has_required_body"] else ""
        _params_arg = (
            f", params={op['filled_query_params']}"
            if op.get("filled_query_params")
            else ""
        )
        if has_services:
            mock_ret = op.get("response_factory") or op.get("default_mock_return_repr")
            lines.append(
                "    def test_endpoint_exists(self, client_with_mock: TestClient, mock_service: AsyncMock) -> None:"
            )
            lines.append('        """Verify endpoint responds (not 404/405)."""')
            if mock_ret:
                lines.append(
                    f"        mock_service.{op['function_name']}.return_value = {mock_ret}"
                )
            lines.append(
                f'        response = client_with_mock.{op["method"]}("{op["filled_path"]}"{body_arg}{_params_arg})'
            )
        else:
            lines.append(
                "    def test_endpoint_exists(self, client: TestClient) -> None:"
            )
            lines.append('        """Verify endpoint responds (not 404/405)."""')
            lines.append(
                f'        response = client.{op["method"]}("{op["filled_path"]}"{body_arg}{_params_arg})'
            )
        lines.append("        assert response.status_code not in (404, 405)")

        if op["needs_validation_test"]:
            lines.append("")
            lines.append(
                "    def test_validation_error(self, client: TestClient) -> None:"
            )
            lines.append(
                '        """Verify validation rejects missing required input (expects 422)."""'
            )
            lines.append(
                f'        response = client.{op["method"]}("{op["filled_path"]}")'
            )
            lines.append("        assert response.status_code == 422")

        if op["has_required_body"] and op["has_required_body_fields"]:
            lines.append("")
            lines.append(
                "    def test_missing_required_field(self, client: TestClient) -> None:"
            )
            lines.append(
                '        """Verify validation rejects body missing required fields (expects 422)."""'
            )
            lines.append(
                f'        response = client.{op["method"]}("{op["filled_path"]}", json={{}})'
            )
            lines.append("        assert response.status_code == 422")

        for ct in op["query_constraint_tests"]:
            lines.append("")
            lines.append(
                f"    def {ct['test_name']}(self, client: TestClient) -> None:"
            )
            lines.append(
                f'        """Verify validation rejects out-of-range {ct["param_name"]} (expects 422)."""'
            )
            lines.append(
                f'        response = client.{op["method"]}("{op["filled_path"]}", params={{"{ct["param_name"]}": {ct["violation_expr"]}}})'
            )
            lines.append("        assert response.status_code == 422")

        for ipt in op["invalid_path_tests"]:
            lines.append("")
            fixture = "client_with_mock" if has_services else "client"
            lines.append(
                f"    def {ipt['test_name']}(self, {fixture}: TestClient) -> None:"
            )
            lines.append(
                f'        """Verify validation rejects {ipt["type_description"]} path parameter (expects 422)."""'
            )
            lines.append(
                f'        response = {fixture}.{op["method"]}("{ipt["invalid_path"]}")'
            )
            lines.append("        assert response.status_code == 422")

        for et in op.get("enum_violation_tests", []):
            lines.append("")
            lines.append(
                f"    def {et['test_name']}(self, client: TestClient) -> None:"
            )
            lines.append(
                f'        """Verify validation rejects invalid enum value for {et["param_name"]} (expects 422)."""'
            )
            lines.append(f"        response = {et['response_call']}")
            lines.append("        assert response.status_code == 422")

        for ft in op.get("body_field_tests", []):
            lines.append("")
            lines.append(
                f"    def {ft['test_name']}(self, client: TestClient) -> None:"
            )
            lines.append(f'        """{ft["docstring"]}"""')
            lines.append(
                f'        response = client.{op["method"]}("{op["filled_path"]}", json={ft["json_repr"]})'
            )
            lines.append("        assert response.status_code == 422")

        if op["has_not_found_case"] and has_services:
            lines.append("")
            lines.append(
                "    def test_not_found(self, client_with_mock: TestClient, mock_service: AsyncMock) -> None:"
            )
            lines.append('        """Service raises not-found — expect 404."""')
            lines.append(
                f"        mock_service.{op['function_name']}.side_effect = {op['not_found_exception_expr']}"
            )
            _nf_body = op.get("not_found_body_repr")
            _body_arg = f", json={_nf_body}" if _nf_body else ""
            lines.append(
                f'        response = client_with_mock.{op["method"]}("{op["filled_path"]}"{_body_arg}{_params_arg})'
            )
            lines.append("        assert response.status_code == 404")

        response_type_str: str = op.get("response_type_str", "")  # type: ignore[assignment]
        success_status_code: int = op.get("success_status_code", 200)  # type: ignore[assignment]
        response_factory: str | None = op.get("response_factory")  # type: ignore[assignment]
        default_mock_return_repr: str | None = op.get("default_mock_return_repr")  # type: ignore[assignment]
        auto_implement_success: bool = op.get("auto_implement_success", False)  # type: ignore[assignment]
        type_suffix = (
            f" {response_type_str}"
            if response_type_str and response_type_str != "None"
            else ""
        )
        _effective_return = response_factory or default_mock_return_repr

        if auto_implement_success and has_services and _effective_return:
            success_sig = "client_with_mock: TestClient, mock_service: AsyncMock"
        elif has_services:
            success_sig = "client_with_mock: TestClient"
        else:
            success_sig = "client: TestClient"

        lines.append("")
        lines.append(f"    def test_success(self, {success_sig}) -> None:")
        lines.append(
            f'        """Happy path — {op["method"].upper()} {op["path"]} → {success_status_code}{type_suffix}."""'
        )
        if auto_implement_success and has_services:
            if _effective_return:
                lines.append(
                    f"        mock_service.{op['function_name']}.return_value = {_effective_return}"
                )
            lines.append(
                f'        response = client_with_mock.{op["method"]}("{op["filled_path"]}"{_params_arg})'
            )
            lines.append(
                f"        assert response.status_code == {success_status_code}"
            )
        else:
            if has_services:
                if response_factory:
                    lines.append(
                        f"        # mock_service.{op['function_name']}.return_value = {response_factory}"
                    )
                    if op["method"] in ("post", "put", "patch"):
                        lines.append(
                            "        # Adjust return_value to match your service logic"
                        )
                lines.append(
                    f'        # response = client_with_mock.{op["method"]}("{op["filled_path"]}")'
                )
                if response_type_str == "None":
                    lines.append(
                        f"        # No response body — assert response.status_code == {success_status_code}"
                    )
                else:
                    lines.append(
                        f"        # assert response.status_code == {success_status_code}"
                    )
            lines.append('        pytest.skip("implement me")')
        lines.append("")
        lines.append("")
    return "\n".join(lines)
