# Router Generation

pyoas generates FastAPI `APIRouter` files from OpenAPI path items. One router file is created per tag.

## Running router generation

```shell
pyoas fastapi                    # generate routers only
pyoas generate                   # generate models + routers + scaffolding
pyoas fastapi --tags pets        # limit to specific tags
pyoas fastapi --clean            # purge output directory first
```

## Output structure

```
src/generated/routers/
  __init__.py        # re-exports all routers
  pets/
    __init__.py
    router.py        # APIRouter for the pets tag
  users/
    __init__.py
    router.py
```

The root `__init__.py` re-exports each router:

```python
from .pets.router import router as pets_router
from .users.router import router as users_router

__all__ = ["pets_router", "users_router"]
```

## Wiring into FastAPI

```python
from fastapi import FastAPI
from src.generated.routers import pets_router, users_router

app = FastAPI()
app.include_router(pets_router)
app.include_router(users_router)
```

## Endpoint functions

Each OpenAPI operation becomes an async endpoint function. The function name is derived from the HTTP method and path:

| Method | Path | Function name |
|---|---|---|
| `GET` | `/pets` | `list_pets` |
| `POST` | `/pets` | `create_pet` |
| `GET` | `/pets/{petId}` | `get_pets_pet_id` |
| `PUT` | `/pets/{petId}` | `update_pets_pet_id` |
| `DELETE` | `/pets/{petId}` | `delete_pets_pet_id` |

If the operation has an `operationId`, that is used instead (converted to snake_case).

## Parameters

Parameters in `path`, `query`, `header`, and `cookie` locations are mapped to typed function arguments:

```yaml
parameters:
  - name: petId
    in: path
    required: true
    schema:
      type: integer
  - name: status
    in: query
    schema:
      type: string
      enum: [available, pending, sold]
  - name: X-Api-Key
    in: header
    required: true
    schema:
      type: string
```

```python
@router.get("/{pet_id}")
async def get_pet(
    pet_id: int,                            # path
    status: Literal["available", "pending", "sold"] | None = None,  # query
    x_api_key: Annotated[str, Header()],    # header
    service: PetsService = Depends(get_pets_service),
) -> Pet:
    ...
```

### Parameter defaults

- **Required parameters** → no default (positional)
- **Optional parameters** → `= None`
- **Parameters with a default value in the spec** → that value as the Python default

## Request bodies

`application/json` request bodies map to a typed `body` parameter:

```python
@router.post("")
async def create_pet(
    body: PetCreate,
    service: PetsService = Depends(get_pets_service),
) -> Pet:
    ...
```

### Form uploads

`multipart/form-data` bodies map to `Form` and `UploadFile` parameters:

```python
@router.post("/upload")
async def upload_file(
    file: UploadFile,
    name: Annotated[str, Form()],
    service: PetsService = Depends(get_pets_service),
) -> UploadResponse:
    ...
```

## Response types

The response type is derived from the first `2xx` response body schema.

```yaml
responses:
  "201":
    content:
      application/json:
        schema:
          $ref: "#/components/schemas/Pet"
```

```python
@router.post("", response_model=Pet, status_code=201)
async def create_pet(...) -> Pet:
    ...
```

If the response has no body (e.g. `204 No Content`), the return type is `None` and no `response_model` is set.

## Service layer integration

When `services.generate: true` and `services.import_path` is set, generated routers wire in the service via a dependency:

```python
# src/generated/routers/pets/router.py
from src.services.pets import PetsService

def get_pets_service() -> PetsService:
    return PetsService()

@router.get("")
async def list_pets(
    service: PetsService = Depends(get_pets_service),
) -> PetList:
    return await service.list_pets()
```

The service is injected via `Depends`, keeping business logic out of the router.

## Security

Operations with `security` requirements get an auth dependency injected:

```python
@router.get("/me", dependencies=[Depends(require_auth)])
async def get_current_user(
    auth: AuthContext = Depends(get_auth_context),
    service: UsersService = Depends(get_users_service),
) -> User:
    return await service.get_current_user(auth=auth)
```

The `require_auth` and `get_auth_context` functions come from the scaffolded `src/dependencies/auth.py`. See the [Dependency Injection guide](dependencies.md).

## Response model options

Control FastAPI's response serialization globally:

```yaml
router:
  response_model_exclude_none: true    # omit None fields from responses
  response_model_exclude_unset: true   # omit unset fields from responses
```

This adds the corresponding kwargs to every `@router.<method>` decorator.

## Router prefix

The `APIRouter` prefix is derived from the first path segment of the tag's operations. For a tag `pets` with operations on `/pets` and `/pets/{id}`, the prefix is `/pets`.

## Generated endpoint body

Generated endpoint bodies delegate to the service:

```python
return await service.list_pets(limit=limit, status=status)
```

If no service is configured, the body raises `NotImplementedError`.
