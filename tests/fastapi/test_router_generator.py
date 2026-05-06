"""
End-to-end and unit tests for RouterGenerator.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from syrupy.assertion import SnapshotAssertion

from pyoas.core.config import (
    Config,
    DependenciesConfig,
    FieldsConfig,
    FormatConfig,
    OutputConfig,
    RouterConfig,
    ServicesConfig,
    WebhooksConfig,
)
from pyoas.fastapi.generator import RouterGenerator
from pyoas.fastapi.scaffold import ServiceScaffolder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(spec_path: str, output_dir: str) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(models="src/generated/models", routers=output_dir),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),  # skip ruff in tests
    )


def _make_config_with_services(
    spec_path: str, routers_dir: str, services_dir: str, import_path: str
) -> Config:
    return Config(
        spec=spec_path,
        output=OutputConfig(models="src/generated/models", routers=routers_dir),
        fields=FieldsConfig(snake_case=True, enums_as_literals=True),
        format=FormatConfig(enabled=False),
        services=ServicesConfig(
            generate=True,
            output=services_dir,
            overwrite=True,
            import_path=import_path,
        ),
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# End-to-end snapshot tests
# ---------------------------------------------------------------------------


def test_generate_petstore_30(petstore_30: Path, snapshot: SnapshotAssertion) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        RouterGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "__init__.py").exists()
        assert (output / "pets.py").exists()
        assert (output / "store.py").exists()

        assert _read(output / "pets.py") == snapshot(name="pets_router_30")
        assert _read(output / "store.py") == snapshot(name="store_router_30")
        assert _read(output / "__init__.py") == snapshot(name="root_init_30")


def test_generate_petstore_31(petstore_31: Path, snapshot: SnapshotAssertion) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_31), tmp)
        RouterGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "pets.py").exists()
        assert _read(output / "pets.py") == snapshot(name="pets_router_31")


def test_generate_multi_tag(multi_tag: Path, snapshot: SnapshotAssertion) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(multi_tag), tmp)
        RouterGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "users.py").exists()
        assert (output / "orders.py").exists()

        assert _read(output / "users.py") == snapshot(name="users_router")
        assert _read(output / "orders.py") == snapshot(name="orders_router")
        assert _read(output / "__init__.py") == snapshot(name="root_init_multi")


def test_generate_no_tags(no_tags: Path, snapshot: SnapshotAssertion) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(no_tags), tmp)
        RouterGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "default.py").exists()
        assert _read(output / "default.py") == snapshot(name="default_router")


def test_generate_optional_before_required(
    optional_before_required: Path, snapshot: SnapshotAssertion
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(optional_before_required), tmp)
        RouterGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "default.py").exists()
        assert _read(output / "default.py") == snapshot(name="repro_router")


def test_generate_generic_paginated(
    generic_paginated: Path, snapshot: SnapshotAssertion
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(generic_paginated), tmp)
        RouterGenerator(cfg).generate()

        output = Path(tmp)
        fleet_src = _read(output / "fleet.py")
        users_src = _read(output / "users.py")

        # Router must use generic bracket syntax, not mangled names
        assert "Paginated[DriverListItem]" in fleet_src
        assert "Paginated_DriverListItem_" not in fleet_src
        assert "Paginated[UserListItem]" in users_src
        assert "Paginated_UserListItem_" not in users_src

        assert fleet_src == snapshot(name="fleet_router_generic")
        assert users_src == snapshot(name="users_router_generic")


# ---------------------------------------------------------------------------
# Tag filter
# ---------------------------------------------------------------------------


def test_tag_filter(multi_tag: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(multi_tag), tmp)
        RouterGenerator(cfg).generate(tag_filter=["users"])

        output = Path(tmp)
        assert (output / "users.py").exists()
        assert not (output / "orders.py").exists()


# ---------------------------------------------------------------------------
# Clean flag
# ---------------------------------------------------------------------------


def test_clean_flag(petstore_30: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        gen = RouterGenerator(cfg)

        # Write a stale file that should be removed by --clean
        stale = Path(tmp) / "stale_tag.py"
        stale.write_text("# stale", encoding="utf-8")

        gen.generate(clean=True)

        assert not stale.exists()
        assert (Path(tmp) / "pets.py").exists()


# ---------------------------------------------------------------------------
# Function name generation
# ---------------------------------------------------------------------------


def test_function_name_from_operation_id(petstore_30: Path) -> None:
    """operationId values are converted to snake_case function names."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "pets.py")
        assert "async def list_pets(" in src
        assert "async def create_pet(" in src
        assert "async def get_pet(" in src


