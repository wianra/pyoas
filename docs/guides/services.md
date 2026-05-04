# Service Scaffolding

pyoas can scaffold one-time service stub files — the implementation layer that sits behind your FastAPI routers. Service files are written once and never overwritten by default, so you can safely implement them without worrying about losing your work on re-generation.

## Enabling service scaffolding

```yaml
# pyoas.yaml
services:
  generate: true
  output: src/services
  import_path: src.services
```

Then run:

```shell
pyoas generate
# or, standalone:
pyoas scaffold services
```

## Output structure

One file per tag:

```
src/services/
  __init__.py
  pets.py      # PetsService
  users.py     # UsersService
```

## Generated service class

```python
# src/services/pets.py
from generated.models.pets.models import Pet, PetCreate, PetList


class PetsService:
    async def list_pets(
        self,
        *,
        limit: int | None = None,
        status: str | None = None,
    ) -> PetList:
        raise NotImplementedError

    async def create_pet(
        self,
        *,
        body: PetCreate,
    ) -> Pet:
        raise NotImplementedError

    async def get_pet(
        self,
        *,
        pet_id: int,
    ) -> Pet:
        raise NotImplementedError
```

Each method signature matches the parameters of the corresponding router endpoint. All parameters are keyword-only.

## Implementing a service method

Replace `raise NotImplementedError` with your logic:

```python
async def list_pets(
    self,
    *,
    limit: int | None = None,
    status: str | None = None,
) -> PetList:
    query = select(PetRow)
    if status:
        query = query.where(PetRow.status == status)
    if limit:
        query = query.limit(limit)
    rows = await self.db.execute(query)
    return PetList(items=[Pet.model_validate(r) for r in rows])
```

## Overwriting service files

By default, pyoas skips existing service files. To re-scaffold from scratch:

```yaml
services:
  overwrite: true
```

Or use the `--clean` flag:

```shell
pyoas scaffold services --clean
```

!!! warning
    `overwrite: true` replaces your implementation. Only use it intentionally.

## Drift detection

When you add new operations to the spec, pyoas detects that the existing service file is missing methods. Drift warnings are printed to the console (or written to a log file):

```yaml
services:
  drift_log: logs/pyoas-drift.log
```

The service file is not modified; drift warnings tell you which methods to add manually.

## `import_path` and router wiring

The `import_path` setting controls how routers import the service:

```yaml
services:
  import_path: src.services
```

```python
# Generated router
from src.services.pets import PetsService
```

If `import_path` is empty, service imports are omitted from generated routers and endpoints raise `NotImplementedError`.

## Services pattern (for Claude Code skills)

When using `pyoas[claude]`, the `services_pattern` option hints at the service layer architecture:

```yaml
skills:
  services_pattern: repository  # none | repository | domain
```

- `none` — plain service class (default)
- `repository` — service delegates to a repository for data access
- `domain` — service contains domain logic, separate from infrastructure
