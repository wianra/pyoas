# Scaffolded by pyoas — safe to edit; won't be overwritten unless tests.overwrite: true.
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from services.pets import PetsService, get_pets_service
from tests.generated.conftest import make_pet, make_pet_list

from generated.routers.pets import router as pets_router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(pets_router)
    return TestClient(app)


@pytest.fixture
def mock_service() -> AsyncMock:
    """Replace the real service with a mock — override dep before each test."""
    return AsyncMock(spec=PetsService)


@pytest.fixture
def client_with_mock(mock_service: AsyncMock) -> TestClient:
    """TestClient with the service dependency wired to mock_service."""
    app = FastAPI()
    app.include_router(pets_router)
    app.dependency_overrides[get_pets_service] = lambda: mock_service
    return TestClient(app)


class TestListPets:
    """Tests for GET /pets"""

    def test_endpoint_exists(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Verify endpoint responds (not 404/405)."""
        mock_service.list_pets.return_value = make_pet_list()
        response = client_with_mock.get("/pets")
        assert response.status_code not in (404, 405)

    def test_limit_below_minimum(self, client: TestClient) -> None:
        """Verify validation rejects out-of-range limit (expects 422)."""
        response = client.get("/pets", params={"limit": 0})
        assert response.status_code == 422

    def test_limit_above_maximum(self, client: TestClient) -> None:
        """Verify validation rejects out-of-range limit (expects 422)."""
        response = client.get("/pets", params={"limit": 101})
        assert response.status_code == 422

    def test_status_invalid_enum(self, client: TestClient) -> None:
        """Verify validation rejects invalid enum value for status (expects 422)."""
        response = client.get("/pets", params={"status": "__invalid__"})
        assert response.status_code == 422

    def test_success(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Happy path — GET /pets → 200 PetList."""
        mock_service.list_pets.return_value = make_pet_list()
        response = client_with_mock.get("/pets")
        assert response.status_code == 200


class TestCreatePet:
    """Tests for POST /pets"""

    def test_endpoint_exists(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Verify endpoint responds (not 404/405)."""
        mock_service.create_pet.return_value = make_pet()
        response = client_with_mock.post("/pets")
        assert response.status_code not in (404, 405)

    def test_validation_error(self, client: TestClient) -> None:
        """Verify validation rejects missing required input (expects 422)."""
        response = client.post("/pets")
        assert response.status_code == 422

    def test_missing_required_field(self, client: TestClient) -> None:
        """Verify validation rejects body missing required fields (expects 422)."""
        response = client.post("/pets", json={})
        assert response.status_code == 422

    def test_success(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Happy path — POST /pets → 201 Pet."""
        mock_service.create_pet.return_value = make_pet()
        response = client_with_mock.post("/pets", json={"name": "example"})
        assert response.status_code == 201


class TestGetPet:
    """Tests for GET /pets/{petId}"""

    def test_endpoint_exists(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Verify endpoint responds (not 404/405)."""
        mock_service.get_pet.return_value = make_pet()
        response = client_with_mock.get("/pets/1")
        assert response.status_code not in (404, 405)

    def test_invalid_pet_id_type(self, client_with_mock: TestClient) -> None:
        """Verify validation rejects non-integer path parameter (expects 422)."""
        response = client_with_mock.get("/pets/not-an-integer")
        assert response.status_code == 422

    def test_not_found(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Service raises not-found — expect 404."""
        mock_service.get_pet.side_effect = HTTPException(status_code=404)
        response = client_with_mock.get("/pets/1")
        assert response.status_code == 404

    def test_success(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Happy path — GET /pets/{petId} → 200 Pet."""
        mock_service.get_pet.return_value = make_pet()
        response = client_with_mock.get("/pets/1")
        assert response.status_code == 200


class TestUpdatePet:
    """Tests for PATCH /pets/{petId}"""

    def test_endpoint_exists(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Verify endpoint responds (not 404/405)."""
        mock_service.update_pet.return_value = make_pet()
        response = client_with_mock.patch("/pets/1", json={})
        assert response.status_code not in (404, 405)

    def test_validation_error(self, client: TestClient) -> None:
        """Verify validation rejects missing required input (expects 422)."""
        response = client.patch("/pets/1")
        assert response.status_code == 422

    def test_invalid_pet_id_type(self, client_with_mock: TestClient) -> None:
        """Verify validation rejects non-integer path parameter (expects 422)."""
        response = client_with_mock.patch("/pets/not-an-integer")
        assert response.status_code == 422

    def test_not_found(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Service raises not-found — expect 404."""
        mock_service.update_pet.side_effect = HTTPException(status_code=404)
        response = client_with_mock.patch("/pets/1", json={})
        assert response.status_code == 404

    def test_success(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Happy path — PATCH /pets/{petId} → 200 Pet."""
        mock_service.update_pet.return_value = make_pet()
        response = client_with_mock.patch("/pets/1", json={})
        assert response.status_code == 200


class TestDeletePet:
    """Tests for DELETE /pets/{petId}"""

    def test_endpoint_exists(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Verify endpoint responds (not 404/405)."""
        response = client_with_mock.delete("/pets/1")
        assert response.status_code not in (404, 405)

    def test_invalid_pet_id_type(self, client_with_mock: TestClient) -> None:
        """Verify validation rejects non-integer path parameter (expects 422)."""
        response = client_with_mock.delete("/pets/not-an-integer")
        assert response.status_code == 422

    def test_not_found(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Service raises not-found — expect 404."""
        mock_service.delete_pet.side_effect = HTTPException(status_code=404)
        response = client_with_mock.delete("/pets/1")
        assert response.status_code == 404

    def test_success(self, client_with_mock: TestClient) -> None:
        """Happy path — DELETE /pets/{petId} → 204."""
        response = client_with_mock.delete("/pets/1")
        assert response.status_code == 204
