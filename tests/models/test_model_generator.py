"""
End-to-end and unit tests for ModelGenerator.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from syrupy.assertion import SnapshotAssertion

from pyoas.core.analysis import (
    _find_referenced_schemas,
    build_schema_tag_map,
    detect_generic_groups_global,
)
from pyoas.core.config import (
    Config,
    FieldsConfig,
    FormatConfig,
    ModelConfig,
    OutputConfig,
    WebhooksConfig,
)
from pyoas.models.classifier import _collect_shared_schemas
from pyoas.models.generator import ModelGenerator
from pyoas.models.schema_renderer import _render_enum_class, _render_schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(spec_path: str, output_dir: str) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(models=output_dir, routers=""),
        model_config=ModelConfig(extra="ignore", frozen=False, populate_by_name=True),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),  # skip ruff in tests
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# _find_referenced_schemas (raw-spec $ref traversal)
# ---------------------------------------------------------------------------


def test_find_referenced_schemas_direct() -> None:
    components = {"Pet": {"type": "object"}, "Tag": {"type": "object"}}
    obj = {"schema": {"$ref": "#/components/schemas/Pet"}}
    names = _find_referenced_schemas(obj, components)
    assert "Pet" in names


def test_find_referenced_schemas_transitive() -> None:
    components = {
        "PetList": {"properties": {"items": {"$ref": "#/components/schemas/Pet"}}},
        "Pet": {"type": "object"},
    }
    obj = {"$ref": "#/components/schemas/PetList"}
    names = _find_referenced_schemas(obj, components)
    assert "PetList" in names
    assert "Pet" in names


def test_find_referenced_schemas_no_refs() -> None:
    components: dict[str, Any] = {"Pet": {}}
    obj = {"type": "string"}
    assert _find_referenced_schemas(obj, components) == []


# ---------------------------------------------------------------------------
# Schema-to-tag mapping
# ---------------------------------------------------------------------------


def test_schema_tag_map_petstore(petstore_30: Path) -> None:
    from pyoas.core.parser import SpecParser
    from pyoas.core.tags import extract_tags

    spec_raw = SpecParser(str(petstore_30)).load()
    grouped_raw = extract_tags(spec_raw)
    tag_map = build_schema_tag_map(spec_raw, grouped_raw)

    assert "Pet" in tag_map
    assert tag_map["Pet"] == {"pets"}
    assert tag_map["PetList"] == {"pets"}
    assert tag_map["CreatePetRequest"] == {"pets"}


def test_shared_schema_detected(multi_tag: Path) -> None:
    from pyoas.core.parser import SpecParser
    from pyoas.core.resolver import resolve_refs
    from pyoas.core.tags import extract_tags

    spec_raw = SpecParser(str(multi_tag)).load()
    spec = resolve_refs(spec_raw, str(multi_tag))
    grouped_raw = extract_tags(spec_raw)
    tag_map = build_schema_tag_map(spec_raw, grouped_raw)

    # Address is referenced by both users (via User) and orders (via Order)
    assert "Address" in tag_map
    assert len(tag_map["Address"]) == 2

    raw_cs = spec_raw.get("components", {}).get("schemas", {})
    shared = _collect_shared_schemas(spec, tag_map, raw_cs)
    shared_names = [s["name"] for s in shared]
    assert "Address" in shared_names


# ---------------------------------------------------------------------------
# readOnly / writeOnly split
# ---------------------------------------------------------------------------


def test_readonly_writeonly_split() -> None:
    schema_entry: dict[str, Any] = {
        "name": "UserForm",
        "schema": {
            "type": "object",
            "required": ["email"],
            "properties": {
                "id": {"type": "integer", "readOnly": True},
                "email": {"type": "string"},
                "password": {"type": "string", "writeOnly": True},
            },
        },
        "raw_schema": {
            "type": "object",
            "required": ["email"],
            "properties": {
                "id": {"type": "integer", "readOnly": True},
                "email": {"type": "string"},
                "password": {"type": "string", "writeOnly": True},
            },
        },
    }
    cfg = Config(
        spec="dummy.yaml",
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
    )
    rendered = _render_schema(schema_entry, cfg)
    # Read, Write, plus alias {name} = {name}Read
    assert len(rendered) == 3
    names = [r["name"] for r in rendered]
    assert "UserFormRead" in names
    assert "UserFormWrite" in names
    assert "UserForm" in names

    alias = next(r for r in rendered if r["name"] == "UserForm")
    assert alias["is_alias"] is True
    assert alias["alias_type"] == "UserFormRead"

    read_model = next(r for r in rendered if r["name"] == "UserFormRead")
    write_model = next(r for r in rendered if r["name"] == "UserFormWrite")

    read_field_names = [f["name"] for f in read_model["fields"]]
    write_field_names = [f["name"] for f in write_model["fields"]]

    # Read: id (readOnly) + email; no password (writeOnly)
    assert "id" in read_field_names
    assert "email" in read_field_names
    assert "password" not in read_field_names

    # Write: email + password (writeOnly); no id (readOnly)
    assert "id" not in write_field_names
    assert "email" in write_field_names
    assert "password" in write_field_names


def test_readonly_only_splits() -> None:
    """Schemas with only readOnly fields (no writeOnly) should also be split."""
    schema_entry: dict[str, Any] = {
        "name": "Item",
        "schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "readOnly": True},
                "name": {"type": "string"},
            },
        },
        "raw_schema": None,
    }
    cfg = Config(spec="dummy.yaml")
    rendered = _render_schema(schema_entry, cfg)
    assert len(rendered) == 3
    names = [r["name"] for r in rendered]
    assert "ItemRead" in names
    assert "ItemWrite" in names

    alias = next(r for r in rendered if r.get("is_alias"))
    assert alias["name"] == "Item"
    assert alias["alias_type"] == "ItemRead"

    read_model = next(r for r in rendered if r["name"] == "ItemRead")
    write_model = next(r for r in rendered if r["name"] == "ItemWrite")

    read_field_names = [f["name"] for f in read_model["fields"]]
    write_field_names = [f["name"] for f in write_model["fields"]]

    assert "id" in read_field_names  # readOnly included in Read
    assert "name" in read_field_names
    assert "id" not in write_field_names  # readOnly excluded from Write
    assert "name" in write_field_names


# ---------------------------------------------------------------------------
# End-to-end snapshot tests
# ---------------------------------------------------------------------------


def test_generate_petstore_30(petstore_30: Path, snapshot: SnapshotAssertion) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        ModelGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "__init__.py").exists()
        assert (output / "pets.py").exists()
        assert (output / "store.py").exists()

        assert _read(output / "pets.py") == snapshot(name="pets_models_30")
        assert _read(output / "store.py") == snapshot(name="store_models_30")
        assert _read(output / "__init__.py") == snapshot(name="root_init_30")


def test_generate_petstore_31(petstore_31: Path, snapshot: SnapshotAssertion) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_31), tmp)
        ModelGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "pets.py").exists()
        assert _read(output / "pets.py") == snapshot(name="pets_models_31")


def test_generate_multi_tag(multi_tag: Path, snapshot: SnapshotAssertion) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(multi_tag), tmp)
        ModelGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "users.py").exists()
        assert (output / "orders.py").exists()
        assert (output / "shared.py").exists()

        assert _read(output / "users.py") == snapshot(name="users_models")
        assert _read(output / "orders.py") == snapshot(name="orders_models")
        assert _read(output / "shared.py") == snapshot(name="shared_models")


def test_generate_no_tags(no_tags: Path, snapshot: SnapshotAssertion) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(no_tags), tmp)
        ModelGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "default.py").exists()
        assert _read(output / "default.py") == snapshot(name="default_models")


def test_generate_discriminated(
    discriminated: Path, snapshot: SnapshotAssertion
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(discriminated), tmp)
        ModelGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "events.py").exists()
        assert _read(output / "events.py") == snapshot(name="events_models")


# ---------------------------------------------------------------------------
# Tag filter
# ---------------------------------------------------------------------------


def test_tag_filter(multi_tag: Path) -> None:
    import warnings

    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(multi_tag), tmp)
        # Filtering to a subset of tags means schemas owned by other tags are
        # unreferenced from the filter's perspective — expect the warning.
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            ModelGenerator(cfg).generate(tag_filter=["users"])

        output = Path(tmp)
        assert (output / "users.py").exists()
        assert not (output / "orders.py").exists()


# ---------------------------------------------------------------------------
# Generic extraction
# ---------------------------------------------------------------------------


def test_detect_generic_groups_cross_tag(generic_paginated: Path) -> None:
    from pyoas.core.parser import SpecParser
    from pyoas.core.tags import extract_tags

    spec_raw = SpecParser(str(generic_paginated)).load()
    grouped_raw = extract_tags(spec_raw)
    tag_map = build_schema_tag_map(spec_raw, grouped_raw)
    raw_cs = spec_raw.get("components", {}).get("schemas", {})

    groups = detect_generic_groups_global(raw_cs, tag_map)

    assert "Paginated" in groups
    grp = groups["Paginated"]
    assert grp.t_field_name == "data"
    assert grp.t_is_list is True
    # Two instances span two different tags → home_tag must be None (shared)
    assert len(grp.instances) == 2
    assert grp.home_tag is None


def test_generate_generic_paginated(
    generic_paginated: Path, snapshot: SnapshotAssertion
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(generic_paginated), tmp)
        ModelGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "shared.py").exists()
        assert (output / "fleet.py").exists()
        assert (output / "users.py").exists()

        shared_src = _read(output / "shared.py")
        fleet_src = _read(output / "fleet.py")
        users_src = _read(output / "users.py")

        # Shared module must contain the generic base class
        assert "class Paginated(BaseModel, Generic[T])" in shared_src
        assert "T = TypeVar" in shared_src

        # Tag modules must contain clean aliases and compat aliases
        assert "PaginatedDriverListItem = Paginated[DriverListItem]" in fleet_src
        assert "Paginated_DriverListItem_ = PaginatedDriverListItem" in fleet_src
        assert "PaginatedUserListItem = Paginated[UserListItem]" in users_src
        assert "Paginated_UserListItem_ = PaginatedUserListItem" in users_src

        assert shared_src == snapshot(name="generic_paginated_shared")
        assert fleet_src == snapshot(name="generic_paginated_fleet")
        assert users_src == snapshot(name="generic_paginated_users")


def test_detect_generic_groups_no_trailing_underscore(
    generic_paginated_no_trailing: Path,
) -> None:
    """Mangled-key detection works for 'Prefix_TypeParam' (no trailing underscore)."""
    from pyoas.core.parser import SpecParser
    from pyoas.core.tags import extract_tags

    spec_raw = SpecParser(str(generic_paginated_no_trailing)).load()
    grouped_raw = extract_tags(spec_raw)
    tag_map = build_schema_tag_map(spec_raw, grouped_raw)
    raw_cs = spec_raw.get("components", {}).get("schemas", {})

    groups = detect_generic_groups_global(raw_cs, tag_map)

    assert "PagingResult" in groups
    grp = groups["PagingResult"]
    assert grp.t_field_name == "items"
    assert grp.t_is_list is True
    assert len(grp.instances) == 2
    assert grp.home_tag is None


def test_generate_generic_paginated_no_trailing(
    generic_paginated_no_trailing: Path,
) -> None:
    """Schemas like 'PagingResult_DriverListItem' (no trailing _) produce generic output."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(generic_paginated_no_trailing), tmp)
        ModelGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "shared.py").exists()
        assert (output / "fleet.py").exists()
        assert (output / "users.py").exists()

        shared_src = _read(output / "shared.py")
        fleet_src = _read(output / "fleet.py")
        users_src = _read(output / "users.py")

        assert "class PagingResult(BaseModel, Generic[T])" in shared_src
        assert "T = TypeVar" in shared_src

        assert "PagingResultDriverListItem = PagingResult[DriverListItem]" in fleet_src
        assert "PagingResult_DriverListItem = PagingResultDriverListItem" in fleet_src
        assert "PagingResultUserListItem = PagingResult[UserListItem]" in users_src
        assert "PagingResult_UserListItem = PagingResultUserListItem" in users_src


