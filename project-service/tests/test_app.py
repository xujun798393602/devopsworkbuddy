from unittest.mock import Mock, patch

from project_service.app import create_app
from project_service.config import Settings
from project_service.database import Database


def test_health_is_liveness_and_readiness_hides_database_details() -> None:
    app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:"))
    client = app.test_client()
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    database = app.extensions["database"]
    database.ping = Mock(return_value=False)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.get_json() == {
        "status": "unavailable",
        "checks": {"database": {"status": "fail"}},
    }
    assert "sqlite" not in response.get_data(as_text=True)
    database.dispose()


def test_postgres_timeout_configuration() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+psycopg://user:secret@db/service",
        readiness_timeout=2.8,
    )
    with patch("project_service.database.create_engine") as create_engine:
        create_engine.return_value = Mock()
        Database(settings)
    options = create_engine.call_args.kwargs
    assert options["connect_args"] == {
        "connect_timeout": 2,
        "options": "-c statement_timeout=2000",
    }
    assert "secret" not in str(options)


def test_problem_details_content_type_and_key_length() -> None:
    app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:"))
    response = app.test_client().post(
        "/api/v1/projects",
        json={"name": "X"},
        headers={"Idempotency-Key": "x" * 256},
    )
    assert response.status_code == 422
    assert response.content_type == "application/problem+json"
    app.extensions["database"].dispose()


def test_unknown_field_is_rejected_before_database_access() -> None:
    app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:"))
    response = app.test_client().post(
        "/api/v1/projects",
        json={"name": "X", "ignored": "not allowed"},
        headers={"Idempotency-Key": "strict"},
    )
    assert response.status_code == 422
    assert response.get_json()["errors"] == [{"field": "ignored", "message": "Unknown field"}]
    app.extensions["database"].dispose()


def test_unexpected_error_is_safe_problem_details(caplog) -> None:
    app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:"))
    secret_message = "password=super-secret DATABASE_URL=postgresql://user:pw@host/db"
    app.extensions["database"].ping = Mock(side_effect=RuntimeError(secret_message))
    with caplog.at_level("ERROR", logger="project_service.app"):
        response = app.test_client().get("/ready", headers={"X-Trace-Id": "safe-trace"})
    assert response.status_code == 500
    assert response.content_type == "application/problem+json"
    body = response.get_json()
    assert body["error_code"] == "INTERNAL_SERVER_ERROR"
    assert body["detail"] == "An unexpected error occurred"
    assert body["trace_id"] == "safe-trace"
    response_text = response.get_data(as_text=True)
    log_text = caplog.text
    for sensitive_value in ("super-secret", "postgresql://", secret_message):
        assert sensitive_value not in response_text
        assert sensitive_value not in log_text
    assert "safe-trace" in log_text
    assert "RuntimeError" in log_text
    app.extensions["database"].dispose()
