import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

from project_service.app import create_app
from project_service.config import Settings

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def app():
    if not DATABASE_URL:
        pytest.skip(
            "TEST_DATABASE_URL is not configured; PostgreSQL integration tests not executed"
        )
    os.environ["DATABASE_URL"] = DATABASE_URL
    command.upgrade(Config("alembic.ini"), "head")
    application = create_app(Settings(environment="test", database_url=DATABASE_URL))
    yield application
    application.extensions["database"].dispose()


def test_replay_conflict_cross_actor_and_isolation(app) -> None:
    key = f"integration-{uuid4()}"
    with app.test_client() as client:
        first = client.post(
            "/api/v1/projects",
            json={"name": "Alpha"},
            headers={"X-Actor-Id": "a", "Idempotency-Key": key},
        )
        replay = client.post(
            "/api/v1/projects",
            json={"name": "Alpha"},
            headers={"X-Actor-Id": "a", "Idempotency-Key": key},
        )
        conflict = client.post(
            "/api/v1/projects",
            json={"name": "Beta"},
            headers={"X-Actor-Id": "a", "Idempotency-Key": key},
        )
        other = client.post(
            "/api/v1/projects",
            json={"name": "Beta"},
            headers={"X-Actor-Id": "b", "Idempotency-Key": key},
        )
    assert first.get_json()["data"]["id"] == replay.get_json()["data"]["id"]
    assert conflict.status_code == 409
    assert conflict.get_json()["error_code"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert other.status_code == 201


def test_ten_concurrent_replays_create_one_project(app) -> None:
    key = f"concurrent-{uuid4()}"

    def create(_: int) -> str:
        with app.test_client() as client:
            response = client.post(
                "/api/v1/projects",
                json={"name": "Concurrent"},
                headers={"X-Actor-Id": "parallel", "Idempotency-Key": key},
            )
            assert response.status_code == 201
            return response.get_json()["data"]["id"]

    with ThreadPoolExecutor(max_workers=10) as executor:
        ids = list(executor.map(create, range(10)))
    assert len(set(ids)) == 1