def test_generate_read_write(read_write: Path, snapshot: SnapshotAssertion) -> None:
    """readOnly/writeOnly fields produce Read/Write split + original-name alias."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(read_write), tmp)
        ModelGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "documents.py").exists()
        src = _read(output / "documents.py")

        # All three variants must be present
        assert "class DocumentRead" in src
        assert "class DocumentWrite" in src
        assert "Document = DocumentRead" in src

        read_section = src.split("class DocumentRead")[1].split("class DocumentWrite")[
            0
        ]
        write_section = src.split("class DocumentWrite")[1].split("Document =")[0]

        # Read: id (readOnly) present, secret (writeOnly) absent
        assert "    id:" in read_section
        assert "    secret:" not in read_section

        # Write: secret (writeOnly) present, id (readOnly) absent
        assert "    id:" not in write_section
        assert "    secret:" in write_section

        assert src == snapshot(name="documents_models_read_write")


def test_generate_inline_schemas(
    inline_schemas: Path, snapshot: SnapshotAssertion
) -> None:
    """Inline requestBody and response schemas become named Pydantic classes."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(inline_schemas), tmp)
        ModelGenerator(cfg).generate()

        src = (Path(tmp) / "reports.py").read_text()
        assert "class CreateReportBody" in src
        assert "class CreateReportResponse" in src
        assert "dict[str, Any]" not in src
        assert src == snapshot(name="reports_models_inline_schemas")


