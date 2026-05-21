from pathlib import Path
from unittest import mock

import pytest

from pyoas.core.utils import (
    derive_import_path,
    ensure_intermediate_inits,
    format_docstring,
    format_output,
    generate_function_name,
    to_snake_case,
)


@pytest.mark.parametrize(
    "input_str, expected",
    [
        # Basic camelCase
        ("camelCase", "camel_case"),
        ("getUser", "get_user"),
        # PascalCase
        ("PascalCase", "pascal_case"),
        ("CreateDriverGroup", "create_driver_group"),
        # Acronyms followed by a word — must NOT split each letter individually
        ("getHTTPCode", "get_http_code"),
        ("getHTTPSResponse", "get_https_response"),
        ("parseHTMLPage", "parse_html_page"),
        ("myURLParser", "my_url_parser"),
        # Acronym at the end
        ("getHTTP", "get_http"),
        ("getID", "get_id"),
        # Already snake_case — must be idempotent
        ("snake_case", "snake_case"),
        ("get_user", "get_user"),
        # Mixed
        ("listHTTPSEndpoints", "list_https_endpoints"),
    ],
)
def test_to_snake_case(input_str: str, expected: str) -> None:
    assert to_snake_case(input_str) == expected


@pytest.mark.parametrize(
    "method, path, expected",
    [
        ("get", "/users", "get_users"),
        # {braces} are non-alphanumeric → replaced and squished; the segment is lowercased but not snake_cased
        ("post", "/users/{userId}", "post_users_userid"),
        ("delete", "/orders/{id}/items/{itemId}", "delete_orders_id_items_itemid"),
        # Path that already starts with method
        ("get", "/get-users", "get_users"),
    ],
)
def test_generate_function_name(method: str, path: str, expected: str) -> None:
    assert generate_function_name(method, path) == expected


# ---------------------------------------------------------------------------
# ensure_intermediate_inits
# ---------------------------------------------------------------------------


def test_ensure_intermediate_inits_src_layout_creates_inits(tmp_path: Path) -> None:
    """Intermediate dirs between src/ and output_root get __init__.py; src/ itself does not."""
    models = tmp_path / "src" / "generated" / "models"
    models.mkdir(parents=True)

    ensure_intermediate_inits(models, source_root="src")

    assert (tmp_path / "src" / "generated" / "__init__.py").exists()
    assert not (tmp_path / "src" / "__init__.py").exists()


def test_ensure_intermediate_inits_flat_layout_with_project_root(
    tmp_path: Path,
) -> None:
    """Flat-layout mode (source_root='') stamps dirs up to project_root."""
    services = tmp_path / "app" / "services"
    services.mkdir(parents=True)

    ensure_intermediate_inits(services, source_root="", project_root=tmp_path)

    assert (tmp_path / "app" / "__init__.py").exists()


def test_ensure_intermediate_inits_flat_layout_no_project_root_is_noop(
    tmp_path: Path,
) -> None:
    """Flat-layout with project_root=None returns early without creating any files."""
    services = tmp_path / "app" / "services"
    services.mkdir(parents=True)

    ensure_intermediate_inits(services, source_root="", project_root=None)

    assert not (tmp_path / "app" / "__init__.py").exists()


def test_ensure_intermediate_inits_flat_layout_project_root_not_ancestor_is_noop(
    tmp_path: Path,
) -> None:
    """Flat-layout where project_root is not in the ancestry does nothing."""
    services = tmp_path / "app" / "services"
    services.mkdir(parents=True)
    fake_root = tmp_path / "nonexistent_root"

    ensure_intermediate_inits(services, source_root="", project_root=fake_root)

    assert not (tmp_path / "app" / "__init__.py").exists()


# ---------------------------------------------------------------------------
# format_output
# ---------------------------------------------------------------------------


def test_format_output_calls_ruff(tmp_path: Path) -> None:
    with mock.patch("pyoas.core.utils.subprocess.run") as mock_run:
        format_output(tmp_path)
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "ruff"
    assert "format" in cmd


def test_format_output_ignores_failures(tmp_path: Path) -> None:
    with mock.patch("pyoas.core.utils.subprocess.run", side_effect=FileNotFoundError):
        format_output(tmp_path)  # must not raise


# ---------------------------------------------------------------------------
# format_docstring
# ---------------------------------------------------------------------------


def test_format_docstring_single_line() -> None:
    assert format_docstring("hello") == '    """hello"""'


def test_format_docstring_multi_line_indents_subsequent_lines() -> None:
    out = format_docstring("first\nsecond\nthird")
    assert out == '    """first\n    second\n    third"""'


def test_format_docstring_custom_indent() -> None:
    out = format_docstring("a\nb", indent="        ")
    assert out == '        """a\n        b"""'


def test_format_docstring_strips_trailing_whitespace() -> None:
    """Trailing newlines must not produce a dangling unindented closing line."""
    out = format_docstring("one\ntwo\n")
    assert out == '    """one\n    two"""'


def test_format_docstring_empty_returns_empty_string() -> None:
    assert format_docstring("") == ""
    assert format_docstring("   \n   ") == ""


def test_format_docstring_blank_internal_line_preserved() -> None:
    out = format_docstring("a\n\nb")
    assert out == '    """a\n\n    b"""'


# ---------------------------------------------------------------------------
# derive_import_path with project_root
# ---------------------------------------------------------------------------


def test_derive_import_path_relative_path() -> None:
    assert derive_import_path("app/routers", source_root="") == "app.routers"


def test_derive_import_path_absolute_rebased_to_project_root(tmp_path: Path) -> None:
    """Absolute paths under project_root are rebased before import-path derivation."""
    abs_path = str(tmp_path / "app" / "routers")
    out = derive_import_path(abs_path, source_root="", project_root=str(tmp_path))
    assert out == "app.routers"


def test_derive_import_path_absolute_outside_project_root_falls_back(
    tmp_path: Path,
) -> None:
    """Absolute paths outside project_root keep absolute behavior (no crash)."""
    abs_path = "/elsewhere/app/routers"
    out = derive_import_path(abs_path, source_root="", project_root=str(tmp_path))
    # No crash; uses the absolute path segments since rebase failed.
    assert out.endswith("app.routers")
