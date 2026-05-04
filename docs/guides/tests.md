# Test Scaffolding

pyoas scaffolds pytest test files for your generated endpoints. New test classes are appended to existing files — your hand-written tests are never removed.

## Enabling test scaffolding

```yaml
# pyoas.yaml
tests:
  generate: true
  output: tests/generated
  not_found_exception: "HTTPException(status_code=404, detail='Not found')"
```

Then run:

```shell
pyoas generate
# or, standalone:
pyoas scaffold tests
```

## Output structure

```
tests/generated/
  conftest.py      # shared fixtures and model factories
  test_pets.py     # tests for the pets tag
  test_users.py    # tests for the users tag
```

## conftest.py — factories and fixtures

The shared `conftest.py` is generated with:

- **Model factories** (`make_pet()`, `make_pet_list()`, …) built with [polyfactory](https://github.com/litestar-org/polyfactory) — each returns a valid instance of the model with random data
- **`client` fixture** — a `TestClient` (from httpx) wired to a FastAPI app with all generated routers
- **`mock_service` fixture** — a `MagicMock` of the service class, pre-patched into the router's dependency

```python
# Example conftest.py (generated)
import pytest
from fastapi.testclient import TestClient
from polyfactory.factories.pydantic_factory import ModelFactory
from unittest.mock import MagicMock, patch

from src.generated.models.pets.models import Pet, PetCreate, PetList
from src.generated.routers import pets_router
from src.services.pets import PetsService

class PetFactory(ModelFactory):
    __model__ = Pet

class PetListFactory(ModelFactory):
    __model__ = PetList

def make_pet(**kwargs) -> Pet:
    return PetFactory.build(**kwargs)

def make_pet_list(**kwargs) -> PetList:
    return PetListFactory.build(**kwargs)

@pytest.fixture
def mock_service():
    mock = MagicMock(spec=PetsService)
    with patch("src.generated.routers.pets.router.get_pets_service", return_value=mock):
        yield mock

@pytest.fixture
def client():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(pets_router)
    return TestClient(app)
```

## Test class structure

Each endpoint gets its own test class:

```python
class TestListPets:
    """Tests for GET /pets"""

    def test_endpoint_exists(self, client):
        resp = client.get("/pets")
        assert resp.status_code not in (404, 405)

    def test_success(self, client, mock_service):
        mock_service.list_pets.return_value = make_pet_list()
        resp = client.get("/pets")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data

    def test_not_found(self, client, mock_service):
        mock_service.list_pets.side_effect = HTTPException(status_code=404, detail="Not found")
        resp = client.get("/pets")
        assert resp.status_code == 404
```

### Validation tests

For endpoints with constrained parameters, pyoas generates validation test stubs:

```python
    def test_limit_exceeds_maximum(self, client):
        resp = client.get("/pets", params={"limit": 101})
        assert resp.status_code == 422

    def test_name_too_short(self, client):
        resp = client.post("/pets", json={"name": ""})
        assert resp.status_code == 422
```

## Appending vs. overwriting

By default, pyoas appends new test classes to existing files. If a test class for an operation already exists, it is not duplicated. This means you can safely add operations to your spec and re-run scaffolding without losing existing tests.

To overwrite completely:

```yaml
tests:
  overwrite: true
```

## `not_found_exception`

Controls the exception raised in `test_not_found` stubs:

```yaml
tests:
  not_found_exception: "HTTPException(status_code=404, detail='Not found')"
```

If `null`, `test_not_found` stubs are generated with a `pytest.skip("configure not_found_exception")` placeholder.

## Running the tests

```shell
uv run pytest tests/generated/
```

Most tests will initially fail with `NotImplementedError` (from the service stubs) or `pytest.skip` markers. Implement the service methods to make them pass.

## Service test scaffolding

In addition to endpoint tests, pyoas can scaffold integration tests for the service layer directly:

```shell
pyoas scaffold tests  # endpoint tests
# service tests are generated alongside if services.generate: true
```

Service tests mock the database/repository layer and test the service methods in isolation.