def test_generate_enum_as_str_enum(
    component_enums: Path, snapshot: SnapshotAssertion
) -> None:
    """Component enum schemas with enums_as_literals=False generate StrEnum/IntEnum classes."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(component_enums),
            output=OutputConfig(models=tmp, routers=""),
            model_config=ModelConfig(
                extra="ignore", frozen=False, populate_by_name=True
            ),
            fields=FieldsConfig(snake_case=True, enums_as_literals=False),
            format=FormatConfig(enabled=False),
        )
        ModelGenerator(cfg).generate()

        src = (Path(tmp) / "pets.py").read_text()
        assert "class PetStatus(StrEnum):" in src
        assert "AVAILABLE = 'available'" in src
        assert "class Priority(IntEnum):" in src
        assert "LOW = 1" in src
        assert src == snapshot(name="pets_models_str_enum")


def test_x_enum_varnames_used_when_present() -> None:
    """x-enum-varnames overrides synthesized member names in IntEnum classes."""
    schema = {
        "type": "integer",
        "enum": [1, 2, 3],
        "x-enum-varnames": ["LOW", "MEDIUM", "HIGH"],
    }
    result = _render_enum_class("Priority", schema)
    members = result[0]["members"]
    assert [m["name"] for m in members] == ["LOW", "MEDIUM", "HIGH"]
    assert [m["value"] for m in members] == ["1", "2", "3"]


def test_x_enum_varnames_fallback() -> None:
    """Falls back to synthesis when x-enum-varnames is absent, empty, or too short."""
    # Absent
    r = _render_enum_class("P", {"type": "integer", "enum": [1, 2, 3]})
    assert [m["name"] for m in r[0]["members"]] == ["VALUE_1", "VALUE_2", "VALUE_3"]

    # Too short — partial override, synthesis for remainder
    r = _render_enum_class(
        "P",
        {"type": "integer", "enum": [1, 2, 3], "x-enum-varnames": ["LOW", "MEDIUM"]},
    )
    assert [m["name"] for m in r[0]["members"]] == ["LOW", "MEDIUM", "VALUE_3"]

    # Empty list — synthesize all
    r = _render_enum_class(
        "P", {"type": "integer", "enum": [1, 2, 3], "x-enum-varnames": []}
    )
    assert [m["name"] for m in r[0]["members"]] == ["VALUE_1", "VALUE_2", "VALUE_3"]


_ORPHAN_SPEC = """\
openapi: "3.0.3"
info:
  title: Test
  version: "1.0"
