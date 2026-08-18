"""Portal aggregation endpoint tests for project-service."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import TracebackType
from typing import Self

from project_service.app import create_app
from project_service.collaboration.models import Iteration, ReleaseVersion
from project_service.config import Settings
from project_service.projects.models import Project
from project_service.projects.service import ProjectService

_NOW = datetime(2026, 8, 10, 2, 11, tzinfo=UTC)


def _project(identifier: str, business_no: str, name: str) -> Project:
    return Project(
        id=identifier,
        business_no=business_no,
        name=name,
        description="",
        owner_id="owner-1",
        status="active",
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _iteration(project_id: str) -> Iteration:
    return Iteration(
        id="it-1",
        project_id=project_id,
        business_no="ITR-001",
        name="Sprint 12",
        goal="",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 14),
        capacity_minutes=None,
        status="active",
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _version(project_id: str) -> ReleaseVersion:
    return ReleaseVersion(
        id="ver-1",
        project_id=project_id,
        business_no="VER-001",
        name="v2.0",
        description="",
        status="active",
        planned_release_date=date(2026, 8, 30),
        release_date=None,
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


class FakePortalRepository:
    """In-memory stand-in for the batched portal read model."""

    def __init__(self) -> None:
        self.mine: list[Project] = [
            _project("p-1", "PRJ-000001", "支付中台"),
            _project("p-2", "PRJ-000002", "风控引擎"),
        ]
        self.all_projects: list[Project] = [*self.mine, _project("p-3", "PRJ-000003", "结算平台")]
        self.calls: list[tuple[str, object]] = []

    def scoped_projects(self, actor_id: str, cross_project: bool) -> list[Project]:
        self.calls.append(("scoped_projects", cross_project))
        return list(self.all_projects if cross_project else self.mine)

    def active_iterations(self, project_ids: list[str]) -> dict[str, Iteration]:
        self.calls.append(("active_iterations", tuple(project_ids)))
        return {"p-1": _iteration("p-1")}

    def active_versions(self, project_ids: list[str]) -> dict[str, ReleaseVersion]:
        self.calls.append(("active_versions", tuple(project_ids)))
        return {"p-1": _version("p-1")}

    def task_progress(self, project_ids: list[str]) -> dict[str, tuple[int, int]]:
        self.calls.append(("task_progress", tuple(project_ids)))
        return {"p-1": (13, 20)}

    def open_task_counts(self, project_ids: list[str], actor_id: str) -> dict[str, int]:
        self.calls.append(("open_task_counts", (tuple(project_ids), actor_id)))
        return {"p-1": 4}


class FakeUnitOfWork:
    """Minimal unit of work exposing only the portal read model."""

    def __init__(self, portal: FakePortalRepository) -> None:
        self.portal = portal

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None


def _service() -> tuple[ProjectService, FakePortalRepository]:
    portal = FakePortalRepository()
    return ProjectService(lambda: FakeUnitOfWork(portal)), portal


def test_portal_overview_shapes_the_frozen_contract() -> None:
    service, _ = _service()
    data = service.portal_overview("actor-1")
    assert data["total"] == 2
    assert data["project_ids"] == ["p-1", "p-2"]
    first = data["items"][0]
    assert first == {
        "id": "p-1",
        "business_no": "PRJ-000001",
        "name": "支付中台",
        "status": "active",
        "progress_percent": 65,
        "current_iteration": {
            "id": "it-1",
            "name": "Sprint 12",
            "status": "active",
            "start_date": "2026-08-01",
            "end_date": "2026-08-14",
        },
        "current_version": {
            "id": "ver-1",
            "name": "v2.0",
            "status": "active",
            "planned_release_date": "2026-08-30",
        },
        "my_open_task_count": 4,
    }


def test_projects_without_tracked_tasks_report_null_progress() -> None:
    service, _ = _service()
    second = service.portal_overview("actor-1")["items"][1]
    assert second["progress_percent"] is None
    assert second["current_iteration"] is None
    assert second["current_version"] is None
    assert second["my_open_task_count"] == 0


def test_limit_truncates_items_but_never_project_ids() -> None:
    service, _ = _service()
    data = service.portal_overview("actor-1", limit=1)
    assert len(data["items"]) == 1
    assert data["project_ids"] == ["p-1", "p-2"]
    assert data["total"] == 2


def test_cross_project_scope_widens_the_project_set() -> None:
    service, portal = _service()
    data = service.portal_overview("actor-1", cross_project=True)
    assert data["total"] == 3
    assert ("scoped_projects", True) in portal.calls


def test_detail_queries_are_batched_over_visible_projects_only() -> None:
    service, portal = _service()
    service.portal_overview("actor-1", limit=1)
    batched = [name for name, _ in portal.calls]
    assert batched == [
        "scoped_projects",
        "active_iterations",
        "active_versions",
        "task_progress",
        "open_task_counts",
    ]
    assert portal.calls[1] == ("active_iterations", ("p-1",))


class StubProjectService:
    """Captures the arguments the HTTP layer resolves before delegating."""

    def __init__(self) -> None:
        self.received: dict[str, object] = {}

    def portal_overview(
        self, actor_id: str, *, cross_project: bool = False, limit: int = 8
    ) -> dict[str, object]:
        self.received = {"actor_id": actor_id, "cross_project": cross_project, "limit": limit}
        return {"total": 0, "items": [], "project_ids": []}


def _client() -> tuple[object, StubProjectService, object]:
    app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:"))
    stub = StubProjectService()
    app.extensions["project_service"] = stub
    return app.test_client(), stub, app


def test_endpoint_defaults_to_scoped_view() -> None:
    client, stub, app = _client()
    response = client.get("/api/v1/portal/projects-overview", headers={"X-Actor-Id": "actor-1"})
    assert response.status_code == 200
    assert response.get_json()["data"] == {"total": 0, "items": [], "project_ids": []}
    assert stub.received == {"actor_id": "actor-1", "cross_project": False, "limit": 8}
    app.extensions["database"].dispose()


def test_cross_project_header_without_permission_is_ignored() -> None:
    client, stub, app = _client()
    client.get(
        "/api/v1/portal/projects-overview",
        headers={
            "X-Actor-Id": "actor-1",
            "X-Portal-Cross-Project": "true",
            "X-Platform-Permissions": "audit.read",
        },
    )
    assert stub.received["cross_project"] is False
    app.extensions["database"].dispose()


def test_cross_project_header_with_permission_is_honoured() -> None:
    client, stub, app = _client()
    client.get(
        "/api/v1/portal/projects-overview?limit=3",
        headers={
            "X-Actor-Id": "actor-1",
            "X-Portal-Cross-Project": "true",
            "X-Platform-Permissions": "audit.read,portal:cross-project-view",
        },
    )
    assert stub.received == {"actor_id": "actor-1", "cross_project": True, "limit": 3}
    app.extensions["database"].dispose()


def test_invalid_limit_is_rejected_as_problem_details() -> None:
    client, _, app = _client()
    response = client.get("/api/v1/portal/projects-overview?limit=0")
    assert response.status_code == 422
    assert response.content_type == "application/problem+json"
    app.extensions["database"].dispose()
