# Dependency Injection Scaffolding

pyoas can scaffold a FastAPI dependency module for authentication and auth context. This is a one-time scaffold — the generated file is yours to implement.

## Enabling dependency scaffolding

```yaml
# pyoas.yaml
dependencies:
  generate: true
  output: src/dependencies
  import_path: src.dependencies
```

Then run:

```shell
pyoas generate
# or, standalone:
pyoas scaffold dependencies
```

## Output

```
src/dependencies/
  __init__.py
  auth.py
```

## Generated `auth.py`

```python
# src/dependencies/auth.py  (scaffolded once)
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


class AuthContext:
    """Parsed, validated auth context — add fields as needed."""
    user_id: str
    scopes: list[str]


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> AuthContext:
    """
    Validate the bearer token and return an AuthContext.
    Raise HTTPException(401) for missing/invalid tokens.
    """
    raise NotImplementedError


async def require_auth(
    auth: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """Shorthand dependency: raises 401 if not authenticated."""
    return auth
```

## Implementing auth

Replace `raise NotImplementedError` with your validation logic:

```python
import jwt  # PyJWT

async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> AuthContext:
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return AuthContext(user_id=payload["sub"], scopes=payload.get("scopes", []))
```

## Router integration

Operations with a `security` requirement in the OpenAPI spec automatically receive auth dependencies in the generated router:

```python
# src/generated/routers/users/router.py
from src.dependencies.auth import AuthContext, get_auth_context, require_auth

@router.get("/me", dependencies=[Depends(require_auth)])
async def get_current_user(
    auth: AuthContext = Depends(get_auth_context),
    service: UsersService = Depends(get_users_service),
) -> User:
    return await service.get_current_user(auth=auth)
```

## `import_path` setting

The `import_path` setting controls how routers import the dependency module:

```yaml
dependencies:
  import_path: src.dependencies
```

```python
from src.dependencies.auth import AuthContext, get_auth_context, require_auth
```

## Overwriting

By default the dependency file is never overwritten. To re-scaffold:

```yaml
dependencies:
  overwrite: true
```
