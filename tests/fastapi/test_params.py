from pyoas.fastapi.params import (
    _annotated_base_type,
    build_function_params,
    resolve_response_type,
)


def test_path_param() -> None:
    operation = {
        "parameters": [
            {
                "name": "petId",
                "in": "path",
                "required": True,
                "schema": {"type": "integer", "format": "int64"},
            },
        ],
        "responses": {},
    }
    params = build_function_params(operation)
    assert len(params) == 1
    p = params[0]
    assert p["name"] == "pet_id"
    assert p["alias"] == "petId"
    assert p["python_type"] == 'Annotated[int, Path(alias="petId")]'
    assert p["fastapi_class"] == "Path"
    assert p["location"] == "path"
    assert p["required"] is True


def test_optional_query_param() -> None:
    operation = {
        "parameters": [
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
            },
        ],
        "responses": {},
    }
    params = build_function_params(operation)
    assert params[0]["required"] is False
    assert "None" in params[0]["python_type"]


def test_request_body() -> None:
    operation = {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/CreatePetRequest"},
                }
            },
        },
        "responses": {},
    }
    params = build_function_params(operation)
    body_params = [p for p in params if p["location"] == "body"]
    assert len(body_params) == 1


def test_query_param_with_min_max_constraints() -> None:
    """Query params with min/max constraints must be wrapped in Annotated[..., Query(...)]."""
    operation = {
        "parameters": [
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        ],
        "responses": {},
    }
    params = build_function_params(operation)
    assert len(params) == 1
    p = params[0]
    assert "Annotated[" in p["python_type"]
    assert "Query(" in p["python_type"]
    assert "ge=1" in p["python_type"]
    assert "le=100" in p["python_type"]
    assert p["fastapi_class"] == "Query"


def test_path_param_with_constraints() -> None:
    """Path params with constraints must be wrapped in Annotated[..., Path(...)]."""
    operation = {
        "parameters": [
            {
                "name": "item_id",
                "in": "path",
                "required": True,
                "schema": {"type": "integer", "minimum": 1},
            },
        ],
        "responses": {},
    }
    params = build_function_params(operation)
    p = params[0]
    assert "Path(" in p["python_type"]
    assert "ge=1" in p["python_type"]
    assert p["fastapi_class"] == "Path"


def test_query_param_min_length_constraint() -> None:
    """String query params with minLength produce Query(min_length=N)."""
    operation = {
        "parameters": [
            {
                "name": "q",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "minLength": 2},
            },
        ],
        "responses": {},
    }
    params = build_function_params(operation)
    p = params[0]
    assert "min_length=2" in p["python_type"]
    assert "Query(" in p["python_type"]


def test_query_param_pattern_constraint() -> None:
    """Query params with pattern produce Query(pattern=...)."""
    operation = {
        "parameters": [
            {
                "name": "code",
                "in": "query",
                "required": True,
                "schema": {"type": "string", "pattern": "^[A-Z]{3}$"},
            },
        ],
        "responses": {},
    }
    params = build_function_params(operation)
    p = params[0]
    assert 'pattern="^[A-Z]{3}$"' in p["python_type"]


def test_param_without_constraints_has_no_fastapi_class() -> None:
    """Params without constraints must not have a fastapi_class set."""
    operation = {
        "parameters": [
            {
                "name": "page",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
            },
        ],
        "responses": {},
    }
    params = build_function_params(operation)
    assert params[0]["fastapi_class"] is None
    assert "Annotated[" not in params[0]["python_type"]


def test_resolve_response_type_200() -> None:
    operation = {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"id": {"type": "integer"}},
                        },
                    }
                }
            }
        }
    }
    result = resolve_response_type(operation)
    assert result == "dict[str, Any]"


def test_required_body_before_optional_query() -> None:
    """Required body param must appear after required params but before optional ones."""
    operation = {
        "parameters": [
            {
                "name": "optional_param",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
            },
        ],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object"},
                }
            },
        },
        "responses": {},
    }
    params = build_function_params(operation)
    names = [p["name"] for p in params]
    # body (required) must come before optional_param (optional)
    assert names.index("body") < names.index("optional_param")