def test_function_name_fallback(no_tags: Path) -> None:
    """Operations without operationId fall back to {method}_{path_slug}."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(no_tags), tmp)
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "default.py")
        # Should contain an auto-generated snake_case function name
        assert "async def " in src


def test_function_name_repro_user_issue() -> None:
    """Check if /app/charging-stations GET results in duplication."""
    from pyoas.core.utils import generate_function_name

    name = generate_function_name("get", "/app/charging-stations")
    assert name == "get_app_charging_stations"


def test_function_name_double_prefix() -> None:
    """Check that we don't get get_get_items."""
    from pyoas.core.utils import generate_function_name

    assert generate_function_name("get", "/get-items") == "get_items"
    assert generate_function_name("post", "/post/order") == "post_order"
    assert generate_function_name("get", "/get") == "get"


# ---------------------------------------------------------------------------
# Service scaffold tests
# ---------------------------------------------------------------------------


def test_scaffold_service_imports(multi_tag: Path, snapshot: SnapshotAssertion) -> None:
    """Scaffolded service files must include model and stdlib imports."""
    with tempfile.TemporaryDirectory() as routers_tmp:
        with tempfile.TemporaryDirectory() as services_tmp:
            cfg = _make_config_with_services(
                str(multi_tag), routers_tmp, services_tmp, "myapp.services"
            )
            ServiceScaffolder(cfg).scaffold()

            services_root = Path(services_tmp)
            assert (services_root / "users.py").exists()
            assert (services_root / "orders.py").exists()
            assert (services_root / "__init__.py").exists()

            users_src = _read(services_root / "users.py")
            orders_src = _read(services_root / "orders.py")

            # Must have service class, dep provider, and model imports
            assert "class UsersService:" in users_src
            assert "async def get_users_service()" in users_src
            assert "from generated.models." in users_src
            assert "from generated.models." in orders_src

            assert users_src == snapshot(name="users_service")
            assert orders_src == snapshot(name="orders_service")


def test_scaffold_warns_on_orphaned_methods(multi_tag: Path) -> None:
    """When overwrite=False, methods without matching spec operations emit a warning."""
    import io
    import sys

    with tempfile.TemporaryDirectory() as routers_tmp:
        with tempfile.TemporaryDirectory() as services_tmp:
            cfg = _make_config_with_services(
                str(multi_tag), routers_tmp, services_tmp, "myapp.services"
            )
            cfg.services.overwrite = False
            ServiceScaffolder(cfg).scaffold()

            users_file = Path(services_tmp) / "users.py"
            # Inject a ghost method that doesn't exist in the spec
            extra = "\n    async def ghost_operation(self) -> None:\n        raise NotImplementedError\n"
            users_file.write_text(users_file.read_text() + extra, encoding="utf-8")

            stderr = io.StringIO()
            old_stderr = sys.stderr
            sys.stderr = stderr
            try:
                ServiceScaffolder(cfg).scaffold()
            finally:
                sys.stderr = old_stderr

            output = stderr.getvalue()
            assert "ghost_operation" in output
            assert "orphaned" in output


def test_scaffold_service_skips_existing_methods(multi_tag: Path) -> None:
    """Existing methods are not duplicated; missing methods are added on re-run."""
    with tempfile.TemporaryDirectory() as routers_tmp:
        with tempfile.TemporaryDirectory() as services_tmp:
            cfg = _make_config_with_services(
                str(multi_tag), routers_tmp, services_tmp, "myapp.services"
            )
            cfg.services.overwrite = False
            ServiceScaffolder(cfg).scaffold()

            users_file = Path(services_tmp) / "users.py"
            original = users_file.read_text()

            # Remove one method from the file to simulate a newly added endpoint
            import re

            trimmed = re.sub(
                r"\n    async def get_user\(.*?raise NotImplementedError\n",
                "\n",
                original,
                flags=re.DOTALL,
            )
            users_file.write_text(trimmed, encoding="utf-8")
            assert "async def get_user(" not in users_file.read_text()

            # Second pass — should add missing method, not touch existing ones
            ServiceScaffolder(cfg).scaffold()
            result = users_file.read_text()
            assert "async def get_user(" in result
            # Existing methods must appear exactly once
            assert result.count("async def list_users(") == 1

            # overwrite=True must fully regenerate
            cfg.services.overwrite = True
            ServiceScaffolder(cfg).scaffold()
            assert users_file.read_text() == original


