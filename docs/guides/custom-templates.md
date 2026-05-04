# Custom Templates

pyoas uses Jinja2 templates to render generated files. You can override any built-in template with your own version.

## Enabling custom templates

Point pyoas at a directory containing your overrides:

```yaml
templates:
  models: templates/models    # overrides model templates
  routers: templates/routers  # overrides router templates
```

You only need to include the templates you want to override. Any template not found in your directory falls back to the built-in version.

## Built-in templates

### Model templates (`pyoas`)

| Template | Purpose |
|---|---|
| `model.py.jinja2` | Pydantic class definitions |
| `init.py.jinja2` | `__init__.py` re-exports |

### Router templates (`pyoas[fastapi]`)

| Template | Purpose |
|---|---|
| `router.py.jinja2` | `APIRouter` with endpoint functions |
| `service.py.jinja2` | Service class stubs |
| `test.py.jinja2` | Pytest endpoint test stubs |
| `test_service.py.jinja2` | Service integration test stubs |
| `conftest.py.jinja2` | `conftest.py` with factories and fixtures |
| `init.py.jinja2` | `__init__.py` re-exports |
| `dependency_auth.py.jinja2` | Auth dependency scaffold |

## Template context

### `model.py.jinja2`

| Variable | Type | Description |
|---|---|---|
| `tag` | `str` | Tag name (e.g. `"pets"`) |
| `schemas` | `list[dict]` | Schema render dicts (see below) |
| `model_config` | `dict` | Config values from `pyoas.yaml` |
| `imports` | `list[str]` | Import statements needed |
| `type_vars` | `list[str]` | TypeVar declarations for generics |
| `shared_imports` | `str` | Import path for the shared module |

Each schema dict in `schemas`:

```python
{
    "name": "Pet",           # Class name
    "fields": [...],         # Field dicts
    "bases": ["BaseModel"],  # Base classes
    "config": {...},         # ConfigDict kwargs
    "docstring": "...",      # Optional docstring
    "is_alias": False,       # True for generic type aliases
    "alias_target": "...",   # e.g. "Paginated[Pet]"
}
```

Each field dict:

```python
{
    "name": "pet_id",
    "python_type": "int",
    "required": True,
    "default": None,
    "alias": "petId",
    "description": "...",
    "field_kwargs": {"ge": 0},
}
```

### `router.py.jinja2`

| Variable | Type | Description |
|---|---|---|
| `tag` | `str` | Tag name |
| `operations` | `list[dict]` | Operation render dicts (see below) |
| `models_import_path` | `str` | Import path for models module |
| `service_import_path` | `str` | Import path for service module |
| `service_class_name` | `str` | e.g. `"PetsService"` |
| `service_dep_fn` | `str` | e.g. `"get_pets_service"` |
| `response_model_exclude_none` | `bool` | From `router` config |
| `response_model_exclude_unset` | `bool` | From `router` config |

Each operation dict:

```python
{
    "function_name": "list_pets",
    "method": "get",
    "path": "",              # suffix after router prefix
    "params": [...],         # parameter dicts
    "response_type": "PetList",
    "status_code": 200,
    "has_body": False,
    "requires_auth": False,
    "summary": "List all pets",
}
```

## Example: adding a custom header to all responses

Override `router.py.jinja2`:

```jinja2
{# templates/routers/router.py.jinja2 #}
from fastapi import APIRouter, Depends, Response
...

{% for op in operations %}
@router.{{ op.method }}("{{ op.path }}", ...)
async def {{ op.function_name }}(
    response: Response,
    {% for param in op.params %}{{ param.name }}: {{ param.python_type }},
    {% endfor %}
) -> {{ op.response_type }}:
    response.headers["X-Generated-By"] = "pyoas"
    return await service.{{ op.function_name }}(...)
{% endfor %}
```

## Inspecting built-in templates

The built-in templates are in the installed package:

```shell
python -c "import pyoas.models; print(pyoas.models.__file__)"
# .../site-packages/pyoas/models/__init__.py
# → templates are in .../site-packages/pyoas/models/templates/
```

Copy a template to your override directory as a starting point:

```shell
cp "$(python -c 'import pyoas.models, os; print(os.path.dirname(pyoas.models.__file__))')/templates/model.py.jinja2" \
   templates/models/model.py.jinja2
```
