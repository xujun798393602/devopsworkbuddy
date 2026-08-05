from datetime import UTC, datetime
from uuid import uuid4

import pytest

from project_service.app import create_app
from project_service.config import Settings
from project_service.persistence.tables import ProjectMembershipRow, ProjectRow


def make_app():
    app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:", internal_service_token="test-token"))
    database = app.extensions["database"]
    ProjectRow.__table__.create(database.engine)
    ProjectMembershipRow.__table__.create(database.engine)
    project_id = uuid4()
    with database.sessions() as session:
        now = datetime.now(UTC)
        session.add(ProjectRow(id=project_id, business_no="WK-1", name="Demo", description="", owner_id="owner", status="active", version=1, created_at=now, updated_at=now))
        session.add(ProjectMembershipRow(id=uuid4(), project_id=project_id, user_id="member", role="member", status="active", joined_at=now, joined_by="owner", version=1))
        session.commit()
    return app, str(project_id)


def test_internal_authorization_token_role_and_project_isolation() -> None:
    app, project_id = make_app()
    client = app.test_client()
    path = "/internal/api/v1/authorization/check"
    payload = {"actor_id": "member", "project_id": project_id, "action": "workflow.start"}
    assert client.post(path, json=payload).status_code == 401
    assert client.post(path, json=payload, headers={"X-Internal-Service-Token": "wrong"}).status_code == 401
    allowed = client.post(path, json=payload, headers={"X-Internal-Service-Token": "test-token"})
    assert allowed.status_code == 200 and allowed.get_json()["data"]["allowed"] is True
    missing = client.post(path, json={**payload, "actor_id": "outsider"}, headers={"X-Internal-Service-Token": "test-token"})
    assert missing.get_json()["data"] == {"allowed": False, "project_role": None, "reason_code": "NOT_PROJECT_MEMBER"}
    cross = client.post(path, json={**payload, "project_id": str(uuid4())}, headers={"X-Internal-Service-Token": "test-token"})
    assert cross.get_json()["data"]["allowed"] is False
    app.extensions["database"].dispose()


def test_production_requires_external_internal_token(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://example.invalid/db")
    monkeypatch.delenv("INTERNAL_SERVICE_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="INTERNAL_SERVICE_TOKEN"):
        Settings.from_env()