paths:
  /pets:
    get:
      operationId: listPets
      tags: [pets]
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Pet'
components:
  schemas:
    Pet:
      type: object
      properties:
        id:
          type: integer
    Orphan:
      type: object
      properties:
        name:
          type: string
"""


def test_unreferenced_schema_warning(tmp_path: Path, capsys) -> None:
    """Schemas in components/schemas not referenced by any operation emit a warning on stderr."""
    spec_path = tmp_path / "openapi.yaml"
    spec_path.write_text(_ORPHAN_SPEC)
    cfg = _make_config(str(spec_path), str(tmp_path / "out"))
    ModelGenerator(cfg).generate()
    stderr = capsys.readouterr().err
    assert "Orphan" in stderr
    assert "include_unreferenced" in stderr


def test_include_unreferenced_generates_in_shared(tmp_path: Path) -> None:
    """With include_unreferenced=True, orphaned schemas are written to shared.py."""
    import warnings

    spec_path = tmp_path / "openapi.yaml"
    spec_path.write_text(_ORPHAN_SPEC)
    out = str(tmp_path / "out")
    cfg = Config(
        spec=str(spec_path),
        output=OutputConfig(models=out, routers=""),
        model_config=ModelConfig(
            extra="ignore",
            frozen=False,
            populate_by_name=True,
            include_unreferenced=True,
        ),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
    )
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        ModelGenerator(cfg).generate()

    shared = (Path(out) / "shared.py").read_text()
    assert "class Orphan" in shared


def test_generate_enum_as_literal(
    component_enums: Path, snapshot: SnapshotAssertion
) -> None:
    """Component enum schemas with enums_as_literals=True generate Literal type aliases."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(
            str(component_enums), tmp
        )  # enums_as_literals=True by default
        ModelGenerator(cfg).generate()

        src = (Path(tmp) / "pets.py").read_text()
        assert 'PetStatus = Literal["available"' in src
        assert "StrEnum" not in src
        assert src == snapshot(name="pets_models_literal_enum")


