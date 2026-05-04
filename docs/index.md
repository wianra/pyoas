# pyoas

**Generate Pydantic v2 models and FastAPI routers from an OpenAPI 3.0/3.1 spec.**

pyoas reads your OpenAPI spec, groups operations by tag, and writes fully-typed Python files you check into source control. Generated files are completely replaced on each run; your hand-written service logic is never touched.

## What pyoas generates

=== "Models"

    ```python
    # src/generated/models/pets/models.py
    from pydantic import BaseModel, Field
    from typing import Literal

    class Pet(BaseModel):
        id: int
        name: str
        status: Literal["available", "pending", "sold"] | None = None

    class PetCreate(BaseModel):
        model_config = ConfigDict(extra="forbid")
        name: str
        status: Literal["available", "pending", "sold"] | None = None
    ```

=== "Routers"

    ```python
    # src/generated/routers/pets/router.py
    from fastapi import APIRouter, Depends, HTTPException
    from .models import Pet, PetCreate, PetList

    router = APIRouter(prefix="/pets", tags=["pets"])

    @router.get("", response_model=PetList)
    async def list_pets(
        service: PetsService = Depends(get_pets_service),
    ) -> PetList:
        return await service.list_pets()

    @router.post("", response_model=Pet, status_code=201)
    async def create_pet(
        body: PetCreate,
        service: PetsService = Depends(get_pets_service),
    ) -> Pet:
        return await service.create_pet(body=body)
    ```

=== "Service stubs"

    ```python
    # src/services/pets.py  (scaffolded once, yours to implement)
    class PetsService:
        async def list_pets(self) -> PetList:
            raise NotImplementedError

        async def create_pet(self, *, body: PetCreate) -> Pet:
            raise NotImplementedError
    ```

=== "Test stubs"

    ```python
    # tests/generated/test_pets.py  (scaffolded, yours to fill in)
    class TestListPets:
        def test_endpoint_exists(self, client):
            resp = client.get("/pets")
            assert resp.status_code not in (404, 405)

        def test_success(self, client, mock_service):
            mock_service.list_pets.return_value = make_pet_list()
            resp = client.get("/pets")
            assert resp.status_code == 200
    ```

## Feature highlights

- **OpenAPI 3.0 and 3.1** — full `$ref` resolution, discriminated unions, generics, inline schemas
- **Pydantic v2** — field constraints (`minLength`, `ge`, `pattern`, …), `Literal` enums, `Annotated` types, snake_case aliases
- **FastAPI routers** — typed parameters (path, query, header, cookie, body), correct status codes, dependency injection wiring
- **Scaffolding** — one-time service stubs, pytest test files with factories, dependency injection boilerplate
- **Custom templates** — override any Jinja2 template with your own
- **Watch mode** — `pyoas watch` re-generates on spec save
- **Diff mode** — `pyoas diff` exits non-zero if any file would change (CI-friendly)
- **Claude Code skills** — optional `.claude/commands/` files for AI-assisted implementation

## Packages

| Package | Install | Purpose |
|---|---|---|
| `pyoas` | `uv add pyoas` | Spec loading, config, CLI, Jinja2 renderer, Pydantic v2 model generation |
| `pyoas[fastapi]` | `uv add pyoas[fastapi]` | FastAPI router + scaffold generation (adds FastAPI dependency) |
| `pyoas[claude]` | `uv add "pyoas[claude]"` | Claude Code skill generation (optional) |

`pyoas[fastapi]` and `pyoas[claude]` both extend the base `pyoas` package.

## Get started

```shell
uv add pyoas[fastapi]
pyoas init openapi.yaml
pyoas generate
```

See the [Quickstart](quickstart.md) for a step-by-step walkthrough.
