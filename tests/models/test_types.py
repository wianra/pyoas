import pytest

from pyoas.models.types import required_imports, schema_to_python_type


@pytest.mark.parametrize(
    "schema, expected",
    [
        ({"type": "string"}, "str"),
        ({"type": "integer"}, "int"),
        ({"type": "number"}, "float"),
        ({"type": "boolean"}, "bool"),
        ({"type": "string", "format": "date"}, "datetime.date"),
        ({"type": "string", "format": "date-time"}, "datetime.datetime"),
        ({"type": "string", "format": "uuid"}, "uuid.UUID"),
        ({"type": "string", "format": "binary"}, "bytes"),
        ({"type": "array", "items": {"type": "string"}}, "list[str]"),
        ({"type": "object"}, "dict[str, Any]"),
        # 3.0 nullable
        ({"type": "string", "nullable": True}, "str | None"),
        # 3.1 nullable via type array
        ({"type": ["string", "null"]}, "str | None"),
        # Literal enum
        ({"type": "string", "enum": ["a", "b", "c"]}, 'Literal["a", "b", "c"]'),
        ({"type": "integer", "enum": [1, 2, 3]}, "Literal[1, 2, 3]"),
    ],
)
def test_scalar_types(schema: dict, expected: str) -> None:
    result = schema_to_python_type(schema)
    assert result == expected


def test_anyof_union() -> None:
    schema = {
        "anyOf": [
            {"type": "string"},
            {"type": "integer"},
        ]
    }
    result = schema_to_python_type(schema)
    assert result == "str | int"


def test_anyof_null_entry_is_nullable() -> None:
    schema = {
        "anyOf": [
            {"type": "string"},
            {"type": "null"},
        ]
    }
    result = schema_to_python_type(schema)
    assert result == "str | None"


def test_nested_array() -> None:
    schema = {
        "type": "array",
        "items": {
            "type": "array",
            "items": {"type": "integer"},
        },
    }
    assert schema_to_python_type(schema) == "list[list[int]]"


def test_allof_single_unwraps() -> None:
    schema = {"allOf": [{"type": "string"}]}
    assert schema_to_python_type(schema) == "str"


def test_allof_multi_produces_union() -> None:
    """allOf with multiple entries must produce valid Python (union), not `&`."""
    schema = {"allOf": [{"type": "string"}, {"type": "integer"}]}
    assert schema_to_python_type(schema) == "str | int"


def test_allof_refs_produce_union() -> None:
    """allOf with $ref entries resolves names and joins with |."""
    # The resolved schema for each part would be the actual schema content,
    # but raw_schema carries the $ref so names are recovered from there.
    resolved_part_a = {"type": "object", "properties": {"id": {"type": "integer"}}}
    resolved_part_b = {"type": "object", "properties": {"name": {"type": "string"}}}
    schema = {"allOf": [resolved_part_a, resolved_part_b]}
    raw_schema = {
        "allOf": [
            {"$ref": "#/components/schemas/A"},
            {"$ref": "#/components/schemas/B"},
        ]
    }
    result = schema_to_python_type(schema, raw_schema=raw_schema)
    assert result == "A | B"


def test_allof_single_ref_unwraps() -> None:
    """allOf with a single $ref unwraps to just that name (no union)."""
    resolved = {"type": "object", "properties": {"id": {"type": "integer"}}}
    schema = {"allOf": [resolved]}
    raw_schema = {"allOf": [{"$ref": "#/components/schemas/Animal"}]}
    result = schema_to_python_type(schema, raw_schema=raw_schema)
    assert result == "Animal"


def test_allof_single_ref_with_inline_returns_ref_name() -> None:
    """allOf with one $ref plus inline additive properties → just the $ref name."""
    resolved_animal = {"type": "object", "properties": {"id": {"type": "integer"}}}
    resolved_inline = {"type": "object", "properties": {"breed": {"type": "string"}}}
    schema = {"allOf": [resolved_animal, resolved_inline]}
    raw_schema = {
        "allOf": [
            {"$ref": "#/components/schemas/Animal"},
            {"type": "object", "properties": {"breed": {"type": "string"}}},
        ]
    }
    result = schema_to_python_type(schema, raw_schema=raw_schema)
    assert result == "Animal"