def test_generate_deprecated_fields(
    deprecated_fields: Path, snapshot: SnapshotAssertion
) -> None:
    """Schema properties marked deprecated:true emit Field(deprecated=True)."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(deprecated_fields), tmp)
        ModelGenerator(cfg).generate()

        src = (Path(tmp) / "items.py").read_text()
        # Deprecated fields carry the kwarg.
        assert "deprecated=True" in src
        # Non-deprecated fields must NOT carry it.
        lines = {line.strip() for line in src.splitlines()}
        assert not any("id:" in line and "deprecated" in line for line in lines)
        assert not any(
            line.startswith("name:") and "deprecated" in line for line in lines
        )
        assert src == snapshot(name="items_models_deprecated_fields")


# ---------------------------------------------------------------------------
# Webhook support
# ---------------------------------------------------------------------------


def test_generate_webhooks_warning_when_disabled(webhooks_31: Path, capsys) -> None:
    """When webhooks.generate=False and spec has webhooks, a warning is printed to stderr."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(webhooks_31), tmp)
        # webhooks.generate defaults to False
        ModelGenerator(cfg).generate()
        stderr = capsys.readouterr().err
        assert "webhooks" in stderr.lower()


def test_generate_webhooks_no_warning_when_enabled(webhooks_31: Path, capsys) -> None:
    """When webhooks.generate=True, no webhook warning is emitted."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(webhooks_31),
            output=OutputConfig(models=tmp, routers=""),
            model_config=ModelConfig(
                extra="ignore", frozen=False, populate_by_name=True
            ),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
            webhooks=WebhooksConfig(generate=True),
        )
        ModelGenerator(cfg).generate()
        stderr = capsys.readouterr().err
        assert "not being generated" not in stderr


def test_generate_webhooks_produces_models(
    webhooks_31: Path, snapshot: SnapshotAssertion
) -> None:
    """With webhooks.generate=True, webhook schemas appear in the generated model file."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(webhooks_31),
            output=OutputConfig(models=tmp, routers=""),
            model_config=ModelConfig(
                extra="ignore", frozen=False, populate_by_name=True
            ),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
            webhooks=WebhooksConfig(generate=True),
        )
        ModelGenerator(cfg).generate()

        src = (Path(tmp) / "subscriptions.py").read_text()
        assert "class Subscription" in src
        assert "class SubscriptionEvent" in src
        assert src == snapshot(name="subscriptions_models_webhooks")


# ---------------------------------------------------------------------------
# allOf inheritance
# ---------------------------------------------------------------------------


