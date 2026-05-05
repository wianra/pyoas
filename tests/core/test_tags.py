import warnings

from pyoas.core.parser import SpecParser
from pyoas.core.resolver import resolve_refs
from pyoas.core.tags import extract_tags, get_declared_tags


def test_extract_petstore_tags(petstore_30) -> None:
    spec = resolve_refs(SpecParser(str(petstore_30)).load(), str(petstore_30))
    grouped = extract_tags(spec)
    assert set(grouped.keys()) == {"pets", "store"}
    assert len(grouped["pets"]) == 3  # listPets, createPet, getPet
    assert len(grouped["store"]) == 1  # getInventory


def test_operations_have_required_keys(petstore_30) -> None:
    spec = resolve_refs(SpecParser(str(petstore_30)).load(), str(petstore_30))
    for tag, operations in extract_tags(spec).items():
        for op in operations:
            assert "method" in op
            assert "path" in op
            assert "operation" in op
            assert op["method"] in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "head",
                "options",
                "trace",
            }


def test_no_tags_fallback(no_tags) -> None:
    spec = resolve_refs(SpecParser(str(no_tags)).load(), str(no_tags))
    grouped = extract_tags(spec, default_tag="default")
    assert "default" in grouped
    assert len(grouped) == 1
    assert len(grouped["default"]) == 4  # listItems, createItem, getItem, deleteItem


def test_custom_fallback_tag(no_tags) -> None:
    spec = resolve_refs(SpecParser(str(no_tags)).load(), str(no_tags))
    grouped = extract_tags(spec, default_tag="untagged")
    assert "untagged" in grouped
    assert "default" not in grouped


def test_multi_tag(multi_tag) -> None:
    spec = resolve_refs(SpecParser(str(multi_tag)).load(), str(multi_tag))
    grouped = extract_tags(spec)
    assert "users" in grouped
    assert "orders" in grouped


def test_get_declared_tags(petstore_30) -> None:
    spec = SpecParser(str(petstore_30)).load()
    tags = get_declared_tags(spec)
    assert tags == ["pets", "store"]


def test_default_tag_collision_warning() -> None:
    spec = {
        "tags": [{"name": "pets"}, {"name": "default"}],
        "paths": {
            "/pets": {
                "get": {"operationId": "listPets", "tags": ["pets"], "responses": {}}
            },
            "/other": {
                "get": {"operationId": "other", "responses": {}}  # no tag → default
            },
        },
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        extract_tags(spec, default_tag="default")
    assert any("default" in str(w.message) for w in caught)
    assert any(issubclass(w.category, UserWarning) for w in caught)


def test_no_collision_warning_when_no_overlap() -> None:
    spec = {
        "tags": [{"name": "pets"}],
        "paths": {},
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        extract_tags(spec, default_tag="default")
    assert not any(issubclass(w.category, UserWarning) for w in caught)


# ---------------------------------------------------------------------------
# Edge-case path-item / operation handling
# ---------------------------------------------------------------------------


def test_non_dict_path_item_is_skipped() -> None:
    spec = {"paths": {"/pets": "not a dict"}}
    assert extract_tags(spec) == {}


def test_non_http_method_key_in_path_item_is_skipped() -> None:
    """Keys like 'x-extension' are not HTTP methods and must be skipped."""
    spec = {
        "paths": {
            "/pets": {
                "x-extension": {"some": "data"},
                "get": {"tags": ["pets"], "responses": {}},
            }
        }
    }
    grouped = extract_tags(spec)
    assert "pets" in grouped
    assert len(grouped["pets"]) == 1


def test_non_dict_operation_is_skipped() -> None:
    spec = {
        "paths": {
            "/pets": {
                "get": "not a dict",
                "post": {"tags": ["pets"], "responses": {}},
            }
        }
    }
    grouped = extract_tags(spec)
    assert len(grouped["pets"]) == 1  # only the post


# ---------------------------------------------------------------------------
# Path-level parameter inheritance
# ---------------------------------------------------------------------------


def test_path_level_params_are_inherited_by_operations() -> None:
    spec = {
        "paths": {
            "/pets/{id}": {
                "parameters": [{"name": "id", "in": "path", "required": True}],
                "get": {"tags": ["pets"], "responses": {}},
            }
        }
    }
    grouped = extract_tags(spec)
    op = grouped["pets"][0]
    assert op["method"] == "get"
    params = op["operation"].get("parameters", [])
    assert any(p.get("name") == "id" and p.get("in") == "path" for p in params)


def test_op_level_params_take_precedence_over_path_level() -> None:
    """When op and path both declare the same (name, in), op wins and no duplicate is added."""
    spec = {
        "paths": {
            "/pets/{id}": {
                "parameters": [
                    {"name": "id", "in": "path", "schema": {"type": "integer"}}
                ],
                "get": {
                    "tags": ["pets"],
                    "parameters": [
                        {"name": "id", "in": "path", "schema": {"type": "string"}}
                    ],
                    "responses": {},
                },
            }
        }
    }
    grouped = extract_tags(spec)
    op_params = grouped["pets"][0]["operation"].get("parameters", [])
    id_params = [p for p in op_params if p.get("name") == "id"]
    assert len(id_params) == 1  # no duplicate
    assert id_params[0]["schema"] == {"type": "string"}  # op-level wins
