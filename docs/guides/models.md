# Model Generation

pyoas generates Pydantic v2 models from OpenAPI `components/schemas`. Models are grouped by tag based on which operations reference them.

## Running model generation

```shell
pyoas models                    # generate models only
pyoas generate                  # generate models + routers + scaffolding
pyoas models --tags pets,users  # limit to specific tags
pyoas models --clean            # purge output directory first
```

## Output structure

```
src/generated/models/
  __init__.py
  pets/
    __init__.py
    models.py     # schemas referenced only by pets operations
  users/
    __init__.py
    models.py     # schemas referenced only by users operations
  shared/
    __init__.py
    models.py     # schemas referenced by more than one tag
```

The top-level `__init__.py` re-exports everything from all tag modules.

## Type mapping

| OpenAPI type | Python type |
|---|---|
| `string` | `str` |
| `string` + `format: date` | `datetime.date` |
| `string` + `format: date-time` | `datetime.datetime` |
| `string` + `format: uuid` | `uuid.UUID` |
| `string` + `format: binary` | `bytes` |
| `integer` | `int` |
| `number` | `float` |
| `boolean` | `bool` |
| `array` of T | `list[T]` |
| `object` (no properties) | `dict[str, Any]` |
| `nullable: true` (OAS 3.0) | `T \| None` |
| `type: ["T", "null"]` (OAS 3.1) | `T \| None` |

## Enums

By default (`enums_as_literals: true`), string and integer enums are rendered as `Literal` types:

```python
status: Literal["available", "pending", "sold"] | None = None
```

Set `enums_as_literals: false` to generate `StrEnum`/`IntEnum` subclasses instead:

```python
class PetStatus(StrEnum):
    available = "available"
    pending = "pending"
    sold = "sold"
```

Component-level enums (defined in `components/schemas`) are always generated as classes so they can be referenced by name.

## Field constraints

OpenAPI constraints map to Pydantic `Field` kwargs via `Annotated`:

| OpenAPI | Pydantic |
|---|---|
| `minLength` / `maxLength` | `min_length` / `max_length` |
| `minimum` / `maximum` | `ge` / `le` |
| `exclusiveMinimum` / `exclusiveMaximum` | `gt` / `lt` |
| `pattern` | `pattern` |
| `minItems` / `maxItems` | `min_length` / `max_length` |
| `multipleOf` | `multiple_of` |

Example:

```yaml
# OpenAPI
properties:
  name:
    type: string
    minLength: 1
    maxLength: 100
  age:
    type: integer
    minimum: 0
    maximum: 150
```

```python
# Generated
name: Annotated[str, Field(min_length=1, max_length=100)]
age: Annotated[int, Field(ge=0, le=150)] | None = None
```

## snake_case conversion

When `fields.snake_case: true` (default), camelCase field names are converted to snake_case with an `alias`:

```python
class Pet(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pet_id: int = Field(alias="petId")
    created_at: datetime = Field(alias="createdAt")
    owner_name: str | None = Field(None, alias="ownerName")
```

Disable with `fields.snake_case: false` to keep original names.

## Composition (allOf / anyOf / oneOf)

**`allOf` with multiple entries** → class inheritance:

```yaml
Dog:
  allOf:
    - $ref: "#/components/schemas/Pet"
    - type: object
      properties:
        breed:
          type: string
```

```python
class Dog(Pet):
    breed: str | None = None
```

**`allOf` with one entry** → unwrapped (treated as a reference):

```python
# allOf: [$ref: Pet]  →  just Pet
```

**`anyOf` / `oneOf`** → union type:

```python
# anyOf: [Cat, Dog]
pet: Cat | Dog
```

## Discriminated unions

OpenAPI `discriminator` objects are supported. pyoas generates Pydantic annotated discriminators:

```yaml
Pet:
  oneOf:
    - $ref: "#/components/schemas/Cat"
    - $ref: "#/components/schemas/Dog"
  discriminator:
    propertyName: petType
```

```python
Pet = Annotated[
    Cat | Dog,
    Field(discriminator="pet_type"),
]
```

## Generic types

pyoas detects generic instantiation patterns. If your spec has titles like `Paginated[DriverListItem]` or component keys like `Paginated_DriverListItem_`, it generates:

```python
T = TypeVar("T")

class Paginated(BaseModel, Generic[T]):
    items: list[T]
    total: int

PaginatedDriverListItem = Paginated[DriverListItem]
```

This keeps generated code DRY when you have many paginated response types.

## Request vs. response classification

pyoas classifies each schema as either *request-only* or *response/shared*:

- **Request-only**: appears only in request bodies, never in responses → `ConfigDict(extra="forbid")`
- **Response/shared**: appears in responses or in both → `ConfigDict(extra="ignore")`

The `extra` values can be changed via `model_config.extra` and `model_config.request_extra` in your config.

## Read-only and write-only fields

OpenAPI `readOnly: true` fields are excluded from request-body schemas; `writeOnly: true` fields are excluded from response schemas. pyoas generates separate model variants automatically.

## Unreferenced schemas

By default, schemas in `components/schemas` that are not referenced by any operation are skipped. Enable them with:

```yaml
model_config:
  include_unreferenced: true
```

## Frozen models

```yaml
model_config:
  frozen: true
```

Adds `frozen=True` to all `ConfigDict` entries, making models hashable and immutable.
