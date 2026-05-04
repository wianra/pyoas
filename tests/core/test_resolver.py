from pyoas.core.parser import SpecParser
from pyoas.core.resolver import resolve_refs


def test_circular_ref_does_not_recurse_infinitely() -> None:
    """resolve_refs must not crash on self-referential schemas."""
    spec: dict = {
        "openapi": "3.0.3",
        "info": {"title": "t", "version": "0"},
        "paths": {},
        "components": {
            "schemas": {
                "TreeNode": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "children": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/TreeNode"},
                        },
                    },
                }
            }
        },
    }
    result = resolve_refs(spec)
    tree = result["components"]["schemas"]["TreeNode"]
    assert tree["type"] == "object"
    # The circular items ref must be preserved as a plain $ref dict, not recursed.
    items = tree["properties"]["children"]["items"]
    assert items == {"$ref": "#/components/schemas/TreeNode"}


def test_resolve_refs_petstore(petstore_30) -> None:
    spec_raw = SpecParser(str(petstore_30)).load()
    spec = resolve_refs(spec_raw, str(petstore_30))
    # After resolution, $ref in Pet response should be a real dict
    get_pet_resp = spec["paths"]["/pets/{petId}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert isinstance(get_pet_resp, dict)
    # The Pet schema properties should be inlined
    assert "properties" in get_pet_resp


def test_deep_copy_removes_proxies(petstore_30) -> None:
    spec_raw = SpecParser(str(petstore_30)).load()
    spec = resolve_refs(spec_raw, str(petstore_30))
    # Result should be a plain dict, not a jsonref proxy
    assert type(spec) is dict  # noqa: E721


def test_resolve_preserves_structure(petstore_31) -> None:
    spec_raw = SpecParser(str(petstore_31)).load()
    spec = resolve_refs(spec_raw, str(petstore_31))
    assert "paths" in spec
    assert "components" in spec