# ---------------------------------------------------------------------------
# Router + service forwarding tests
# ---------------------------------------------------------------------------


def test_router_with_service_forwarding(
    multi_tag: Path, snapshot: SnapshotAssertion
) -> None:
    """When service_import_path is set, routers forward calls to service functions."""
    with tempfile.TemporaryDirectory() as routers_tmp:
        with tempfile.TemporaryDirectory() as services_tmp:
            cfg = _make_config_with_services(
                str(multi_tag), routers_tmp, services_tmp, "myapp.services"
            )
            RouterGenerator(cfg).generate()

            users_src = _read(Path(routers_tmp) / "users.py")
            orders_src = _read(Path(routers_tmp) / "orders.py")

            # Must import service class + dep fn and forward via service instance
            assert (
                "from myapp.services.users import UsersService, get_users_service"
                in users_src
            )
            assert "service: UsersService = Depends(get_users_service)" in users_src
            assert "return await service." in users_src
            assert "raise NotImplementedError" not in users_src

            assert (
                "from myapp.services.orders import OrdersService, get_orders_service"
                in orders_src
            )
            assert "return await service." in orders_src

            assert users_src == snapshot(name="users_router_with_service")
            assert orders_src == snapshot(name="orders_router_with_service")


def test_router_forwards_auth_to_service(
    secured: Path, snapshot: SnapshotAssertion
) -> None:
    """Router passes auth=current_user into service calls for secured operations."""
    with tempfile.TemporaryDirectory() as routers_tmp:
        with tempfile.TemporaryDirectory() as services_tmp:
            cfg = Config(
                spec=str(secured),
                output=OutputConfig(models="src/generated/models", routers=routers_tmp),
                fields=FieldsConfig(snake_case=True, enums_as_literals=True),
                format=FormatConfig(enabled=False),
                services=ServicesConfig(
                    generate=True,
                    output=services_tmp,
                    overwrite=True,
                    import_path="myapp.services",
                ),
                dependencies=DependenciesConfig(import_path="myapp.deps"),
            )
            RouterGenerator(cfg).generate()

            src = _read(Path(routers_tmp) / "items.py")
            assert "auth=current_user" in src
            # createItem is unsecured → its service call must NOT include auth
            assert src.count("auth=current_user") == 1
            assert src == snapshot(name="items_router_secured_with_service_and_dep")


def test_generate_form_upload(form_upload: Path, snapshot: SnapshotAssertion) -> None:
    """Multipart and urlencoded bodies generate Form/File/UploadFile params."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(form_upload), tmp)
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "files.py")

        assert "UploadFile" in src
        assert "File()" in src
        assert "Form()" in src
        assert src == snapshot(name="files_router_form_upload")


def test_generate_read_write(read_write: Path, snapshot: SnapshotAssertion) -> None:
    """Request body for split schema uses Write variant; response keeps original name."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(read_write), tmp)
        RouterGenerator(cfg).generate()

        src = (Path(tmp) / "documents.py").read_text()

        # POST body must use DocumentWrite
        assert "DocumentWrite" in src
        # Response type must use Document (alias = DocumentRead)
        assert "Document" in src

        assert src == snapshot(name="documents_router_read_write")


def test_generate_security_stubs(secured: Path, snapshot: SnapshotAssertion) -> None:
    """Operations with security requirements get a TODO auth comment stub."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(secured), tmp)
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "items.py")
        # listItems inherits global security → stub present
        assert "# TODO: add authentication dependency" in src
        assert src == snapshot(name="items_router_secured")


def test_generate_security_with_dep_import_path(
    secured: Path, snapshot: SnapshotAssertion
) -> None:
    """When dep_import_path is set, routers import AuthContext and type current_user."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(secured),
            output=OutputConfig(models="src/generated/models", routers=tmp),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
            dependencies=DependenciesConfig(import_path="myapp.deps"),
        )
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "items.py")
        assert "from myapp.deps.auth import AuthContext, get_auth_context" in src
        assert "current_user: AuthContext = Depends(get_auth_context)" in src
        # createItem has security: [] override → its function must not declare current_user
        assert src.count("current_user: AuthContext") == 1
        assert src == snapshot(name="items_router_secured_with_dep")


