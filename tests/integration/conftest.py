"""Integration test configuration.

Tests in this directory are marked ``@pytest.mark.integration`` and are
skipped by default.  Run them with::

    pytest tests/integration/ --run-integration -v

Specs are downloaded separately::

    python tests/integration/download_specs.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

SPECS_DIR = Path(__file__).parent / "specs"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests against real-world OpenAPI specs.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-integration"):
        return
    skip_marker = pytest.mark.skip(reason="Pass --run-integration to run this test")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)


def _spec_fixture(filename: str):
    """Factory that creates a session-scoped fixture for a single spec file."""

    @pytest.fixture(scope="session")
    def _fixture() -> Path:
        path = SPECS_DIR / filename
        if not path.exists():
            pytest.skip(
                f"Spec not found: {path}\n"
                "Run: python tests/integration/download_specs.py"
            )
        return path

    _fixture.__name__ = filename.replace(".", "_").replace("-", "_")
    return _fixture


github_spec = _spec_fixture("github.json")
stripe_spec = _spec_fixture("stripe.yaml")
openai_spec = _spec_fixture("openai.yaml")
kubernetes_spec = _spec_fixture("kubernetes.json")
