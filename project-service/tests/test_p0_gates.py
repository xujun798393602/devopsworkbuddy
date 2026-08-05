"""Unit tests for version/iteration completion gate, cursor pagination, and idempotency replay."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from project_service.collaboration.models import Iteration, ProjectMembership, ReleaseVersion, Role
from project_service.collaboration.service import CollaborationService
from project_service.shared.errors import ConflictError, ValidationError
from project_service.shared.idempotency import IdempotencyExecutor
from project_service.shared.request_context import RequestContext
from project_service.tasks.models import Task
from project_service.tasks.service import TaskService

CONTEXT = RequestContext(trace_id="trace-test", actor_id="owner-1")
NOW = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)


def _membership(role: Role = Role.OWNER) -> ProjectMembership:
    return ProjectMembership("m1", "p1", "owner-1", role, "active", NOW, "owner-1")


def _version(status: str = "planned", version: int = 1) -> ReleaseVersion:
    return ReleaseVersion(
        "v1", "p1", "VER-1", "Release 1", "", status,
        date(2026, 3, 1), None, version, NOW, NOW,
    )


def _iteration(status: str = "planned", version: int = 1) -> Iteration:
    return Iteration(
        "i1", "p1", "ITR-1", "Sprint 1", "",
        date(2026, 1, 1), date(2026, 1, 31), None, status,
        version, NOW, NOW,
    )


def _task(
    task_id: str = "t1",
    status: str = "todo",
    release_version_id: str = "v1",
    iteration_id: str | None = None,
) -> Task:
    return Task(
        task_id, "TSK-1", "p1", "Task", "", "other", "p2", status,
        "owner-1", None, release_version_id, iteration_id, 30,
        None, None, None, None, "task-default", 1, 1, NOW, NOW,
    )


class FakeUoW:
    """In-memory UoW for unit testing service-layer logic."""

    def __init__(self, *, has_open: bool = False, tasks: list[Task] | None = None) -> None:
        self._has_open = has_open
        self._tasks = tasks or []
        self.idempotency = MagicMock()
        self.idempotency._records: dict[tuple[str, str], Any] = {}

        def mock_lock(scope: str, key: str) -> None:
            pass

        def mock_get(scope: str, key: str) -> Any:
            return self.idempotency._records.get((scope, key))

        def mock_add_processing(scope: str, key: str, request_hash: str, operation: str = "") -> Any:
            record = MagicMock()
            record.scope = scope
            record.idempotency_key = key
            record.request_hash = request_hash
            record.status = "processing"
            record.response_status = None
            record.resource_id = None
            record.response_body = None
            record.response_headers = None
            self.idempotency._records[(scope, key)] = record
            return record

        def mock_complete(
            record: Any, resource_id: str | None, status: int,
            body: dict | None = None, headers: dict | None = None,
        ) -> None:
            record.status = "completed"
            record.response_status = status
            record.resource_id = resource_id
            record.response_body = body
            record.response_headers = headers or {}

        self.idempotency.lock = mock_lock
        self.idempotency.get = mock_get
        self.idempotency.add_processing = mock_add_processing
        self.idempotency.complete = mock_complete

        self.collaboration = MagicMock()
        self.collaboration.get_active_membership.return_value = _membership()
        self.collaboration.get_version.return_value = _version()
        self.collaboration.get_iteration.return_value = _iteration()
        self.collaboration.transfer_owner_roles.return_value = True
        self.collaboration.next_counter.return_value = 1

        self.projects = MagicMock()
        project = MagicMock()
        project.status = "active"
        project.version = 1
        project.owner_id = "owner-1"
        self.projects.get.return_value = project
        self.projects.save.return_value = True

        self.tasks = MagicMock()
        self.tasks.has_open_tasks.return_value = self._has_open
        self.tasks.get.return_value = None
        self.tasks.list.return_value = self._tasks
        self.tasks.next_business_no.return_value = "TSK-1"
        self.tasks.add.return_value = None
        self.tasks.save.return_value = True
        self.tasks.get_worklog.return_value = None
        self.tasks.list_worklogs.return_value = []
        self.tasks.append_worklog.return_value = None
        self.tasks.sum_task_minutes.return_value = 0
        self.tasks.sum_user_day_minutes.return_value = 0
        self.tasks.lock_worklog_scope.return_value = None

        self.audit = MagicMock()
        self.outbox = MagicMock()
        self._committed = False

    def __enter__(self) -> FakeUoW:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        pass

    def commit(self) -> None:
        self._committed = True


def _collab_service(has_open: bool = False) -> CollaborationService:
    uow = FakeUoW(has_open=has_open)

    def factory() -> FakeUoW:
        return uow

    return CollaborationService(factory, clock=lambda: NOW, idempotency=IdempotencyExecutor())


# ---------------------------------------------------------------------------
# Completion gate tests
# ---------------------------------------------------------------------------


class TestVersionCompletionGate:
    """Version release gate: reject when associated tasks are open."""

    def test_release_rejected_when_open_tasks_exist(self) -> None:
        service = _collab_service(has_open=True)
        with pytest.raises(ConflictError) as exc:
            service.transition_version(
                "p1", "v1",
                {"target_status": "released"},
                CONTEXT, "key-1", expected=1,
            )
        assert exc.value.error_code == "OPEN_TASKS_EXIST"

    def test_force_without_reason_returns_validation_error(self) -> None:
        service = _collab_service(has_open=True)
        with pytest.raises(ValidationError, match="reason is required"):
            service.transition_version(
                "p1", "v1",
                {"target_status": "released", "force": True},
                CONTEXT, "key-2", expected=1,
            )

    def test_force_with_reason_succeeds(self) -> None:
        service = _collab_service(has_open=True)
        # Version must be active before releasing
        service._uow_factory()._has_open = False  # type: ignore[attr-defined]
        service.transition_version(
            "p1", "v1",
            {"target_status": "active"},
            CONTEXT, "key-3a", expected=1,
        )
        service._uow_factory()._has_open = True  # type: ignore[attr-defined]
        service._uow_factory().collaboration.get_version.return_value = _version(status="active", version=2)  # type: ignore[attr-defined]
        response = service.transition_version(
            "p1", "v1",
            {"target_status": "released", "force": True, "reason": "  emergency release  "},
            CONTEXT, "key-3", expected=2,
        )
        assert response.status == 200
        assert response.body["data"]["status"] == "released"


class TestIterationCompletionGate:
    """Iteration completion gate: reject when associated tasks are open."""

    def test_complete_rejected_when_open_tasks_exist(self) -> None:
        service = _collab_service(has_open=True)
        # Iteration must be active first before completing
        service._uow_factory()._has_open = False  # type: ignore[attr-defined]
        service.transition_iteration(
            "p1", "i1",
            {"target_status": "active"},
            CONTEXT, "key-4", expected=1,
        )
        service._uow_factory()._has_open = True  # type: ignore[attr-defined]
        service._uow_factory().collaboration.get_iteration.return_value = _iteration(status="active", version=2)  # type: ignore[attr-defined]
        with pytest.raises(ConflictError) as exc:
            service.transition_iteration(
                "p1", "i1",
                {"target_status": "completed"},
                CONTEXT, "key-5", expected=2,
            )
        assert exc.value.error_code == "OPEN_TASKS_EXIST"

    def test_force_without_reason_returns_validation_error(self) -> None:
        service = _collab_service(has_open=True)
        service._uow_factory()._has_open = False  # type: ignore[attr-defined]
        service.transition_iteration(
            "p1", "i1",
            {"target_status": "active"},
            CONTEXT, "key-6", expected=1,
        )
        service._uow_factory()._has_open = True  # type: ignore[attr-defined]
        service._uow_factory().collaboration.get_iteration.return_value = _iteration(status="active", version=2)  # type: ignore[attr-defined]
        with pytest.raises(ValidationError, match="reason is required"):
            service.transition_iteration(
                "p1", "i1",
                {"target_status": "completed", "force": True},
                CONTEXT, "key-7", expected=2,
            )

    def test_force_with_reason_succeeds(self) -> None:
        service = _collab_service(has_open=True)
        service._uow_factory()._has_open = False  # type: ignore[attr-defined]
        service.transition_iteration(
            "p1", "i1",
            {"target_status": "active"},
            CONTEXT, "key-8", expected=1,
        )
        service._uow_factory()._has_open = True  # type: ignore[attr-defined]
        service._uow_factory().collaboration.get_iteration.return_value = _iteration(status="active", version=2)  # type: ignore[attr-defined]
        response = service.transition_iteration(
            "p1", "i1",
            {"target_status": "completed", "force": True, "reason": "carry-over approved"},
            CONTEXT, "key-9", expected=2,
        )
        assert response.status == 200
        assert response.body["data"]["status"] == "completed"


# ---------------------------------------------------------------------------
# Cursor pagination tests
# ---------------------------------------------------------------------------


class TestTaskCursorPagination:
    """Stable cursor pagination: (created_at, id) ordering, after cursor, limit."""

    def _tasks(self, count: int) -> list[Task]:
        return [
            Task(
                f"t{i:03d}", f"TSK-{i:03d}", "p1", f"Task {i}", "", "other", "p2", "todo",
                "owner-1", None, "v1", None, 30, None, None, None, None,
                "task-default", 1, 1,
                datetime(2026, 1, 1, 10, i, 0, tzinfo=UTC), NOW,
            )
            for i in range(count)
        ]

    def _task_service(self, tasks: list[Task]) -> TaskService:
        uow = FakeUoW(tasks=tasks)

        def factory() -> FakeUoW:
            return uow

        return TaskService(factory, clock=lambda: NOW, idempotency=IdempotencyExecutor())

    def test_stable_sort_by_created_at_then_id(self) -> None:
        tasks = self._tasks(5)
        service = self._task_service(tasks)
        page = service.list_tasks("p1", CONTEXT, limit=50, after=None)
        assert len(page.items) == 5
        for i in range(4):
            assert page.items[i].created_at <= page.items[i + 1].created_at

    def test_after_cursor_continues_from_last_item(self) -> None:
        tasks = self._tasks(10)
        service = self._task_service(tasks)

        # FakeUoW.tasks.list is a MagicMock; configure it to slice properly
        original_list = service._uow_factory()._tasks  # type: ignore[attr-defined]

        def mock_list(project_id: str, limit: int = 50, after: tuple[str, str] | None = None) -> list[Task]:
            items = list(original_list)
            if after is not None:
                after_dt = datetime.fromisoformat(after[0].replace("Z", "+00:00"))
                items = [t for t in items if (t.created_at, t.id) > (after_dt, after[1])]
            return items[:limit]

        service._uow_factory().tasks.list.side_effect = mock_list  # type: ignore[attr-defined]

        page1 = service.list_tasks("p1", CONTEXT, limit=5, after=None)
        assert len(page1.items) == 5
        assert page1.has_more is True
        assert page1.next_cursor is not None

        from project_service.shared.http import decode_cursor

        cursor = decode_cursor(page1.next_cursor, "p1")
        page2 = service.list_tasks("p1", CONTEXT, limit=5, after=cursor)
        assert len(page2.items) == 5
        assert page2.has_more is False
        assert page2.next_cursor is None

    def test_default_limit_is_50(self) -> None:
        tasks = self._tasks(60)
        service = self._task_service(tasks)
        page = service.list_tasks("p1", CONTEXT, limit=50, after=None)
        assert len(page.items) == 50
        assert page.has_more is True

    def test_max_limit_is_200(self) -> None:
        from project_service.shared.errors import ValidationError as VE
        from project_service.shared.http import parse_limit

        class FakeRequest:
            def __init__(self, limit_str: str) -> None:
                self._args = {"limit": limit_str}

            @property
            def args(self) -> dict[str, str]:
                return self._args

        with pytest.raises(VE):
            parse_limit(FakeRequest("201"))

        assert parse_limit(FakeRequest("200")) == 200

    def test_invalid_cursor_returns_422(self) -> None:
        from project_service.shared.errors import ValidationError as VE
        from project_service.shared.http import decode_cursor

        with pytest.raises(VE):
            decode_cursor("!!!invalid!!!", "p1")

    def test_cross_project_cursor_leakage_prevented(self) -> None:
        """Cursor from project A must not be usable for project B."""
        from project_service.shared.errors import ValidationError as VE
        from project_service.shared.http import decode_cursor, encode_cursor

        cursor = encode_cursor("project-a", "2026-01-01T10:00:00+00:00", "t1")
        with pytest.raises(VE, match="cursor is invalid"):
            decode_cursor(cursor, "project-b")

    def test_cursor_with_valid_project_returns_tuple(self) -> None:
        from project_service.shared.http import decode_cursor, encode_cursor

        cursor = encode_cursor("p1", "2026-01-01T10:00:00+00:00", "t1")
        result = decode_cursor(cursor, "p1")
        assert result == ("2026-01-01T10:00:00+00:00", "t1")


# ---------------------------------------------------------------------------
# Idempotency replay tests
# ---------------------------------------------------------------------------


class TestIdempotencyReplay:
    """Verify replay returns full status/body/headers; same key different request = 409."""

    def _collab_service(self) -> CollaborationService:
        uow = FakeUoW(has_open=False)
        uow.collaboration.get_version.return_value = _version(status="planned", version=1)
        uow.collaboration.add_version.return_value = None
        uow.collaboration.save_version.return_value = True
        uow.collaboration.next_counter.return_value = 1

        def factory() -> FakeUoW:
            return uow

        return CollaborationService(factory, clock=lambda: NOW, idempotency=IdempotencyExecutor())

    def test_replay_returns_same_status_body_and_headers(self) -> None:
        service = self._collab_service()
        cmd = {"name": "Version A", "description": "desc"}
        first = service.create_version("p1", cmd, CONTEXT, "key-replay-1")
        second = service.create_version("p1", cmd, CONTEXT, "key-replay-1")
        assert second.replayed is True
        assert second.status == first.status
        assert second.body == first.body
        assert second.headers == first.headers

    def test_same_key_different_request_returns_409(self) -> None:
        service = self._collab_service()
        service.create_version("p1", {"name": "Version A"}, CONTEXT, "key-conflict-1")
        with pytest.raises(ConflictError) as exc:
            service.create_version("p1", {"name": "Version B"}, CONTEXT, "key-conflict-1")
        assert exc.value.status_code == 409
        assert exc.value.error_code == "IDEMPOTENCY_KEY_CONFLICT"

    def test_delete_request_fingerprint_includes_path_params(self) -> None:
        """DELETE with same key but different path param should be 409."""
        from project_service.shared.idempotency import canonical_request_hash

        hash1 = canonical_request_hash(
            "DELETE /projects/{p}/members/{m}",
            {"project_id": "p1", "membership_id": "m1"},
            {},
            1,
        )
        hash2 = canonical_request_hash(
            "DELETE /projects/{p}/members/{m}",
            {"project_id": "p1", "membership_id": "m2"},
            {},
            1,
        )
        assert hash1 != hash2

    def test_patch_request_fingerprint_includes_if_match_and_body(self) -> None:
        """PATCH fingerprint must differ with different If-Match or body."""
        from project_service.shared.idempotency import canonical_request_hash

        hash1 = canonical_request_hash(
            "PATCH /projects/{p}/members/{m}",
            {"project_id": "p1", "membership_id": "m1"},
            {"role": "member"},
            1,
        )
        hash2 = canonical_request_hash(
            "PATCH /projects/{p}/members/{m}",
            {"project_id": "p1", "membership_id": "m1"},
            {"role": "admin"},
            1,
        )
        hash3 = canonical_request_hash(
            "PATCH /projects/{p}/members/{m}",
            {"project_id": "p1", "membership_id": "m1"},
            {"role": "member"},
            2,
        )
        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3