def test_allof_inline_objects_only_returns_dict() -> None:
    """allOf with zero $refs and all object schemas → dict[str, Any]."""
    resolved_a = {"type": "object", "properties": {"a": {"type": "string"}}}
    resolved_b = {"type": "object", "properties": {"b": {"type": "integer"}}}
    schema = {"allOf": [resolved_a, resolved_b]}
    raw_schema = {
        "allOf": [
            {"type": "object", "properties": {"a": {"type": "string"}}},
            {"type": "object", "properties": {"b": {"type": "integer"}}},
        ]
    }
    result = schema_to_python_type(schema, raw_schema=raw_schema)
    assert result == "dict[str, Any]"


def test_discriminator_mapping_emits_tag_discriminator() -> None:
    """discriminator with mapping → Annotated[... Tag ..., Discriminator(...)]."""
    schema = {
        "oneOf": [
            {
                "type": "object",
                "properties": {"type": {"type": "string", "enum": ["click"]}},
            },
            {
                "type": "object",
                "properties": {"type": {"type": "string", "enum": ["keyboard"]}},
            },
        ],
        "discriminator": {
            "propertyName": "type",
            "mapping": {
                "click": "#/components/schemas/ClickEvent",
                "keyboard": "#/components/schemas/KeyboardEvent",
            },
        },
    }
    raw_schema = {
        "oneOf": [
            {"$ref": "#/components/schemas/ClickEvent"},
            {"$ref": "#/components/schemas/KeyboardEvent"},
        ],
        "discriminator": {
            "propertyName": "type",
            "mapping": {
                "click": "#/components/schemas/ClickEvent",
                "keyboard": "#/components/schemas/KeyboardEvent",
            },
        },
    }
    result = schema_to_python_type(schema, raw_schema=raw_schema)
    assert 'Tag("click")' in result
    assert 'Tag("keyboard")' in result
    assert 'Discriminator("type")' in result
    assert "ClickEvent" in result
    assert "KeyboardEvent" in result


def test_discriminator_no_mapping_keeps_field_discriminator() -> None:
    """discriminator without mapping → Annotated[A | B, Field(discriminator=...)]."""
    schema = {
        "oneOf": [{"type": "object"}, {"type": "object"}],
        "discriminator": {"propertyName": "kind"},
    }
    raw_schema = {
        "oneOf": [
            {"$ref": "#/components/schemas/CatSchema"},
            {"$ref": "#/components/schemas/DogSchema"},
        ],
        "discriminator": {"propertyName": "kind"},
    }
    result = schema_to_python_type(schema, raw_schema=raw_schema)
    assert result == 'Annotated[CatSchema | DogSchema, Field(discriminator="kind")]'


def test_required_imports_datetime() -> None:
    imports = required_imports("datetime.datetime")
    assert "import datetime" in imports


def test_required_imports_uuid() -> None:
    imports = required_imports("uuid.UUID")
    assert "import uuid" in imports


def test_required_imports_plain_str() -> None:
    imports = required_imports("str")
    assert imports == []


