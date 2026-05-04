import pytest

from pyoas.core.utils import generate_function_name, to_snake_case


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
