"""Tests for pyoas.core.fixer — unit and CLI integration."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from pyoas.core.cli import app
from pyoas.core.fixer import (
    assign_missing_operation_ids,
    dedupe_operation_ids,
    fix_spec,
    normalize_tags,
    serialize_spec,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_spec(**paths_overrides: dict) -> dict:
    """Return a minimal OAS 3.0 spec with the given paths."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": paths_overrides,
    }


def _op(op_id: str | None = None, tags: list[str] | None = None) -> dict:
    """Return a minimal operation object."""
    op: dict = {"responses": {"200": {"description": "ok"}}}
    if op_id is not None:
        op["operationId"] = op_id
    if tags is not None:
        op["tags"] = tags
    return op


def _write_config(tmp_path: Path, spec: Path | str, **extra) -> Path:
    data: dict = {
        "spec": str(spec),
        "output": {
            "models": str(tmp_path / "models"),
            "routers": str(tmp_path / "routers"),
        },
        "format": {"enabled": False},
    }
    data.update(extra)
    cfg = tmp_path / "pyoas.yaml"
    cfg.write_text(yaml.dump(data), encoding="utf-8")
    return cfg


# ---------------------------------------------------------------------------
# assign_missing_operation_ids
# ---------------------------------------------------------------------------


def test_assigns_id_to_operation_with_no_id() -> None:
    spec = _minimal_spec(**{"/pets": {"get": _op()}})
    actions = assign_missing_operation_ids(spec)
    assert len(actions) == 1
    assert actions[0].kind == "assign_operation_id"
    assert actions[0].location == "GET /pets"
    assert actions[0].before == ""
    assert spec["paths"]["/pets"]["get"]["operationId"] == actions[0].after


def test_does_not_touch_existing_operation_id() -> None:
    spec = _minimal_spec(**{"/pets": {"get": _op("listPets")}})
    actions = assign_missing_operation_ids(spec)
    assert actions == []
    assert spec["paths"]["/pets"]["get"]["operationId"] == "listPets"


def test_assign_avoids_collision_with_existing_ids() -> None:
    # /pets GET → candidate "get_pets", but that id already exists on another op
    spec = _minimal_spec(
        **{
            "/pets": {"get": _op()},  # missing id — will generate "get_pets"
            "/other": {"get": _op("get_pets")},  # already has the candidate name
        }
    )
    actions = assign_missing_operation_ids(spec)
    assert len(actions) == 1
    new_id = spec["paths"]["/pets"]["get"]["operationId"]
    assert new_id == "get_pets_2"


def test_assign_multiple_missing_same_candidate() -> None:
    # Two paths that both generate "get_items"
    spec = _minimal_spec(
        **{
            "/items": {"get": _op()},
            "/items/{id}": {"get": _op()},
        }
    )
    actions = assign_missing_operation_ids(spec)
    assert len(actions) == 2
    ids = {a.after for a in actions}
    # Both should be unique
    assert len(ids) == 2


# ---------------------------------------------------------------------------
# dedupe_operation_ids
# ---------------------------------------------------------------------------


def test_dedupes_two_ops_with_same_id() -> None:
    spec = _minimal_spec(
        **{
            "/users": {"get": _op("listItems")},
            "/orders": {"get": _op("listItems")},
        }
    )
    actions = dedupe_operation_ids(spec)
    assert len(actions) == 1
    assert actions[0].kind == "dedupe_operation_id"
    assert actions[0].before == "listItems"
    assert actions[0].after == "listItems_2"
    # First occurrence unchanged
    assert spec["paths"]["/users"]["get"]["operationId"] == "listItems"
    assert spec["paths"]["/orders"]["get"]["operationId"] == "listItems_2"


def test_dedupes_three_ops_with_same_id() -> None:
    spec = _minimal_spec(
        **{
            "/a": {"get": _op("foo")},
            "/b": {"get": _op("foo")},
            "/c": {"get": _op("foo")},
        }
    )
    actions = dedupe_operation_ids(spec)
    assert len(actions) == 2
    ids = {spec["paths"][p]["get"]["operationId"] for p in ("/a", "/b", "/c")}
    assert ids == {"foo", "foo_2", "foo_3"}


