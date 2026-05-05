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
def generic_paginated(fixtures_dir: Path) -> Path:
    return fixtures_dir / "generic_paginated.yaml"


@pytest.fixture
def optional_before_required(fixtures_dir: Path) -> Path:
    return fixtures_dir / "optional_before_required.yaml"


@pytest.fixture
def read_write(fixtures_dir: Path) -> Path:
    return fixtures_dir / "read_write.yaml"


@pytest.fixture
def no_tags_paginated(fixtures_dir: Path) -> Path:
    return fixtures_dir / "no_tags_paginated.yaml"


@pytest.fixture
def body_field_constraints(fixtures_dir: Path) -> Path:
    return fixtures_dir / "body_field_constraints.yaml"


@pytest.fixture
def form_upload(fixtures_dir: Path) -> Path:
    return fixtures_dir / "form_upload.yaml"


@pytest.fixture
def inline_schemas(fixtures_dir: Path) -> Path:
    return fixtures_dir / "inline_schemas.yaml"


@pytest.fixture
def secured(fixtures_dir: Path) -> Path:
    return fixtures_dir / "secured.yaml"


@pytest.fixture
def webhooks_31(fixtures_dir: Path) -> Path:
    return fixtures_dir / "webhooks_3.1.yaml"


@pytest.fixture
def multi_response(fixtures_dir: Path) -> Path:
    return fixtures_dir / "multi_response.yaml"