def test_unique_items_produces_set() -> None:
    schema = {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
    assert schema_to_python_type(schema) == "set[str]"


def test_unique_items_as_set_false_produces_list() -> None:
    schema = {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
    assert schema_to_python_type(schema, unique_items_as_set=False) == "list[str]"


def test_array_without_unique_items_produces_list() -> None:
    schema = {"type": "array", "items": {"type": "string"}}
    assert schema_to_python_type(schema) == "list[str]"


def test_prefix_items_produces_tuple() -> None:
    schema = {
        "type": "array",
        "prefixItems": [{"type": "string"}, {"type": "integer"}, {"type": "boolean"}],
    }
    assert schema_to_python_type(schema) == "tuple[str, int, bool]"


def test_prefix_items_single_element() -> None:
    schema = {"prefixItems": [{"type": "number"}]}
    assert schema_to_python_type(schema) == "tuple[float]"


def test_prefix_items_with_tail_items_produces_variadic_tuple() -> None:
    schema = {
        "type": "array",
        "prefixItems": [{"type": "string"}, {"type": "integer"}],
        "items": {"type": "boolean"},
    }
    assert schema_to_python_type(schema) == "tuple[str, int, *tuple[bool, ...]]"


def test_prefix_items_single_with_tail_items() -> None:
    schema = {
        "prefixItems": [{"type": "number"}],
        "items": {"type": "string"},
    }
    assert schema_to_python_type(schema) == "tuple[float, *tuple[str, ...]]"


def test_not_keyword_returns_any_with_warning() -> None:
    import warnings

    schema = {"not": {"type": "string"}}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = schema_to_python_type(schema)
    assert result == "Any"
    assert any("not" in str(w.message).lower() for w in caught)
    assert any(issubclass(w.category, UserWarning) for w in caught)


# ---------------------------------------------------------------------------
# OAS 3.1 const keyword (F-03 / T-10)
# ---------------------------------------------------------------------------


def test_const_string() -> None:
    assert schema_to_python_type({"const": "active"}) == 'Literal["active"]'


def test_const_integer() -> None:
    assert schema_to_python_type({"const": 42}) == "Literal[42]"


def test_const_boolean() -> None:
    assert schema_to_python_type({"const": True}) == "Literal[True]"


def test_const_null() -> None:
    assert schema_to_python_type({"const": None}) == "Literal[None]"


def test_const_with_type_annotation() -> None:
    # const takes precedence over the type field
    assert (
        schema_to_python_type({"const": "pending", "type": "string"})
        == 'Literal["pending"]'
    )


# ---------------------------------------------------------------------------
# F-09 · $ref + sibling nullable keywords (OAS 3.1)
# ---------------------------------------------------------------------------


def test_ref_with_nullable_true_returns_optional() -> None:
    raw = {"$ref": "#/components/schemas/Pet", "nullable": True}
    resolved = {"type": "object", "properties": {"name": {"type": "string"}}}
    assert schema_to_python_type(resolved, raw_schema=raw) == "Pet | None"


def test_ref_without_nullable_returns_plain_name() -> None:
    raw = {"$ref": "#/components/schemas/Pet"}
    resolved = {"type": "object", "properties": {"name": {"type": "string"}}}
    assert schema_to_python_type(resolved, raw_schema=raw) == "Pet"


def test_ref_with_type_array_null_returns_optional() -> None:
    # OAS 3.1 nullable via type array alongside $ref
    raw = {"$ref": "#/components/schemas/Tag", "type": ["object", "null"]}
    resolved = {"type": "object"}
    assert schema_to_python_type(resolved, raw_schema=raw) == "Tag | None"


# ---------------------------------------------------------------------------
# F-10 · contentEncoding: base64 → bytes (OAS 3.1)
# ---------------------------------------------------------------------------


def test_content_encoding_base64_returns_bytes() -> None:
    assert (
        schema_to_python_type({"type": "string", "contentEncoding": "base64"})
        == "bytes"
    )


def test_content_encoding_other_value_falls_through() -> None:
    assert (
        schema_to_python_type({"type": "string", "contentEncoding": "quoted-printable"})
        == "str"
    )


def test_content_encoding_without_type_returns_bytes() -> None:
    assert schema_to_python_type({"contentEncoding": "base64"}) == "bytes"


# ---------------------------------------------------------------------------
# F-05 · if/then/else best-effort (OAS 3.1)
# ---------------------------------------------------------------------------


def test_if_then_uses_then_branch() -> None:
    import warnings

    schema = {
        "if": {"properties": {"kind": {"const": "dog"}}},
        "then": {"type": "string"},
        "else": {"type": "integer"},
    }
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = schema_to_python_type(schema)
    assert result == "str"
    assert any("if" in str(warning.message).lower() for warning in w)


def test_if_without_then_returns_any() -> None:
    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = schema_to_python_type({"if": {"type": "string"}})
    assert result == "Any"
    assert any("if" in str(warning.message).lower() for warning in w)


def test_if_then_ref_resolves_correctly() -> None:
    import warnings

    schema = {
        "if": {"properties": {"x": {"type": "integer"}}},
        "then": {"type": "integer"},
    }
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        assert schema_to_python_type(schema) == "int"


# ---------------------------------------------------------------------------
# F-04 · patternProperties → dict[str, T] (OAS 3.1)
# ---------------------------------------------------------------------------


def test_pattern_properties_single_type_returns_typed_dict() -> None:
    schema = {
        "type": "object",
        "patternProperties": {"^S_": {"type": "string"}},
    }
    assert schema_to_python_type(schema) == "dict[str, str]"


def test_pattern_properties_multiple_types_returns_any_dict() -> None:
    schema = {
        "type": "object",
        "patternProperties": {
            "^S_": {"type": "string"},
            "^I_": {"type": "integer"},
        },
    }
    assert schema_to_python_type(schema) == "dict[str, Any]"


def test_pattern_properties_without_explicit_type() -> None:
    # patternProperties implies object semantics even without type: object
    schema = {"patternProperties": {"^.*$": {"type": "number"}}}
    assert schema_to_python_type(schema) == "dict[str, float]"


def test_pattern_properties_ignored_when_properties_present() -> None:
    # If properties is set, it wins (model generator owns the class shape)
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "patternProperties": {"^.*$": {"type": "integer"}},
    }
    result = schema_to_python_type(schema, context_name="MyModel")
    assert result == "MyModel"