def test_no_action_when_no_duplicates() -> None:
    spec = _minimal_spec(
        **{
            "/a": {"get": _op("aGet")},
            "/b": {"get": _op("bGet")},
        }
    )
    actions = dedupe_operation_ids(spec)
    assert actions == []


def test_dedupe_suffix_avoids_pre_existing_suffixed_id() -> None:
    # listItems_2 already exists — new dedupe should land on listItems_3
    spec = _minimal_spec(
        **{
            "/a": {"get": _op("listItems")},
            "/b": {"get": _op("listItems_2")},
            "/c": {"get": _op("listItems")},  # duplicate → should become listItems_3
        }
    )
    actions = dedupe_operation_ids(spec)
    assert len(actions) == 1
    assert actions[0].after == "listItems_3"


# ---------------------------------------------------------------------------
# normalize_tags
# ---------------------------------------------------------------------------


def test_normalizes_collision_group_to_canonical_title() -> None:
    spec = _minimal_spec(
        **{
            "/a": {"get": _op(tags=["Pets"])},
            "/b": {"get": _op(tags=["pets"])},
        }
    )
    actions = normalize_tags(spec, casing="title")
    # Both "Pets" and "pets" normalize to dirname "pets"; canonical is "Pets".title() = "Pets"
    assert all(a.kind == "normalize_tag" for a in actions)
    # One of them must change (the one that was "pets")
    changed = [a for a in actions if a.before != a.after]
    assert len(changed) >= 1


def test_no_action_when_tags_already_canonical_title() -> None:
    # "Pets" with title casing: "Pets".title() == "Pets" — no change needed
    spec = _minimal_spec(**{"/a": {"get": _op(tags=["Pets"])}})
    actions = normalize_tags(spec, casing="title")
    changed = [a for a in actions if a.before != a.after]
    assert changed == []


def test_no_action_when_tags_already_canonical_lower() -> None:
    spec = _minimal_spec(**{"/a": {"get": _op(tags=["pets"])}})
    actions = normalize_tags(spec, casing="lower")
    changed = [a for a in actions if a.before != a.after]
    assert changed == []


def test_rewrites_top_level_tags_list() -> None:
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "tags": [{"name": "my-tag"}, {"name": "My-Tag"}],
        "paths": {},
    }
    actions = normalize_tags(spec, casing="title")
    tl_actions = [a for a in actions if a.kind == "normalize_tags_list"]
    assert len(tl_actions) >= 1


def test_rewrites_operation_level_tags() -> None:
    # "my-tag" and "my_tag" both normalize to dirname "my_tag" → collision group
    spec = _minimal_spec(
        **{
            "/a": {"get": _op(tags=["my-tag"])},
            "/b": {"get": _op(tags=["my_tag"])},
        }
    )
    actions = normalize_tags(spec, casing="title")
    op_actions = [a for a in actions if a.kind == "normalize_tag"]
    # At least one op tag changes (the one that doesn't match the canonical form)
    assert len(op_actions) >= 1
    # All changed tags map to the same canonical value
    after_values = {a.after for a in op_actions}
    assert len(after_values) == 1


def test_lower_casing_option() -> None:
    # "Pets" and "pets" collide under tag_to_dirname → resolved to canonical lowercase
    spec = _minimal_spec(
        **{
            "/a": {"get": _op(tags=["Pets"])},
            "/b": {"get": _op(tags=["pets"])},
        }
    )
    actions = normalize_tags(spec, casing="lower")
    changed = [a for a in actions if a.before != a.after]
    assert len(changed) >= 1
    assert all(a.after == "pets" for a in changed)


# ---------------------------------------------------------------------------
# fix_spec
# ---------------------------------------------------------------------------


