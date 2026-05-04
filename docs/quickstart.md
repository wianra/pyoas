# Quickstart

This guide walks through generating models and routers for a simple pets API.

## 1. Install

```shell
uv add pyoas[fastapi]
```

## 2. Create an OpenAPI spec

Save this as `openapi.yaml`:

```yaml
openapi: "3.0.3"
info:
  title: Pets API
  version: "1.0.0"
paths:
  /pets:
    get:
      summary: List pets
      operationId: listPets
      tags: [pets]
      parameters:
        - name: limit
          in: query
          schema:
            type: integer
            maximum: 100
      responses:
        "200":
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/PetList"
    post:
      summary: Create a pet
      operationId: createPet
      tags: [pets]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/PetCreate"
      responses:
        "201":
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Pet"
  /pets/{petId}:
    get:
      summary: Get a pet
      operationId: getPet
      tags: [pets]
      parameters:
        - name: petId
          in: path
          required: true
          schema:
            type: integer
      responses:
        "200":
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Pet"
components:
  schemas:
    Pet:
      type: object
      required: [id, name]
      properties:
        id:
          type: integer
        name:
          type: string
        status:
          type: string
          enum: [available, pending, sold]
    PetCreate:
      type: object
      required: [name]
      properties:
        name:
          type: string
        status:
          type: string
          enum: [available, pending, sold]
    PetList:
      type: object
      required: [items]
      properties:
        items:
          type: array
          items:
            $ref: "#/components/schemas/Pet"
```

## 3. Create a config

```shell
pyoas init openapi.yaml
```

This writes `pyoas.yaml`:

```yaml
spec: openapi.yaml
output:
  models: src/generated/models
  routers: src/generated/routers
```

## 4. Generate

```shell
pyoas generate
```

pyoas writes:

```
src/generated/
  models/
    __init__.py
    pets/
      __init__.py
      models.py     # Pet, PetCreate, PetList
  routers/
    __init__.py
    pets/
      __init__.py
      router.py     # APIRouter with list_pets, create_pet, get_pet
```

## 5. Wire into FastAPI

```python
# main.py
from fastapi import FastAPI
from src.generated.routers import pets_router

app = FastAPI()
app.include_router(pets_router)
```

## 6. (Optional) Scaffold services and tests

Add to `pyoas.yaml`:

```yaml
services:
  generate: true
  output: src/services
  import_path: src.services

tests:
  generate: true
  output: tests/generated
  not_found_exception: "HTTPException(status_code=404, detail='Not found')"
```

Then run:

```shell
pyoas scaffold services
pyoas scaffold tests
```

Or just re-run `pyoas generate` — scaffolding happens automatically when `generate: true`.

This creates:

```
src/services/
  pets.py          # PetsService with async method stubs

tests/generated/
  conftest.py      # make_pet(), make_pet_list() factories
  test_pets.py     # TestListPets, TestCreatePet, TestGetPet
```

Implement the service methods and run your tests:

```shell
uv run pytest tests/generated/
```

## Next steps

- [Configuration reference](configuration.md) — all `pyoas.yaml` options
- [Model generation guide](guides/models.md) — field types, constraints, generics
- [Router generation guide](guides/routers.md) — parameters, auth, response types
- [CLI reference](cli.md) — all commands and flags
