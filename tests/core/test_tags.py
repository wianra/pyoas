import warnings

import pytest

from pyoas.core.parser import SpecParser
from pyoas.core.resolver import resolve_refs
from pyoas.core.tags import extract_tags, get_declared_tags


def test_extract_petstore_tags(petstore_30) -> None:
    spec = resolve_refs(SpecParser(str(petstore_30)).load(), str(petstore_30))
    grouped = extract_tags(spec)
    assert set(grouped.keys()) == {"Pets", "Store"}
    assert len(grouped["Pets"]) == 3  # listPets, createPet, getPet
    assert len(grouped["Store"]) == 1  # getInventory


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
    assert tags == ["Pets", "Store"]


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


# ---------------------------------------------------------------------------
# Webhook support (OAS 3.1)
# ---------------------------------------------------------------------------

_WEBHOOK_SPEC: dict = {
    "paths": {
        "/subscriptions": {
            "post": {
                "operationId": "createSubscription",
                "tags": ["subscriptions"],
                "responses": {},
            }
        }
    },
    "webhooks": {
        "onSubscriptionEvent": {
            "post": {
                "operationId": "onSubscriptionEvent",
                "tags": ["subscriptions"],
                "responses": {},
            }
        }
    },
}


def test_webhooks_excluded_by_default() -> None:
    """Webhook operations are NOT included when include_webhooks=False (default)."""
    grouped = extract_tags(_WEBHOOK_SPEC)
    assert "subscriptions" in grouped
    # Only the path operation; webhook excluded
    assert len(grouped["subscriptions"]) == 1
    assert grouped["subscriptions"][0]["path"] == "/subscriptions"


def test_webhooks_included_when_flag_set() -> None:
    """Webhook operations ARE included when include_webhooks=True."""
    grouped = extract_tags(_WEBHOOK_SPEC, include_webhooks=True)
    assert "subscriptions" in grouped
    assert len(grouped["subscriptions"]) == 2
    webhook_ops = [op for op in grouped["subscriptions"] if op.get("is_webhook")]
    assert len(webhook_ops) == 1
    assert webhook_ops[0]["path"] == "onSubscriptionEvent"


def test_webhook_operations_have_is_webhook_flag() -> None:
    """All webhook operations carry is_webhook=True; path ops carry is_webhook=False."""
    grouped = extract_tags(_WEBHOOK_SPEC, include_webhooks=True)
    for op in grouped["subscriptions"]:
        assert "is_webhook" in op
        if op["path"] == "/subscriptions":
            assert op["is_webhook"] is False
        else:
            assert op["is_webhook"] is True


def test_webhook_operations_have_required_keys() -> None:
    """Webhook operation entries have method, path, operation, is_webhook."""
    grouped = extract_tags(_WEBHOOK_SPEC, include_webhooks=True)
    for op in grouped["subscriptions"]:
        assert "method" in op
        assert "path" in op
        assert "operation" in op
        assert "is_webhook" in op


def test_webhooks_use_default_tag_when_untagged() -> None:
    """Webhook operations with no tags fall back to default_tag."""
    spec: dict = {
        "webhooks": {"onEvent": {"post": {"operationId": "onEvent", "responses": {}}}}
    }
    grouped = extract_tags(spec, default_tag="default", include_webhooks=True)
    assert "default" in grouped
    assert grouped["default"][0]["is_webhook"] is True


def test_no_webhooks_key_does_not_error() -> None:
    """Specs with no webhooks key are unaffected when include_webhooks=True."""
    spec: dict = {"paths": {"/items": {"get": {"tags": ["items"], "responses": {}}}}}
    grouped = extract_tags(spec, include_webhooks=True)
    assert "items" in grouped
    assert all(not op.get("is_webhook") for op in grouped["items"])


def test_non_dict_webhook_item_is_skipped() -> None:
    """Non-dict entries under webhooks are skipped gracefully."""
    spec: dict = {"webhooks": {"badEntry": "not a dict"}}
    grouped = extract_tags(spec, include_webhooks=True)
    assert grouped == {}