def test_required_params_before_optional() -> None:
    """All required params appear before all optional params."""
    operation = {
        "parameters": [
            {
                "name": "opt_a",
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
            },
            {
                "name": "req_b",
                "in": "query",
                "required": True,
                "schema": {"type": "integer"},
            },
            {
                "name": "opt_c",
                "in": "header",
                "required": False,
                "schema": {"type": "string"},
            },
            {
                "name": "req_d",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            },
        ],
        "responses": {},
    }
    params = build_function_params(operation)
    required_indices = [i for i, p in enumerate(params) if p["required"]]
    optional_indices = [i for i, p in enumerate(params) if not p["required"]]
    assert max(required_indices) < min(optional_indices)


def test_resolve_response_type_no_content() -> None:
    operation = {"responses": {"204": {"description": "No content"}}}
    result = resolve_response_type(operation)
    assert result == "None"


# ---------------------------------------------------------------------------
# _annotated_base_type
# ---------------------------------------------------------------------------


def test_annotated_base_type_strips_body() -> None:
    assert _annotated_base_type("Annotated[Pet, Body()]") == "Pet"


def test_annotated_base_type_strips_query_constraints() -> None:
    assert (
        _annotated_base_type("Annotated[int | None, Query(ge=1, le=100)]")
        == "int | None"
    )


def test_annotated_base_type_passthrough() -> None:
    assert _annotated_base_type("int") == "int"
    assert _annotated_base_type("str | None") == "str | None"


# ---------------------------------------------------------------------------
# multipart/form-data (fix #4)
# ---------------------------------------------------------------------------


def test_multipart_file_field_generates_upload_file() -> None:
    operation = {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                        },
                    }
                }
            },
        },
        "responses": {},
    }
    params = build_function_params(operation)
    assert len(params) == 1
    p = params[0]
    assert p["name"] == "file"
    assert "UploadFile" in p["python_type"]
    assert "File()" in p["python_type"]
    assert p["fastapi_class"] == "File"
    assert p["required"] is True


def test_multipart_text_field_generates_form() -> None:
    operation = {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    }
                }
            },
        },
        "responses": {},
    }
    params = build_function_params(operation)
    assert len(params) == 2
    by_name = {p["name"]: p for p in params}
    assert "Form()" in by_name["name"]["python_type"]
    assert by_name["name"]["fastapi_class"] == "Form"
    assert by_name["name"]["required"] is True
    assert "None" in by_name["description"]["python_type"]  # optional
    assert by_name["description"]["required"] is False


def test_urlencoded_generates_form_params() -> None:
    operation = {
        "requestBody": {
            "required": True,
            "content": {
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "required": ["username"],
                        "properties": {
                            "username": {"type": "string"},
                            "age": {"type": "integer"},
                        },
                    }
                }
            },
        },
        "responses": {},
    }
    params = build_function_params(operation)
    assert len(params) == 2
    by_name = {p["name"]: p for p in params}
    assert "Form()" in by_name["username"]["python_type"]
    assert by_name["username"]["required"] is True
    assert "Form()" in by_name["age"]["python_type"]


def test_multipart_no_properties_falls_back_to_bytes() -> None:
    operation = {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {"type": "object"},
                }
            },
        },
        "responses": {},
    }
    params = build_function_params(operation)
    assert len(params) == 1
    assert params[0]["name"] == "body"
    assert "bytes" in params[0]["python_type"]


# ---------------------------------------------------------------------------
# Fix #2: service params should not carry FastAPI annotations
# ---------------------------------------------------------------------------


def test_body_param_has_annotated_body_wrapper() -> None:
    """Router params retain Annotated[T, Body()] — services strip this."""
    operation = {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object"},
                }
            },
        },
        "responses": {},
    }
    params = build_function_params(operation)
    body = next(p for p in params if p["location"] == "body")
    assert body["python_type"].startswith("Annotated[")
    # After stripping (as done in scaffold.py service context):
    assert _annotated_base_type(body["python_type"]) == "dict[str, Any]"