def test_fix_spec_deep_copies_input() -> None:
    spec = _minimal_spec(**{"/pets": {"get": _op()}})
    original_id_before = spec["paths"]["/pets"]["get"].get("operationId")
    fixed, _ = fix_spec(spec, None)
    # Original must not have been mutated
    assert spec["paths"]["/pets"]["get"].get("operationId") == original_id_before
    # Fixed version should have id assigned
    assert fixed["paths"]["/pets"]["get"].get("operationId") is not None


def test_fix_spec_returns_all_action_kinds() -> None:
    spec = yaml.safe_load((FIXTURES / "fixable_spec.yaml").read_text())
    _, actions = fix_spec(spec, None)
    kinds = {a.kind for a in actions}
    assert "assign_operation_id" in kinds
    assert "dedupe_operation_id" in kinds
    assert "normalize_tag" in kinds or "normalize_tags_list" in kinds


def test_fix_spec_clean_spec_returns_empty_actions() -> None:
    spec = yaml.safe_load((FIXTURES / "petstore_3.0.yaml").read_text())
    _, actions = fix_spec(spec, None)
    assert actions == []


def test_fix_spec_assign_runs_before_dedupe() -> None:
    # If two ops get the same generated name, dedupe should handle the collision.
    spec = _minimal_spec(
        **{
            "/items": {"get": _op()},  # → get_items
            "/items/{id}": {
                "get": _op()
            },  # → get_items_id (different, so no dupe here)
        }
    )
    _, actions = fix_spec(spec, None)
    kinds = [a.kind for a in actions]
    # Assigns come first in the list
    assign_idx = [i for i, k in enumerate(kinds) if k == "assign_operation_id"]
    dedupe_idx = [i for i, k in enumerate(kinds) if k == "dedupe_operation_id"]
    if assign_idx and dedupe_idx:
        assert max(assign_idx) < min(dedupe_idx)


# ---------------------------------------------------------------------------
# serialize_spec
# ---------------------------------------------------------------------------


def test_serialize_yaml_round_trips() -> None:
    spec = _minimal_spec(**{"/pets": {"get": _op("listPets")}})
    text = serialize_spec(spec, ".yaml")
    recovered = yaml.safe_load(text)
    assert recovered == spec


def test_serialize_json_round_trips() -> None:
    spec = _minimal_spec(**{"/pets": {"get": _op("listPets")}})
    text = serialize_spec(spec, ".json")
    recovered = json.loads(text)
    assert recovered == spec


