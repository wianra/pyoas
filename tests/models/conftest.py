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
def discriminated(fixtures_dir: Path) -> Path:
    return fixtures_dir / "discriminated.yaml"


@pytest.fixture
def generic_paginated(fixtures_dir: Path) -> Path:
    return fixtures_dir / "generic_paginated.yaml"


@pytest.fixture
def generic_paginated_no_trailing(fixtures_dir: Path) -> Path:
    return fixtures_dir / "generic_paginated_no_trailing.yaml"


@pytest.fixture
def generic_paginated_list_param(fixtures_dir: Path) -> Path:
    return fixtures_dir / "generic_paginated_list_param.yaml"


@pytest.fixture
def read_write(fixtures_dir: Path) -> Path:
    return fixtures_dir / "read_write.yaml"


@pytest.fixture
def inline_schemas(fixtures_dir: Path) -> Path:
    return fixtures_dir / "inline_schemas.yaml"


@pytest.fixture
def component_enums(fixtures_dir: Path) -> Path:
    return fixtures_dir / "component_enums.yaml"


@pytest.fixture
def deprecated_fields(fixtures_dir: Path) -> Path:
    return fixtures_dir / "deprecated_fields.yaml"


@pytest.fixture
def webhooks_31(fixtures_dir: Path) -> Path:
    return fixtures_dir / "webhooks_3.1.yaml"


@pytest.fixture
def allof_inheritance(fixtures_dir: Path) -> Path:
    return fixtures_dir / "allof_inheritance.yaml"


@pytest.fixture
def circular_ref(fixtures_dir: Path) -> Path:
    return fixtures_dir / "circular_ref.yaml"


@pytest.fixture
def unique_items(fixtures_dir: Path) -> Path:
    return fixtures_dir / "unique_items.yaml"


@pytest.fixture
def inline_defs_31(fixtures_dir: Path) -> Path:
    return fixtures_dir / "inline_defs_3.1.yaml"
