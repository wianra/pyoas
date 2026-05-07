# Scaffolded by pyoas — safe to edit; won't be overwritten unless overwrite: true.
from __future__ import annotations

from fastapi import HTTPException
from generated.models.users import CreateUserRequest, User

# In-memory store — replace with a real database session in production.
_users: dict[str, User] = {}
_next_id = 1


class UsersService:
    async def create_user(
        self,
        *,
        body: CreateUserRequest,
    ) -> User:
        """Create a user account"""
        global _next_id
        if body.username in _users:
            raise HTTPException(
                status_code=409, detail=f"Username '{body.username}' already taken"
            )
        user = User(
            id=_next_id,
            username=body.username,
            email=body.email,
            first_name=body.first_name,
            last_name=body.last_name,
        )
        _users[body.username] = user
        _next_id += 1
        return user

    async def get_user(
        self,
        *,
        username: str,
    ) -> User:
        """Get user by username"""
        user = _users.get(username)
        if user is None:
            raise HTTPException(status_code=404, detail=f"User '{username}' not found")
        return user


async def get_users_service() -> UsersService:
    return UsersService()
