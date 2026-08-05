from project_service.app import create_app
from project_service.config import Settings


def test_unknown_project_is_hidden_as_404() -> None:
    app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:"))
    client = app.test_client()
    # No database access is attempted because the UUID is invalid; non-members and invalid scoped IDs share 404.
    response = client.get("/api/v1/projects/not-a-uuid", headers={"X-Actor-Id": "outsider"})
    assert response.status_code == 404
    app.extensions["database"].dispose()