def test_scaffold_service_with_auth(secured: Path, snapshot: SnapshotAssertion) -> None:
    """Service methods for secured operations receive auth: AuthContext."""
    with tempfile.TemporaryDirectory() as routers_tmp:
        with tempfile.TemporaryDirectory() as services_tmp:
            cfg = Config(
                spec=str(secured),
                output=OutputConfig(models="src/generated/models", routers=routers_tmp),
                fields=FieldsConfig(snake_case=True, enums_as_literals=True),
                format=FormatConfig(enabled=False),
                services=ServicesConfig(
                    generate=True,
                    output=services_tmp,
                    overwrite=True,
                    import_path="myapp.services",
                ),
                dependencies=DependenciesConfig(import_path="myapp.deps"),
            )
            ServiceScaffolder(cfg).scaffold()

            src = _read(Path(services_tmp) / "items.py")
            # Secured method gets auth param
            assert "from myapp.deps.auth import AuthContext" in src
            assert "auth: AuthContext" in src
            # Unsecured method (createItem has security: []) must not get auth param
            assert src.count("auth: AuthContext") == 1
            assert src == snapshot(name="items_service_with_auth")


def test_generate_inline_schemas(
    inline_schemas: Path, snapshot: SnapshotAssertion
) -> None:
    """Inline object schemas in requestBody/responses become named model classes."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(inline_schemas), tmp)
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "reports.py")
        # Inline body → CreateReportBody; inline response → CreateReportResponse
        assert "CreateReportBody" in src
        assert "CreateReportResponse" in src
        assert "dict[str, Any]" not in src
        assert src == snapshot(name="reports_router_inline_schemas")


def test_response_model_exclude_none_in_decorator(petstore_30: Path) -> None:
    """response_model_exclude_none=True appears in route decorator kwargs."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(petstore_30),
            output=OutputConfig(models="src/generated/models", routers=tmp),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
            router=RouterConfig(response_model_exclude_none=True),
        )
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "pets.py")
        assert "response_model_exclude_none=True" in src


def test_response_model_exclude_unset_in_decorator(petstore_30: Path) -> None:
    """response_model_exclude_unset=True appears in route decorator kwargs."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(petstore_30),
            output=OutputConfig(models="src/generated/models", routers=tmp),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
            router=RouterConfig(response_model_exclude_unset=True),
        )
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "pets.py")
        assert "response_model_exclude_unset=True" in src


def test_response_model_exclude_none_off_by_default(petstore_30: Path) -> None:
    """With default config, response_model_exclude_none is NOT emitted."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(petstore_30), tmp)
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "pets.py")
        assert "response_model_exclude_none" not in src


# ---------------------------------------------------------------------------
# Webhook support
# ---------------------------------------------------------------------------


def test_generate_webhooks_warning_when_disabled(webhooks_31: Path, capsys) -> None:
    """When webhooks.generate=False and spec has webhooks, a warning goes to stderr."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(webhooks_31), tmp)
        RouterGenerator(cfg).generate()
        stderr = capsys.readouterr().err
        assert "webhooks" in stderr.lower()


def test_generate_webhooks_no_warning_when_enabled(webhooks_31: Path, capsys) -> None:
    """When webhooks.generate=True, no warning is emitted."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(webhooks_31),
            output=OutputConfig(models="src/generated/models", routers=tmp),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
            webhooks=WebhooksConfig(generate=True),
        )
        RouterGenerator(cfg).generate()
        stderr = capsys.readouterr().err
        assert "not being generated" not in stderr


def test_generate_webhooks_router_output(
    webhooks_31: Path, snapshot: SnapshotAssertion
) -> None:
    """With webhooks.generate=True, the router file includes a webhooks router variable."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(webhooks_31),
            output=OutputConfig(models="src/generated/models", routers=tmp),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
            webhooks=WebhooksConfig(generate=True),
        )
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "subscriptions.py")
        assert "webhooks = APIRouter" in src
        assert "@webhooks.post" in src
        assert "on_subscription_event" in src
        assert src == snapshot(name="subscriptions_router_webhooks")


def test_generate_webhooks_disabled_no_webhooks_router(webhooks_31: Path) -> None:
    """With webhooks.generate=False (default), no webhooks router is generated."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(webhooks_31), tmp)
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "subscriptions.py")
        assert "webhooks = APIRouter" not in src


