# Scaffolded by pyoas — safe to edit; won't be overwritten unless tests.overwrite: true.
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from services.store import StoreService, get_store_service
from tests.generated.conftest import make_order

from generated.routers.store import router as store_router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(store_router)
    return TestClient(app)


@pytest.fixture
def mock_service() -> AsyncMock:
    """Replace the real service with a mock — override dep before each test."""
    return AsyncMock(spec=StoreService)


@pytest.fixture
def client_with_mock(mock_service: AsyncMock) -> TestClient:
    """TestClient with the service dependency wired to mock_service."""
    app = FastAPI()
    app.include_router(store_router)
    app.dependency_overrides[get_store_service] = lambda: mock_service
    return TestClient(app)


class TestGetInventory:
    """Tests for GET /store/inventory"""

    def test_endpoint_exists(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Verify endpoint responds (not 404/405)."""
        mock_service.get_inventory.return_value = {}
        response = client_with_mock.get("/store/inventory")
        assert response.status_code not in (404, 405)

    def test_success(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Happy path — GET /store/inventory → 200 dict[str, int]."""
        mock_service.get_inventory.return_value = {}
        response = client_with_mock.get("/store/inventory")
        assert response.status_code == 200


class TestCreateOrder:
    """Tests for POST /store/orders"""

    def test_endpoint_exists(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Verify endpoint responds (not 404/405)."""
        mock_service.create_order.return_value = make_order()
        response = client_with_mock.post("/store/orders")
        assert response.status_code not in (404, 405)

    def test_validation_error(self, client: TestClient) -> None:
        """Verify validation rejects missing required input (expects 422)."""
        response = client.post("/store/orders")
        assert response.status_code == 422

    def test_missing_required_field(self, client: TestClient) -> None:
        """Verify validation rejects body missing required fields (expects 422)."""
        response = client.post("/store/orders", json={})
        assert response.status_code == 422

    def test_pet_id_wrong_type(self, client: TestClient) -> None:
        """Verify validation rejects wrong type for pet_id (expects 422)."""
        response = client.post(
            "/store/orders", json={"pet_id": "not-an-integer", "quantity": 2}
        )
        assert response.status_code == 422

    def test_quantity_below_minimum(self, client: TestClient) -> None:
        """Verify validation rejects quantity below minimum (expects 422)."""
        response = client.post("/store/orders", json={"pet_id": 1, "quantity": 0})
        assert response.status_code == 422

    def test_quantity_above_maximum(self, client: TestClient) -> None:
        """Verify validation rejects quantity above maximum (expects 422)."""
        response = client.post("/store/orders", json={"pet_id": 1, "quantity": 101})
        assert response.status_code == 422

    def test_quantity_wrong_type(self, client: TestClient) -> None:
        """Verify validation rejects wrong type for quantity (expects 422)."""
        response = client.post(
            "/store/orders", json={"pet_id": 1, "quantity": "not-an-integer"}
        )
        assert response.status_code == 422

    def test_success(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Happy path — POST /store/orders → 201 Order."""
        mock_service.create_order.return_value = make_order()
        response = client_with_mock.post(
            "/store/orders", json={"pet_id": 1, "quantity": 2}
        )
        assert response.status_code == 201


class TestGetOrder:
    """Tests for GET /store/orders/{orderId}"""

    def test_endpoint_exists(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Verify endpoint responds (not 404/405)."""
        mock_service.get_order.return_value = make_order()
        response = client_with_mock.get("/store/orders/1")
        assert response.status_code not in (404, 405)

    def test_invalid_order_id_type(self, client_with_mock: TestClient) -> None:
        """Verify validation rejects non-integer path parameter (expects 422)."""
        response = client_with_mock.get("/store/orders/not-an-integer")
        assert response.status_code == 422

    def test_not_found(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Service raises not-found — expect 404."""
        mock_service.get_order.side_effect = HTTPException(status_code=404)
        response = client_with_mock.get("/store/orders/1")
        assert response.status_code == 404

    def test_success(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Happy path — GET /store/orders/{orderId} → 200 Order."""
        mock_service.get_order.return_value = make_order()
        response = client_with_mock.get("/store/orders/1")
        assert response.status_code == 200