# ---------------------------------------------------------------------------
# skip_extensions filtering
# ---------------------------------------------------------------------------

_DRAFT_SPEC: dict = {
    "paths": {
        "/published": {
            "get": {"tags": ["items"], "responses": {}, "operationId": "getPublished"},
        },
        "/draft": {
            "get": {
                "tags": ["items"],
                "responses": {},
                "operationId": "getDraft",
                "x-draft": True,
            },
        },
    }
}


def test_skip_extension_truthy_operation_excluded() -> None:
    grouped = extract_tags(_DRAFT_SPEC, skip_extensions=["x-draft"])
    ops = grouped["items"]
    assert len(ops) == 1
    assert ops[0]["operation"]["operationId"] == "getPublished"


def test_skip_extension_falsy_operation_kept() -> None:
    spec: dict = {
        "paths": {
            "/item": {
                "get": {"tags": ["items"], "responses": {}, "x-draft": False},
            }
        }
    }
    grouped = extract_tags(spec, skip_extensions=["x-draft"])
    assert len(grouped["items"]) == 1


def test_skip_extension_absent_operation_kept() -> None:
    spec: dict = {
        "paths": {
            "/item": {
                "get": {"tags": ["items"], "responses": {}},
            }
        }
    }
    grouped = extract_tags(spec, skip_extensions=["x-draft"])
    assert len(grouped["items"]) == 1


def test_skip_multiple_extensions_any_truthy_excluded() -> None:
    spec: dict = {
        "paths": {
            "/a": {
                "get": {
                    "tags": ["t"],
                    "responses": {},
                    "operationId": "a",
                    "x-draft": True,
                }
            },
            "/b": {
                "get": {
                    "tags": ["t"],
                    "responses": {},
                    "operationId": "b",
                    "x-internal": True,
                }
            },
            "/c": {"get": {"tags": ["t"], "responses": {}, "operationId": "c"}},
        }
    }
    grouped = extract_tags(spec, skip_extensions=["x-draft", "x-internal"])
    assert len(grouped["t"]) == 1
    assert grouped["t"][0]["operation"]["operationId"] == "c"


def test_empty_skip_extensions_no_filtering() -> None:
    grouped = extract_tags(_DRAFT_SPEC, skip_extensions=[])
    assert len(grouped["items"]) == 2


_LIFECYCLE_SPEC: dict = {
    "paths": {
        "/a": {
            "get": {
                "tags": ["t"],
                "operationId": "a",
                "responses": {},
                "x-lifecycle": "draft",
            }
        },
        "/b": {
            "get": {
                "tags": ["t"],
                "operationId": "b",
                "responses": {},
                "x-lifecycle": "alpha",
            }
        },
        "/c": {
            "get": {
                "tags": ["t"],
                "operationId": "c",
                "responses": {},
                "x-lifecycle": "stable",
            }
        },
    }
}


def test_skip_extension_equals_single_value() -> None:
    grouped = extract_tags(
        _LIFECYCLE_SPEC, skip_extensions={"x-lifecycle": frozenset({"draft"})}
    )
    op_ids = sorted(op["operation"]["operationId"] for op in grouped["t"])
    assert op_ids == ["b", "c"]


def test_skip_extension_value_in_set() -> None:
    grouped = extract_tags(
        _LIFECYCLE_SPEC,
        skip_extensions={"x-lifecycle": frozenset({"draft", "alpha"})},
    )
    op_ids = [op["operation"]["operationId"] for op in grouped["t"]]
    assert op_ids == ["c"]


def test_skip_extension_value_match_does_not_skip_other_values() -> None:
    grouped = extract_tags(
        _LIFECYCLE_SPEC,
        skip_extensions={"x-lifecycle": frozenset({"retired"})},
    )
    assert len(grouped["t"]) == 3