def _make_allof_schema_entry(
    name: str,
    raw_allof: list,
    resolved_allof: list,
) -> dict:
    """Build a schema entry for _render_schema testing allOf patterns."""
    return {
        "name": name,
        "schema": {"allOf": resolved_allof},
        "raw_schema": {"allOf": raw_allof},
    }


def test_allof_single_ref_nested_generates_inheritance() -> None:
    """Dog(Animal) via nested allOf generates class Dog(Animal): breed: ... (not name)."""
    from pyoas.models.schema_renderer import _render_schema

    raw_allof = [
        {"$ref": "#/components/schemas/Animal"},
        {"type": "object", "properties": {"breed": {"type": "string"}}},
    ]
    resolved_allof = [
        {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
        {"type": "object", "properties": {"breed": {"type": "string"}}},
    ]
    entry = _make_allof_schema_entry("Dog", raw_allof, resolved_allof)
    cfg = Config(spec="dummy.yaml")

    rendered = _render_schema(entry, cfg)

    assert len(rendered) == 1
    rs = rendered[0]
    assert rs["name"] == "Dog"
    assert rs["bases"] == ["Animal"]
    field_names = [f["name"] for f in rs.get("fields", [])]
    assert "breed" in field_names
    assert "name" not in field_names  # inherited — must not be redeclared


def test_allof_flat_pattern_regression() -> None:
    """DogFlat (properties at top level) still works correctly after the fix."""
    from pyoas.models.schema_renderer import _render_schema

    # DogFlat: type: object, allOf: [{$ref: Animal}], properties: {coat: ...}
    entry = {
        "name": "DogFlat",
        "schema": {
            "type": "object",
            "allOf": [
                {
                    "type": "object",
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}},
                }
            ],
            "properties": {"coat": {"type": "string"}},
        },
        "raw_schema": {
            "type": "object",
            "allOf": [{"$ref": "#/components/schemas/Animal"}],
            "properties": {"coat": {"type": "string"}},
        },
    }
    cfg = Config(spec="dummy.yaml")

    rendered = _render_schema(entry, cfg)

    assert len(rendered) == 1
    rs = rendered[0]
    assert rs["bases"] == ["Animal"]
    field_names = [f["name"] for f in rs.get("fields", [])]
    assert "coat" in field_names
    assert "name" not in field_names  # only child-own properties at top level