def test_generate_webhooks_init_re_exports_webhooks_router(
    webhooks_31: Path, snapshot: SnapshotAssertion
) -> None:
    """With webhooks.generate=True, __init__.py re-exports the webhooks router variable."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(webhooks_31),
            output=OutputConfig(models="src/generated/models", routers=tmp),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
            webhooks=WebhooksConfig(generate=True),
        )
        RouterGenerator(cfg).generate()

        init_src = _read(Path(tmp) / "__init__.py")
        assert (
            "from .subscriptions import webhooks as subscriptions_webhooks" in init_src
        )
        assert init_src == snapshot(name="webhooks_init")


def test_generate_webhooks_disabled_init_does_not_export_webhooks_router(
    webhooks_31: Path,
) -> None:
    """With webhooks.generate=False (default), __init__.py does NOT re-export webhooks."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(webhooks_31), tmp)
        RouterGenerator(cfg).generate()

        init_src = _read(Path(tmp) / "__init__.py")
        assert "webhooks as subscriptions_webhooks" not in init_src


# ---------------------------------------------------------------------------
# Multiple 2xx response handling
# ---------------------------------------------------------------------------


def test_generate_multi_response_router(
    multi_response: Path, snapshot: SnapshotAssertion
) -> None:
    """Router generated from a spec with multiple 2xx responses per operation."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(multi_response), tmp)
        RouterGenerator(cfg).generate()

        output = Path(tmp)
        assert (output / "items.py").exists()
        assert _read(output / "items.py") == snapshot(
            name="multi_response_items_router"
        )


def test_multi_response_union_in_source(multi_response: Path) -> None:
    """Union type and Optional appear in the generated router source."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(multi_response), tmp)
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "items.py")
        # updateItem: 200 Item + 201 CreatedItem → Union
        assert "Item | CreatedItem" in src
        # deleteItem: 200 Item + 204 empty → Optional
        assert "Item | None" in src
        # createItem: 200+201 same type → just Item (deduplication)
        assert src.count("response_model=Item") >= 1


# ---------------------------------------------------------------------------
# Security scope annotation (T2-C)
# ---------------------------------------------------------------------------


def test_scope_comment_emitted_for_operations_with_scopes(
    secured_scoped: Path,
) -> None:
    """Operations with explicit OAuth2 scopes get a '# Required scopes:' comment."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(secured_scoped), tmp)
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "pets.py")
        # listPets: read:pets only
        assert "# Required scopes: read:pets" in src
        # createPet: read:pets + write:pets
        assert "# Required scopes: read:pets, write:pets" in src


def test_no_scope_comment_for_explicit_no_auth(secured_scoped: Path) -> None:
    """Operations with security: [] (explicit opt-out) must not have a scope comment."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(secured_scoped), tmp)
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "pets.py")
        # deletePet has security: [] — verify its section has no scope comment.
        # The function appears once; scope comment appears only twice (list + create).
        assert src.count("# Required scopes:") == 2


def test_no_scope_comment_when_bearer_with_empty_scopes(secured: Path) -> None:
    """Bearer auth without named scopes produces no '# Required scopes:' line."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(secured), tmp)
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "items.py")
        assert "# Required scopes:" not in src


def test_scope_comment_snapshot(
    secured_scoped: Path, snapshot: SnapshotAssertion
) -> None:
    """Snapshot: router generated from scoped OAuth2 spec."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(str(secured_scoped), tmp)
        RouterGenerator(cfg).generate()

        src = _read(Path(tmp) / "pets.py")
        assert src == snapshot(name="pets_router_scoped_oauth2")


def test_multi_response_bytes_fallback(tmp_path: Path) -> None:
    """When JSON + binary are mixed, Response is used and response_model is omitted."""
    from pyoas.core.parser import SpecParser
    from pyoas.core.resolver import resolve_refs
    from pyoas.fastapi.params import resolve_response_type

    spec_src = """
openapi: "3.0.3"
info: {title: t, version: "1"}
paths:
  /download:
    get:
      operationId: downloadItem
      tags: [items]
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema: {type: object, properties: {id: {type: integer}}}
        '206':
          description: Partial Content
          content:
            application/octet-stream: {}
"""
    spec_file = tmp_path / "bytes_mix.yaml"
    spec_file.write_text(spec_src)

    spec_raw = SpecParser(str(spec_file)).load()
    spec = resolve_refs(spec_raw, str(spec_file))
    op = spec["paths"]["/download"]["get"]
    raw_op = spec_raw["paths"]["/download"]["get"]
    result = resolve_response_type(op, raw_operation=raw_op)
    assert result == "Response"