def test_skip_extension_mapping_with_None_is_presence_check() -> None:
    grouped = extract_tags(_DRAFT_SPEC, skip_extensions={"x-draft": None})
    ops = grouped["items"]
    assert len(ops) == 1
    assert ops[0]["operation"]["operationId"] == "getPublished"


def test_skip_extension_or_semantics_across_keys() -> None:
    spec: dict = {
        "paths": {
            "/a": {
                "get": {
                    "tags": ["t"],
                    "operationId": "a",
                    "responses": {},
                    "x-draft": True,
                }
            },
            "/b": {
                "get": {
                    "tags": ["t"],
                    "operationId": "b",
                    "responses": {},
                    "x-lifecycle": "draft",
                }
            },
            "/c": {
                "get": {
                    "tags": ["t"],
                    "operationId": "c",
                    "responses": {},
                    "x-lifecycle": "stable",
                }
            },
        }
    }
    grouped = extract_tags(
        spec,
        skip_extensions={
            "x-draft": None,
            "x-lifecycle": frozenset({"draft"}),
        },
    )
    op_ids = [op["operation"]["operationId"] for op in grouped["t"]]
    assert op_ids == ["c"]


def test_skip_extension_unhashable_value_does_not_match_equality() -> None:
    """If an op's extension value is a list, it cannot equal any scalar."""
    spec: dict = {
        "paths": {
            "/a": {
                "get": {
                    "tags": ["t"],
                    "operationId": "a",
                    "responses": {},
                    "x-status": ["draft"],
                }
            },
        }
    }
    grouped = extract_tags(spec, skip_extensions={"x-status": frozenset({"draft"})})
    assert len(grouped["t"]) == 1


# ---------------------------------------------------------------------------
# normalize_skip_extensions
# ---------------------------------------------------------------------------


def test_normalize_skip_extensions_none_returns_empty() -> None:
    from pyoas.core.tags import normalize_skip_extensions

    assert normalize_skip_extensions(None) == {}


def test_normalize_skip_extensions_list_form() -> None:
    from pyoas.core.tags import normalize_skip_extensions

    assert normalize_skip_extensions(["x-a", "x-b"]) == {"x-a": None, "x-b": None}


def test_normalize_skip_extensions_dict_truthy() -> None:
    from pyoas.core.tags import normalize_skip_extensions

    assert normalize_skip_extensions({"x-a": True}) == {"x-a": None}


def test_normalize_skip_extensions_dict_scalar() -> None:
    from pyoas.core.tags import normalize_skip_extensions

    assert normalize_skip_extensions({"x-a": "draft"}) == {"x-a": frozenset({"draft"})}


def test_normalize_skip_extensions_dict_list() -> None:
    from pyoas.core.tags import normalize_skip_extensions

    assert normalize_skip_extensions({"x-a": ["draft", "alpha"]}) == {
        "x-a": frozenset({"draft", "alpha"})
    }


def test_normalize_skip_extensions_dict_false_raises() -> None:
    from pyoas.core.tags import normalize_skip_extensions

    with pytest.raises(ValueError, match="ambiguous"):
        normalize_skip_extensions({"x-a": False})


def test_normalize_skip_extensions_dict_nested_raises() -> None:
    from pyoas.core.tags import normalize_skip_extensions

    with pytest.raises(ValueError, match="must be `true`"):
        normalize_skip_extensions({"x-a": {"nested": "thing"}})


def test_normalize_skip_extensions_non_string_key_raises() -> None:
    from pyoas.core.tags import normalize_skip_extensions

    with pytest.raises(ValueError, match="keys must be strings"):
        normalize_skip_extensions({123: True})


def test_normalize_skip_extensions_non_string_list_entry_raises() -> None:
    from pyoas.core.tags import normalize_skip_extensions

    with pytest.raises(ValueError, match="list entries must be strings"):
        normalize_skip_extensions([123])


def test_normalize_skip_extensions_top_level_string_raises() -> None:
    from pyoas.core.tags import normalize_skip_extensions

    with pytest.raises(ValueError, match="must be a list or mapping"):
        normalize_skip_extensions("x-draft")
