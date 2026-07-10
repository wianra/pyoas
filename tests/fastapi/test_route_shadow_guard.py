"""
Tests for the generated route-shadowing guard (issue #1).

pyoas emits ``test_no_shadowed_routes.py`` into every scaffolded test tree. It
walks the assembled route table and fails if a route is unreachable behind an
earlier, less-specific one — the residual case the append-only scaffolder can't
reorder away. These tests exercise the *generated* algorithm directly by
rendering the template and running its ``find_shadowed_routes`` against real
FastAPI routes registered in a controlled order.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI
from starlette.routing import Route

from pyoas.core.config import (
    Config,
    FieldsConfig,
    FormatConfig,
    OutputConfig,
    TestsConfig,
)
from pyoas.core.renderer import Renderer
from pyoas.fastapi.testscaffold import (  # type: ignore[attr-defined]
    _DEFAULT_TEMPLATES,
    TestScaffolder,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
PETSTORE = FIXTURES / "petstore_3.0.yaml"


def _load_find_shadowed_routes() -> Callable[[list[Route]], list[str]]:
    """Render the guard template and return its ``find_shadowed_routes``."""
    src = Renderer(default_templates_dir=_DEFAULT_TEMPLATES).render(
        "test_no_shadowed_routes.py.jinja2", {"router_import_path": "unused.pkg"}
    )
    ns: dict[str, Any] = {}
    exec(compile(src, "test_no_shadowed_routes.py", "exec"), ns)
    return ns["find_shadowed_routes"]


def _routes(*specs: tuple[str, str]) -> list[Route]:
    """Register ``(method, path)`` pairs in order and return the route table.

    Each route lives in its own APIRouter so registration order is exactly the
    argument order, bypassing the generator's specificity sort.
    """
    app = FastAPI(openapi_url=None)
    for method, path in specs:
        router = APIRouter()
        router.add_api_route(path, lambda: None, methods=[method])
        app.include_router(router)
    return [r for r in app.routes if isinstance(r, Route)]


def test_detects_literal_shadowed_by_parametric() -> None:
    """A literal registered after a parametric sibling is flagged (the bug)."""
    find_shadowed_routes = _load_find_shadowed_routes()
    findings = find_shadowed_routes(
        _routes(("GET", "/items/{item_id}"), ("GET", "/items/export"))
    )
    assert len(findings) == 1
    assert "/items/export" in findings[0]
    assert "/items/{item_id}" in findings[0]


def test_no_finding_when_literal_registered_first() -> None:
    """Correct ordering (literal before parametric) is not flagged."""
    find_shadowed_routes = _load_find_shadowed_routes()
    findings = find_shadowed_routes(
        _routes(("GET", "/items/export"), ("GET", "/items/{item_id}"))
    )
    assert findings == []


def test_probe_does_not_collide_with_real_literal() -> None:
    """A parametric route after a real literal sibling is not a false positive.

    ``/items/{item_id}`` is legitimately more general than the earlier
    ``/items/sample`` and only its ``sample`` value is captured — that is the
    intended behaviour, not a shadow.
    """
    find_shadowed_routes = _load_find_shadowed_routes()
    findings = find_shadowed_routes(
        _routes(("GET", "/items/sample"), ("GET", "/items/{item_id}"))
    )
    assert findings == []


def test_disjoint_methods_never_shadow() -> None:
    """Routes on the same path but different methods do not shadow each other."""
    find_shadowed_routes = _load_find_shadowed_routes()
    findings = find_shadowed_routes(
        _routes(("GET", "/items/{item_id}"), ("POST", "/items/export"))
    )
    assert findings == []


def test_literal_suffix_action_route_not_flagged_when_ordered_first() -> None:
    """``/items/{id}:cancel`` before bare ``/items/{id}`` is reachable."""
    find_shadowed_routes = _load_find_shadowed_routes()
    findings = find_shadowed_routes(
        _routes(("POST", "/items/{item_id}:cancel"), ("POST", "/items/{item_id}"))
    )
    assert findings == []


def test_scaffolder_writes_guard_file() -> None:
    """TestScaffolder emits the shadow-guard test into the tree."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            spec=str(PETSTORE),
            output=OutputConfig(
                models="src/generated/models", routers="src/generated/routers"
            ),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
            tests=TestsConfig(generate=True, output=tmp, overwrite=True),
        )
        TestScaffolder(cfg).scaffold()
        guard = Path(tmp) / "test_no_shadowed_routes.py"
        assert guard.exists()
        text = guard.read_text(encoding="utf-8")
        assert "def test_no_shadowed_routes(" in text
        assert "def find_shadowed_routes(" in text
