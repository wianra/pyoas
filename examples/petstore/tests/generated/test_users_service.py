# Scaffolded by pyoas — safe to edit; won't be overwritten unless tests.overwrite: true.
from __future__ import annotations

import pytest
from services.users import UsersService


@pytest.fixture
def service() -> UsersService:
    """Construct UsersService with real dependencies.

    Replace pytest.skip with actual construction, e.g.:
        return UsersService(db=your_db_session, repo=your_repo, ...)
    """
    pytest.skip("implement me")


class TestCreateUserService:
    """Service tests for POST /users"""

    def test_creates_resource(self, service: UsersService) -> None:
        """Happy path — verify service returns expected result."""
        pytest.skip("implement me")


class TestGetUserService:
    """Service tests for GET /users/{username}"""

    def test_returns_user(self, service: UsersService) -> None:
        """Happy path — verify service returns expected result."""
        pytest.skip("implement me")
