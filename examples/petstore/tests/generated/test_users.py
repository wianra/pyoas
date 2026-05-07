# Scaffolded by pyoas — safe to edit; won't be overwritten unless tests.overwrite: true.
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.users import UsersService, get_users_service
from tests.generated.conftest import make_user

from generated.routers.users import router as users_router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(users_router)
    return TestClient(app)


@pytest.fixture
def mock_service() -> AsyncMock:
    """Replace the real service with a mock — override dep before each test."""
    return AsyncMock(spec=UsersService)


@pytest.fixture
def client_with_mock(mock_service: AsyncMock) -> TestClient:
    """TestClient with the service dependency wired to mock_service."""
    app = FastAPI()
    app.include_router(users_router)
    app.dependency_overrides[get_users_service] = lambda: mock_service
    return TestClient(app)


class TestCreateUser:
    """Tests for POST /users"""

    def test_endpoint_exists(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Verify endpoint responds (not 404/405)."""
        mock_service.create_user.return_value = make_user()
        response = client_with_mock.post("/users")
        assert response.status_code not in (404, 405)

    def test_validation_error(self, client: TestClient) -> None:
        """Verify validation rejects missing required input (expects 422)."""
        response = client.post("/users")
        assert response.status_code == 422

    def test_missing_required_field(self, client: TestClient) -> None:
        """Verify validation rejects body missing required fields (expects 422)."""
        response = client.post("/users", json={})
        assert response.status_code == 422

    def test_success(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Happy path — POST /users → 201 User."""
        mock_service.create_user.return_value = make_user()
        response = client_with_mock.post(
            "/users", json={"username": "example", "email": "example"}
        )
        assert response.status_code == 201


class TestGetUser:
    """Tests for GET /users/{username}"""

    def test_endpoint_exists(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Verify endpoint responds (not 404/405)."""
        mock_service.get_user.return_value = make_user()
        response = client_with_mock.get("/users/example")
        assert response.status_code not in (404, 405)

    def test_success(
        self, client_with_mock: TestClient, mock_service: AsyncMock
    ) -> None:
        """Happy path — GET /users/{username} → 200 User."""
        mock_service.get_user.return_value = make_user()
        response = client_with_mock.get("/users/example")
        assert response.status_code == 200
