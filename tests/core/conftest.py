from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def petstore_30(fixtures_dir: Path) -> Path:
    return fixtures_dir / "petstore_3.0.yaml"


@pytest.fixture
def petstore_31(fixtures_dir: Path) -> Path:
    return fixtures_dir / "petstore_3.1.yaml"


@pytest.fixture
def multi_tag(fixtures_dir: Path) -> Path:
    return fixtures_dir / "multi_tag.yaml"


@pytest.fixture
def no_tags(fixtures_dir: Path) -> Path:
    return fixtures_dir / "no_tags.yaml"


@pytest.fixture
def webhooks_31(fixtures_dir: Path) -> Path:
    return fixtures_dir / "webhooks_3.1.yaml"
