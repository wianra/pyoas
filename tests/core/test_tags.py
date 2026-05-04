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
