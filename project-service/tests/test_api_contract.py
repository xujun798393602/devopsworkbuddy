from pathlib import Path

import yaml
from openapi_spec_validator import validate

from project_service.app import create_app
from project_service.config import Settings


def test_openapi_is_valid_31_and_covers_p0_paths() -> None:
    openapi_path = Path(__file__).resolve().parents[1] / "openapi.yaml"
    document = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))
    validate(document)
    assert document["openapi"] == "3.1.0"
    required = {
        "/api/v1/projects/{project_id}/members",
        "/api/v1/projects/{project_id}/versions",
        "/api/v1/projects/{project_id}/iterations",
        "/api/v1/projects/{project_id}/tasks",
        "/api/v1/projects/{project_id}/tasks/{task_id}/worklogs",
    }
    assert required <= document["paths"].keys()


def test_if_match_problem_is_rfc9457() -> None:
    app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:"))
    client = app.test_client()
    response = client.patch(
        "/api/v1/projects/p/members/m", json={"role": "member"}, headers={"Idempotency-Key": "k"}
    )
    assert response.status_code == 422 and response.content_type == "application/problem+json"
    assert {
        "type",
        "title",
        "status",
        "detail",
        "error_code",
        "trace_id",
    } <= response.get_json().keys()
    app.extensions["database"].dispose()
