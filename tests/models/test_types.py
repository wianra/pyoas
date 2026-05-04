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


def test_not_keyword_returns_any_with_warning() -> None:
    import warnings

    schema = {"not": {"type": "string"}}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = schema_to_python_type(schema)
    assert result == "Any"
    assert any("not" in str(w.message).lower() for w in caught)
    assert any(issubclass(w.category, UserWarning) for w in caught)