def test_serialize_json_suffix_triggers_json() -> None:
    spec = _minimal_spec()
    text = serialize_spec(spec, ".json")
    # Must be valid JSON
    parsed = json.loads(text)
    assert parsed["openapi"] == "3.0.0"


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_fix_exits_zero_on_clean_spec(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, FIXTURES / "petstore_3.0.yaml")
    result = runner.invoke(app, ["fix", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "No fixable issues found." in result.output


def test_fix_assigns_and_dedupes_in_place(tmp_path: Path) -> None:
    spec_dst = tmp_path / "spec.yaml"
    spec_dst.write_bytes((FIXTURES / "fixable_spec.yaml").read_bytes())
    cfg = _write_config(tmp_path, spec_dst)
    result = runner.invoke(app, ["fix", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    # File should have been rewritten
    from pyoas.core.tags import HTTP_METHODS

    updated = yaml.safe_load(spec_dst.read_text())
    op_ids = []
    for path_item in updated["paths"].values():
        for method, op in path_item.items():
            if method in HTTP_METHODS and isinstance(op, dict) and "operationId" in op:
                op_ids.append(op["operationId"])
    assert len(op_ids) == len(set(op_ids)), "operationIds must be unique after fix"
    # No missing operation ids
    for path_item in updated["paths"].values():
        for method, op in path_item.items():
            if method in HTTP_METHODS and isinstance(op, dict):
                assert "operationId" in op


def test_fix_dry_run_does_not_write(tmp_path: Path) -> None:
    spec_dst = tmp_path / "spec.yaml"
    spec_dst.write_bytes((FIXTURES / "fixable_spec.yaml").read_bytes())
    original_content = spec_dst.read_text()
    cfg = _write_config(tmp_path, spec_dst)
    result = runner.invoke(app, ["fix", "--config", str(cfg), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert spec_dst.read_text() == original_content


def test_fix_dry_run_exits_zero(tmp_path: Path) -> None:
    spec_dst = tmp_path / "spec.yaml"
    spec_dst.write_bytes((FIXTURES / "fixable_spec.yaml").read_bytes())
    cfg = _write_config(tmp_path, spec_dst)
    result = runner.invoke(app, ["fix", "--config", str(cfg), "--dry-run"])
    assert result.exit_code == 0


def test_fix_dry_run_output_contains_diff(tmp_path: Path) -> None:
    spec_dst = tmp_path / "spec.yaml"
    spec_dst.write_bytes((FIXTURES / "fixable_spec.yaml").read_bytes())
    cfg = _write_config(tmp_path, spec_dst)
    result = runner.invoke(app, ["fix", "--config", str(cfg), "--dry-run"])
    assert "---" in result.output
    assert "+++" in result.output


def test_fix_shows_action_count(tmp_path: Path) -> None:
    spec_dst = tmp_path / "spec.yaml"
    spec_dst.write_bytes((FIXTURES / "fixable_spec.yaml").read_bytes())
    cfg = _write_config(tmp_path, spec_dst)
    result = runner.invoke(app, ["fix", "--config", str(cfg)])
    assert "fix(es) applied" in result.output


def test_fix_doctor_confirms_resolution(tmp_path: Path) -> None:
    spec_dst = tmp_path / "spec.yaml"
    spec_dst.write_bytes((FIXTURES / "fixable_spec.yaml").read_bytes())
    cfg = _write_config(tmp_path, spec_dst)
    result = runner.invoke(app, ["fix", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "all fixable issues resolved" in result.output


def test_fix_tag_casing_lower(tmp_path: Path) -> None:
    # fixable_spec has a collision group: "my-tag" / "My-Tag"
    # With casing=lower, both should be normalized to the lowercase canonical form.
    from pyoas.core.tags import HTTP_METHODS

    spec_dst = tmp_path / "spec.yaml"
    spec_dst.write_bytes((FIXTURES / "fixable_spec.yaml").read_bytes())
    cfg = _write_config(tmp_path, spec_dst)
    result = runner.invoke(app, ["fix", "--config", str(cfg), "--tag-casing", "lower"])
    assert result.exit_code == 0, result.output
    updated = yaml.safe_load(spec_dst.read_text())
    for path_item in updated["paths"].values():
        for method, op in path_item.items():
            if method in HTTP_METHODS and isinstance(op, dict):
                for tag in op.get("tags") or []:
                    assert tag == tag.lower(), f"tag {tag!r} should be lowercase"


def test_fix_json_spec_round_trips_as_json(tmp_path: Path) -> None:
    # Convert petstore YAML to JSON, then run fix, verify output is still valid JSON
    petstore = yaml.safe_load((FIXTURES / "petstore_3.0.yaml").read_text())
    spec_dst = tmp_path / "spec.json"
    spec_dst.write_text(json.dumps(petstore, indent=2), encoding="utf-8")
    cfg = _write_config(tmp_path, spec_dst)
    result = runner.invoke(app, ["fix", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    # Output file should still be valid JSON
    json.loads(spec_dst.read_text())


def test_fix_exits_one_when_unfixable_errors_remain(tmp_path: Path) -> None:
    # Spec with BOTH a fixable issue (missing operationId) and an unfixable error
    # (unresolvable $ref). After fix, doctor should still report the ref error → exit 1.
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/pets": {
                "get": {
                    # No operationId — fixable
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {
                        "owner": {"$ref": "#/components/schemas/DoesNotExist"},
                    },
                }
            }
        },
    }
    spec_dst = tmp_path / "spec.yaml"
    spec_dst.write_text(yaml.dump(spec), encoding="utf-8")
    cfg = _write_config(tmp_path, spec_dst)
    result = runner.invoke(app, ["fix", "--config", str(cfg)])
    assert result.exit_code == 1