def test_allof_child_no_own_fields_generates_pass_guard() -> None:
    """DogNoExtras (allOf with only a $ref, no extra properties) generates empty fields list."""
    from pyoas.models.schema_renderer import _render_schema

    raw_allof = [{"$ref": "#/components/schemas/Animal"}]
    resolved_allof = [
        {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
    ]
    entry = _make_allof_schema_entry("DogNoExtras", raw_allof, resolved_allof)
    cfg = Config(spec="dummy.yaml")

    rendered = _render_schema(entry, cfg)

    assert len(rendered) == 1
    rs = rendered[0]
    assert rs["bases"] == ["Animal"]
    assert rs.get("fields", []) == []  # template will render 'pass'


def test_allof_multi_ref_keeps_existing_behavior() -> None:
    """Multi-$ref allOf (two $refs) still uses bases for both (existing behavior)."""
    from pyoas.models.schema_renderer import _render_schema

    raw_allof = [
        {"$ref": "#/components/schemas/Animal"},
        {"$ref": "#/components/schemas/Dog"},
    ]
    resolved_allof = [
        {"type": "object", "properties": {"name": {"type": "string"}}},
        {"type": "object", "properties": {"breed": {"type": "string"}}},
    ]
    entry = _make_allof_schema_entry("MultiParent", raw_allof, resolved_allof)
    cfg = Config(spec="dummy.yaml")

    rendered = _render_schema(entry, cfg)

    assert len(rendered) == 1
    rs = rendered[0]
    # Multi-$ref: bases has both; fields are from top-level properties (empty here)
    assert "Animal" in rs["bases"]
    assert "Dog" in rs["bases"]


def test_allof_inheritance_full_generation(
    allof_inheritance: Path, snapshot: SnapshotAssertion
) -> None:
    """Full generation snapshot for allOf inheritance fixture."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(allof_inheritance), tmp)
        ModelGenerator(cfg).generate()

        animals_src = (Path(tmp) / "animals.py").read_text()
        shared_src = (Path(tmp) / "shared.py").read_text()

        # Dog should inherit from Animal, not redeclare 'name'
        assert "class Dog(Animal)" in animals_src
        assert "breed" in animals_src
        assert "from .shared import Animal" in animals_src

        # Animal lives in shared (referenced by both tags)
        assert "class Animal" in shared_src

        assert animals_src == snapshot(name="allof_animals_models")
        assert shared_src == snapshot(name="allof_shared_models")


def test_allof_child_with_shared_base_generates_import(
    allof_inheritance: Path,
) -> None:
    """Dog(Animal) where Animal is in shared.py gets 'from .shared import Animal'."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(allof_inheritance), tmp)
        ModelGenerator(cfg).generate()

        animals_src = (Path(tmp) / "animals.py").read_text()
        assert "from .shared import Animal" in animals_src


def test_generate_circular_ref(circular_ref: Path, snapshot: SnapshotAssertion) -> None:
    """Self-referencing schemas generate valid importable Python."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(circular_ref), tmp)
        ModelGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "trees.py").exists()
        src = _read(output / "trees.py")
        assert "from __future__ import annotations" in src
        assert "class TreeNode" in src
        assert src == snapshot(name="circular_ref_trees")


# ---------------------------------------------------------------------------
# uniqueItems serialization
# ---------------------------------------------------------------------------


def test_unique_items_default_emits_set(unique_items: Path) -> None:
    """Default config (unique_items_as_set=True): uniqueItems fields use set[T]."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(unique_items), tmp)
        ModelGenerator(cfg).generate()

        src = _read(Path(tmp) / "resources.py")
        assert "set[str]" in src
        assert "model_validator" not in src


def test_unique_items_as_set_false_emits_list_with_validator(
    unique_items: Path, snapshot: SnapshotAssertion
) -> None:
    """unique_items_as_set=False: uniqueItems fields use list[T] + dedup model_validator."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(unique_items),
            output=OutputConfig(models=tmp, routers=""),
            model_config=ModelConfig(
                extra="ignore", frozen=False, populate_by_name=True
            ),
            fields=FieldsConfig(
                snake_case=True, enums_as_literals=True, unique_items_as_set=False
            ),
            format=FormatConfig(enabled=False),
        )
        ModelGenerator(cfg).generate()

        src = _read(Path(tmp) / "resources.py")
        # Fields must be list, not set
        assert "list[str]" in src
        assert "list[int]" in src
        assert "set[" not in src
        # Dedup validator must be present
        assert "model_validator" in src
        assert "_deduplicate_unique_items" in src
        assert "object.__setattr__" in src
        assert src == snapshot(name="unique_items_list_with_validator")


# ---------------------------------------------------------------------------
# OAS 3.1 $defs support
# ---------------------------------------------------------------------------


def test_generate_inline_defs_31(
    inline_defs_31: Path, snapshot: SnapshotAssertion
) -> None:
    """OAS 3.1 $defs schemas are collected and emitted as named classes."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(inline_defs_31), tmp)
        ModelGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "pets.py").exists()
        assert (output / "orders.py").exists()
        assert (output / "shared.py").exists()

        pets_src = _read(output / "pets.py")
        orders_src = _read(output / "orders.py")
        shared_src = _read(output / "shared.py")

        # Tag-local $defs: PetStatus and Tag appear in pets.py
        assert "PetStatus" in pets_src
        assert "class Tag" in pets_src

        # Tag-local $defs appear before the parent schema that references them
        assert pets_src.index("class Tag") < pets_src.index("class Pet")

        # Shared $defs: Label lives in shared.py and is imported in both tag files
        assert "class Label" in shared_src
        assert "from .shared import Label" in pets_src
        assert "from .shared import Label" in orders_src

        # Label must not be redeclared in the tag files
        assert "class Label" not in pets_src
        assert "class Label" not in orders_src

        assert pets_src == snapshot(name="inline_defs_31_pets")
        assert orders_src == snapshot(name="inline_defs_31_orders")
        assert shared_src == snapshot(name="inline_defs_31_shared")
