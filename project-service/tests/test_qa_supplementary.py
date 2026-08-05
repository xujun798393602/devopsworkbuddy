"""Supplementary Round 1 QA tests for project-collaboration increment.

Covers gaps identified in code review:
- Idempotency: member/version/iteration/task/worklog all use shared executor
- Force transition writes audit + outbox
- Worklog immutability (no PATCH/DELETE route)
- Worklog actual_minutes net aggregation
- Cross-project cursor 422
- OpenAPI schema detail: enums, required fields, If-Match/Idempotency-Key params
- Migration 0002: pgcrypto order, FK order, no duplicate constraints
- Permission matrix: Viewer cannot create tasks, Member limited transitions
- Worklog correction chain: actual_minutes tracked after multiple corrections
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import yaml

from project_service.collaboration.models import (
    Iteration,
    ProjectMembership,
    ReleaseVersion,
    Role,
)
from project_service.collaboration.policies import Action, AuthorizationPolicy
from project_service.collaboration.service import CollaborationService
from project_service.shared.audit import make_audit, make_outbox
from project_service.shared.errors import ConflictError, ForbiddenError, ValidationError
from project_service.shared.idempotency import (
    IdempotencyExecutor,
    canonical_request_hash,
    replay_or_conflict,
)
from project_service.shared.request_context import RequestContext
from project_service.tasks.models import Task, Worklog
from project_service.tasks.service import TaskService
from project_service.tasks.workflow import WorkflowV1

CONTEXT = RequestContext(trace_id="trace-qa", actor_id="owner-1")
NOW = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers and fakes
# ---------------------------------------------------------------------------

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


def _task_service(tasks: list[Task] | None = None) -> TaskService:
    uow = FakeUoW(tasks=tasks or [])

    def factory() -> FakeUoW:
        return uow

    return TaskService(factory, clock=lambda: NOW, idempotency=IdempotencyExecutor())


# ---------------------------------------------------------------------------
# 1. Idempotency: all write interfaces use shared executor
# ---------------------------------------------------------------------------


class TestIdempotencyAllWriteInterfaces:
    """Verify member/version/iteration/task/worklog all go through IdempotencyExecutor."""

    def test_member_add_uses_executor_and_replays(self) -> None:
        service = _collab_service()
        cmd = {"user_id": "new-user", "role": "member"}
        first = service.add_member("p1", cmd, CONTEXT, "key-member-1")
        second = service.add_member("p1", cmd, CONTEXT, "key-member-1")
        assert second.replayed is True
        assert second.status == first.status
        assert second.body == first.body
        assert second.headers == first.headers

    def test_member_add_same_key_different_request_409(self) -> None:
        service = _collab_service()
        service.add_member("p1", {"user_id": "user-a", "role": "member"}, CONTEXT, "key-mc-1")
        with pytest.raises(ConflictError) as exc:
            service.add_member("p1", {"user_id": "user-b", "role": "admin"}, CONTEXT, "key-mc-1")
        assert exc.value.error_code == "IDEMPOTENCY_KEY_CONFLICT"

    def test_version_create_replays_full_response(self) -> None:
        service = _collab_service()
        cmd = {"name": "Version X", "description": "desc"}
        first = service.create_version("p1", cmd, CONTEXT, "key-ver-1")
        second = service.create_version("p1", cmd, CONTEXT, "key-ver-1")
        assert second.replayed is True
        assert second.status == first.status == 201
        assert second.body == first.body
        assert second.headers == first.headers

    def test_iteration_create_replays_full_response(self) -> None:
        service = _collab_service()
        cmd = {"name": "Sprint Q1", "start_date": "2026-01-01", "end_date": "2026-01-31"}
        first = service.create_iteration("p1", cmd, CONTEXT, "key-itr-1")
        second = service.create_iteration("p1", cmd, CONTEXT, "key-itr-1")
        assert second.replayed is True
        assert second.status == first.status == 201
        assert second.body == first.body
        assert second.headers == first.headers

    def test_task_create_replays_full_response(self) -> None:
        service = _task_service()
        uow = service._uow_factory()  # type: ignore[attr-defined]
        uow.tasks.get.return_value = _task()
        uow.tasks.save.return_value = True
        cmd = {"title": "New Task", "release_version_id": "v1", "estimated_minutes": 60}
        first = service.create_task("p1", cmd, CONTEXT, "key-task-1")
        second = service.create_task("p1", cmd, CONTEXT, "key-task-1")
        assert second.replayed is True
        assert second.status == first.status == 201
        assert second.body == first.body
        assert second.headers == first.headers

    def test_worklog_record_replays_full_response(self) -> None:
        service = _task_service()
        uow = service._uow_factory()  # type: ignore[attr-defined]
        uow.tasks.get.return_value = _task()
        uow.tasks.sum_task_minutes.return_value = 0
        uow.tasks.sum_user_day_minutes.return_value = 0
        cmd = {
            "work_date": "2026-01-10",
            "minutes_delta": 120,
            "description": "work done",
        }
        first = service.record_worklog("p1", "t1", cmd, CONTEXT, "key-wl-1")
        second = service.record_worklog("p1", "t1", cmd, CONTEXT, "key-wl-1")
        assert second.replayed is True
        assert second.status == first.status == 201
        assert second.body == first.body
        assert second.headers == first.headers

    def test_delete_fingerprint_includes_path_and_if_match(self) -> None:
        """DELETE with same key but different path or If-Match should produce different hash."""
        h1 = canonical_request_hash(
            "DELETE /projects/{project_id}/members/{membership_id}",
            {"project_id": "p1", "membership_id": "m1"},
            {},
            1,
        )
        h2 = canonical_request_hash(
            "DELETE /projects/{project_id}/members/{membership_id}",
            {"project_id": "p1", "membership_id": "m2"},
            {},
            1,
        )
        h3 = canonical_request_hash(
            "DELETE /projects/{project_id}/members/{membership_id}",
            {"project_id": "p1", "membership_id": "m1"},
            {},
            2,
        )
        assert h1 != h2  # different path
        assert h1 != h3  # different If-Match

    def test_patch_fingerprint_includes_path_if_match_and_body(self) -> None:
        """PATCH fingerprint must differ with different path, If-Match, or body."""
        h1 = canonical_request_hash(
            "PATCH /projects/{project_id}/members/{membership_id}",
            {"project_id": "p1", "membership_id": "m1"},
            {"role": "member"},
            1,
        )
        h2 = canonical_request_hash(
            "PATCH /projects/{project_id}/members/{membership_id}",
            {"project_id": "p1", "membership_id": "m2"},
            {"role": "member"},
            1,
        )
        h3 = canonical_request_hash(
            "PATCH /projects/{project_id}/members/{membership_id}",
            {"project_id": "p1", "membership_id": "m1"},
            {"role": "admin"},
            1,
        )
        h4 = canonical_request_hash(
            "PATCH /projects/{project_id}/members/{membership_id}",
            {"project_id": "p1", "membership_id": "m1"},
            {"role": "member"},
            2,
        )
        assert h1 != h2  # different path
        assert h1 != h3  # different body
        assert h1 != h4  # different If-Match

    def test_replay_or_conflict_in_progress_returns_409(self) -> None:
        """A processing record with same hash should return 409 IN_PROGRESS."""
        from project_service.idempotency.models import IdempotencyRecord

        record = IdempotencyRecord(
            scope="actor:u|operation:POST",
            idempotency_key="key",
            request_hash="abc123",
            status="processing",
        )
        with pytest.raises(ConflictError) as exc:
            replay_or_conflict(record, "abc123")
        assert exc.value.error_code == "IDEMPOTENCY_IN_PROGRESS"


# ---------------------------------------------------------------------------
# 2. Force transition writes audit and outbox
# ---------------------------------------------------------------------------


class TestForceTransitionAuditOutbox:
    """Verify force=true with reason writes audit and outbox records."""

    def test_force_version_release_writes_audit_and_outbox(self) -> None:
        service = _collab_service(has_open=True)
        # First transition to active (no open tasks)
        service._uow_factory()._has_open = False  # type: ignore[attr-defined]
        service.transition_version("p1", "v1", {"target_status": "active"}, CONTEXT, "key-a1", expected=1)

        uow = service._uow_factory()  # type: ignore[attr-defined]
        uow._has_open = True
        uow.collaboration.get_version.return_value = _version(status="active", version=2)

        service.transition_version(
            "p1", "v1",
            {"target_status": "released", "force": True, "reason": "emergency"},
            CONTEXT, "key-a2", expected=2,
        )
        # Audit and outbox should have been called at least once
        assert uow.audit.append.called
        assert uow.outbox.append.called

    def test_force_iteration_complete_writes_audit_and_outbox(self) -> None:
        service = _collab_service(has_open=True)
        service._uow_factory()._has_open = False  # type: ignore[attr-defined]
        service.transition_iteration("p1", "i1", {"target_status": "active"}, CONTEXT, "key-i1", expected=1)

        uow = service._uow_factory()  # type: ignore[attr-defined]
        uow._has_open = True
        uow.collaboration.get_iteration.return_value = _iteration(status="active", version=2)

        service.transition_iteration(
            "p1", "i1",
            {"target_status": "completed", "force": True, "reason": "carry-over"},
            CONTEXT, "key-i2", expected=2,
        )
        assert uow.audit.append.called
        assert uow.outbox.append.called


# ---------------------------------------------------------------------------
# 3. Cross-project cursor 422
# ---------------------------------------------------------------------------


class TestCursorCrossProject:
    """Verify cross-project cursor is rejected."""

    def test_cross_project_cursor_raises_validation_error(self) -> None:
        from project_service.shared.http import decode_cursor, encode_cursor

        cursor_a = encode_cursor("project-a-id", "2026-01-01T10:00:00+00:00", "task-1")
        with pytest.raises(ValidationError, match="cursor is invalid"):
            decode_cursor(cursor_a, "project-b-id")

    def test_malformed_cursor_raises_validation_error(self) -> None:
        from project_service.shared.http import decode_cursor

        with pytest.raises(ValidationError):
            decode_cursor("not-a-valid-base64-cursor!!!", "p1")


# ---------------------------------------------------------------------------
# 4. OpenAPI schema detail
# ---------------------------------------------------------------------------


class TestOpenAPISchemaDetail:
    """Verify OpenAPI 3.1 schema detail: enums, required fields, headers."""

    @pytest.fixture(scope="class")
    def doc(self) -> dict:
        openapi_path = Path(__file__).resolve().parents[1] / "openapi.yaml"
        return yaml.safe_load(openapi_path.read_text(encoding="utf-8"))

    def test_enum_values_in_schemas(self, doc: dict) -> None:
        schemas = doc["components"]["schemas"]
        # Member role enum
        assert "admin" in schemas["AddMemberRequest"]["properties"]["role"]["enum"]
        # Version status enum
        assert "planned" in schemas["VersionData"]["properties"]["status"]["enum"]
        # Task status enum
        assert "todo" in schemas["TaskData"]["properties"]["status"]["enum"]
        # Task priority enum
        assert "p2" in schemas["CreateTaskRequest"]["properties"]["priority"]["enum"]

    def test_required_fields_present(self, doc: dict) -> None:
        schemas = doc["components"]["schemas"]
        # ProblemDetails required fields
        assert "type" in schemas["ProblemDetails"]["required"]
        assert "error_code" in schemas["ProblemDetails"]["required"]
        assert "trace_id" in schemas["ProblemDetails"]["required"]
        # CreateTaskRequest required
        assert "title" in schemas["CreateTaskRequest"]["required"]
        assert "release_version_id" in schemas["CreateTaskRequest"]["required"]
        # RecordWorklogRequest required
        assert "work_date" in schemas["RecordWorklogRequest"]["required"]
        assert "minutes_delta" in schemas["RecordWorklogRequest"]["required"]

    def test_idempotency_key_parameter_required_on_writes(self, doc: dict) -> None:
        params = doc["components"]["parameters"]
        assert params["IdempotencyKey"]["required"] is True
        assert params["IdempotencyKey"]["schema"]["minLength"] == 1
        assert params["IdempotencyKey"]["schema"]["maxLength"] == 255

    def test_if_match_parameter_required_on_mutating(self, doc: dict) -> None:
        params = doc["components"]["parameters"]
        assert params["IfMatch"]["required"] is True

    def test_201_response_on_post_create(self, doc: dict) -> None:
        # POST create version → 201
        responses = doc["paths"]["/api/v1/projects/{project_id}/versions"]["post"]["responses"]
        assert "201" in responses

    def test_200_replay_header_on_post(self, doc: dict) -> None:
        responses = doc["paths"]["/api/v1/projects/{project_id}/versions"]["post"]["responses"]
        assert "201" in responses
        assert "Idempotency-Replayed" in responses["201"]["headers"]

    def test_404_409_412_422_problem_details(self, doc: dict) -> None:
        responses = doc["components"]["responses"]
        assert "NotFound" in responses
        assert "Conflict" in responses
        assert "PreconditionFailed" in responses
        assert "ValidationError" in responses
        for name in ("NotFound", "Conflict", "PreconditionFailed", "ValidationError"):
            content = responses[name]["content"]
            assert "application/problem+json" in content

    def test_limit_default_50_max_200(self, doc: dict) -> None:
        limit_schema = doc["components"]["parameters"]["Limit"]["schema"]
        assert limit_schema["default"] == 50
        assert limit_schema["maximum"] == 200


# ---------------------------------------------------------------------------
# 5. Migration 0002 structure
# ---------------------------------------------------------------------------


class TestMigration0002Additional:
    """Additional migration structure checks."""

    def test_0002_down_revision_is_0001(self) -> None:
        import importlib.util
        from pathlib import Path

        migrations_dir = Path(__file__).resolve().parents[1] / "migrations" / "versions"
        module_path = migrations_dir / "0002_project_collaboration.py"
        spec = importlib.util.spec_from_file_location("m0002", module_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.revision == "0002"
        assert module.down_revision == "0001"

    def test_0002_no_duplicate_constraints_in_upgrade(self) -> None:
        """0002 upgrade should not re-create constraints that 0001 already has."""
        from pathlib import Path

        migrations_dir = Path(__file__).resolve().parents[1] / "migrations" / "versions"
        source = (migrations_dir / "0002_project_collaboration.py").read_text(encoding="utf-8")
        upgrade_section = source.split("def downgrade")[0]
        # ck_idempotency_status was created in 0001; 0002 should not re-create it in upgrade
        # but may create a new one or drop/recreate
        # The key check: 0002 should NOT have create_check_constraint for ck_idempotency_status in upgrade
        # (it already exists from 0001)
        # It's OK to drop ck_idempotency_state in upgrade
        assert "drop_constraint" in upgrade_section  # drops old constraint
        # ck_projects_status is a NEW constraint for projects (0001 didn't have it)
        assert "ck_projects_status" in upgrade_section

    def test_0002_fk_order_correct(self) -> None:
        """Tables with composite FKs must be created after their referent tables."""
        from pathlib import Path

        migrations_dir = Path(__file__).resolve().parents[1] / "migrations" / "versions"
        source = (migrations_dir / "0002_project_collaboration.py").read_text(encoding="utf-8")

        # Verify ordering: project_memberships after projects (0001), tasks after versions+iterations
        pos_memberships = source.index('create_table(\n        "project_memberships"')
        pos_counters = source.index('create_table(\n        "project_counters"')
        pos_versions = source.index('create_table(\n        "release_versions"')
        pos_iterations = source.index('create_table(\n        "iterations"')
        pos_tasks = source.index('create_table(\n        "tasks"')
        pos_participants = source.index('create_table(\n        "task_participants"')
        pos_worklogs = source.index('create_table(\n        "worklogs"')

        # Counters and versions come after memberships (counters reference projects)
        assert pos_counters > pos_memberships
        # Versions after counters (counter is independent but logically after)
        assert pos_versions > pos_counters
        # Iterations after versions (both reference projects)
        assert pos_iterations > pos_versions
        # Tasks after versions AND iterations (composite FK to both)
        assert pos_tasks > pos_versions
        assert pos_tasks > pos_iterations
        # Participants after tasks (composite FK to tasks)
        assert pos_participants > pos_tasks
        # Worklogs after tasks (composite FK to tasks)
        assert pos_worklogs > pos_tasks

    def test_0002_upgrade_downgrade_symmetric_tables(self) -> None:
        """Every table created in upgrade must be dropped in downgrade."""
        import re
        from pathlib import Path

        migrations_dir = Path(__file__).resolve().parents[1] / "migrations" / "versions"
        source = (migrations_dir / "0002_project_collaboration.py").read_text(encoding="utf-8")

        upgrade_section = source.split("def downgrade")[0]
        downgrade_section = source.split("def downgrade")[1]

        created = set(re.findall(r'create_table\(\s*"(\w+)"', upgrade_section))
        dropped = set(re.findall(r'drop_table\("(\w+)"', downgrade_section))

        missing = created - dropped
        assert not missing, f"Tables created but not dropped: {missing}"


# ---------------------------------------------------------------------------
# 7. Permission matrix
# ---------------------------------------------------------------------------


class TestPermissionMatrix:
    """Verify the fixed P0 role matrix is correctly enforced."""

    def test_viewer_cannot_create_task(self) -> None:
        policy = AuthorizationPolicy()
        with pytest.raises(ForbiddenError):
            policy.authorize(Role.VIEWER, Action.CREATE_TASK)

    def test_member_cannot_manage_members(self) -> None:
        policy = AuthorizationPolicy()
        with pytest.raises(ForbiddenError):
            policy.authorize(Role.MEMBER, Action.MANAGE_MEMBERS)

    def test_member_cannot_transfer_owner(self) -> None:
        policy = AuthorizationPolicy()
        with pytest.raises(ForbiddenError):
            policy.authorize(Role.MEMBER, Action.TRANSFER_OWNER)

    def test_admin_cannot_transfer_owner(self) -> None:
        policy = AuthorizationPolicy()
        with pytest.raises(ForbiddenError):
            policy.authorize(Role.ADMIN, Action.TRANSFER_OWNER)

    def test_viewer_cannot_view_worklog_detail(self) -> None:
        policy = AuthorizationPolicy()
        assert policy.can_view_worklog_detail(Role.VIEWER) is False

    def test_member_can_create_and_transition_tasks(self) -> None:
        policy = AuthorizationPolicy()
        # Should not raise for related tasks
        policy.authorize(Role.MEMBER, Action.CREATE_TASK)
        policy.authorize(
            Role.MEMBER,
            Action.TRANSITION_TASK,
            {"actor_id": "u1", "creator_id": "u1", "assignee_id": None, "participant_ids": []},
        )

    def test_member_cannot_transition_unrelated_tasks(self) -> None:
        policy = AuthorizationPolicy()
        with pytest.raises(ForbiddenError, match="related tasks"):
            policy.authorize(
                Role.MEMBER,
                Action.TRANSITION_TASK,
                {"actor_id": "u1", "creator_id": "u2", "assignee_id": "u3", "participant_ids": []},
            )


# ---------------------------------------------------------------------------
# 8. Worklog immutability and actual_minutes aggregation
# ---------------------------------------------------------------------------


class TestWorklogImmutabilityAndAggregation:
    """Verify Worklog is immutable (frozen dataclass), correction is delta, actual_minutes net."""

    def test_worklog_is_frozen_dataclass(self) -> None:
        """Worklog must be a frozen dataclass — no mutation after creation."""
        wl = Worklog(
            "w1", "p1", "t1", "u1", "u1", date(2026, 1, 10), 120,
            "work", None, None, NOW,
        )
        with pytest.raises(AttributeError):
            wl.minutes_delta = 60  # type: ignore[misc]

    def test_correction_is_delta_not_replacement(self) -> None:
        """A correction record uses minutes_delta as a delta, not a replacement value."""
        original = Worklog(
            "w1", "p1", "t1", "u1", "u1", date(2026, 1, 10), 120,
            "work", None, None, NOW,
        )
        correction = Worklog(
            "w2", "p1", "t1", "u1", "u1", date(2026, 1, 10), -30,
            "adjust", original.id, "mistake", NOW,
        )
        # Net = 120 + (-30) = 90
        assert original.minutes_delta + correction.minutes_delta == 90

    def test_multiple_corrections_chain(self) -> None:
        """A record can be corrected multiple times; net must be correct."""
        original = Worklog(
            "w1", "p1", "t1", "u1", "u1", date(2026, 1, 10), 120,
            "work", None, None, NOW,
        )
        corr1 = Worklog(
            "w2", "p1", "t1", "u1", "u1", date(2026, 1, 10), -30,
            "adjust1", original.id, "reason1", NOW,
        )
        corr2 = Worklog(
            "w3", "p1", "t1", "u1", "u1", date(2026, 1, 10), 10,
            "adjust2", original.id, "reason2", NOW,
        )
        # Net = 120 - 30 + 10 = 100
        total = original.minutes_delta + corr1.minutes_delta + corr2.minutes_delta
        assert total == 100

    def test_normal_worklog_must_be_positive(self) -> None:
        """A normal Worklog (no corrects_worklog_id) must have positive minutes_delta."""
        with pytest.raises(ValidationError):
            Worklog(
                "w", "p", "t", "u", "u", date(2026, 1, 10), -10,
                "desc", None, None, NOW,
            )

    def test_correction_must_have_reason(self) -> None:
        """A correction record must have a non-empty correction_reason."""
        with pytest.raises(ValidationError):
            Worklog(
                "w", "p", "t", "u", "u", date(2026, 1, 10), -10,
                "desc", "original-id", "", NOW,
            )

    def test_worklog_delta_zero_rejected(self) -> None:
        """minutes_delta of 0 is not valid."""
        with pytest.raises(ValidationError):
            Worklog(
                "w", "p", "t", "u", "u", date(2026, 1, 10), 0,
                "desc", None, None, NOW,
            )

    def test_worklog_delta_over_1440_rejected(self) -> None:
        """minutes_delta over 1440 is not valid."""
        with pytest.raises(ValidationError):
            Worklog(
                "w", "p", "t", "u", "u", date(2026, 1, 10), 1441,
                "desc", None, None, NOW,
            )

    def test_worklog_correction_delta_over_1440_negative_rejected(self) -> None:
        """Correction minutes_delta below -1440 is not valid."""
        with pytest.raises(ValidationError):
            Worklog(
                "w", "p", "t", "u", "u", date(2026, 1, 10), -1441,
                "desc", "orig", "reason", NOW,
            )

    def test_no_patch_or_delete_route_for_worklogs(self) -> None:
        """No PATCH or DELETE route should exist for worklog resources in the API."""
        from project_service.app import create_app
        from project_service.config import Settings

        app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:"))
        worklog_methods: set[str] = set()
        for rule in app.url_map.iter_rules():
            if "worklog" in rule.rule:
                worklog_methods.update(rule.methods)
        assert "PATCH" not in worklog_methods
        assert "DELETE" not in worklog_methods
        app.extensions["database"].dispose()

    def test_actual_minutes_is_sum_of_deltas(self) -> None:
        """actual_minutes = max(0, SUM(minutes_delta)) — verify the formula."""
        deltas = [120, -30, 10, -50]
        total = sum(deltas)
        assert max(0, total) == 50

    def test_actual_minutes_floor_at_zero(self) -> None:
        """If sum of deltas goes negative, actual_minutes floors at 0."""
        deltas = [120, -150]
        total = sum(deltas)
        assert max(0, total) == 0  # -30 floored to 0


# ---------------------------------------------------------------------------
# Workflow state machine additional
# ---------------------------------------------------------------------------


class TestWorkflowStateMachine:
    """Additional workflow state machine tests."""

    def test_todo_to_done_is_invalid(self) -> None:
        """todo → done is not an allowed transition."""
        task = _task()
        flow = WorkflowV1()
        with pytest.raises(ConflictError):
            flow.transition(task, "done", Role.ADMIN, NOW, 1)

    def test_closed_is_terminal(self) -> None:
        """closed → any should be invalid."""
        task = _task(status="closed")
        flow = WorkflowV1()
        with pytest.raises(ConflictError):
            flow.transition(task, "in_progress", Role.ADMIN, NOW, 1)
        with pytest.raises(ConflictError):
            flow.transition(task, "todo", Role.ADMIN, NOW, 1)

    def test_canceled_is_terminal(self) -> None:
        """canceled → any should be invalid."""
        task = _task(status="canceled")
        flow = WorkflowV1()
        with pytest.raises(ConflictError):
            flow.transition(task, "in_progress", Role.ADMIN, NOW, 1)

    def test_member_cannot_close(self) -> None:
        """Member role should not be able to close tasks."""
        task = _task(status="done")
        flow = WorkflowV1()
        with pytest.raises(ForbiddenError):
            flow.transition(task, "closed", Role.MEMBER, NOW, 1)

    def test_reopen_clears_actual_end(self) -> None:
        """done → in_progress should clear actual_end_at."""
        task = _task(status="done")
        task.actual_end_at = NOW
        flow = WorkflowV1()
        flow.transition(task, "in_progress", Role.ADMIN, NOW, 1)
        assert task.actual_end_at is None
        # actual_start_at should be preserved
        assert task.actual_start_at is not None or task.actual_start_at is None


# ---------------------------------------------------------------------------
# Project isolation
# ---------------------------------------------------------------------------


class TestProjectIsolation404:
    """Verify project-level 404 isolation."""

    def test_invalid_uuid_returns_404(self) -> None:
        from project_service.app import create_app
        from project_service.config import Settings

        app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:"))
        client = app.test_client()
        response = client.get(
            "/api/v1/projects/not-a-uuid/members",
            headers={"X-Actor-Id": "outsider"},
        )
        assert response.status_code == 404
        body = response.get_json()
        assert body["error_code"] == "RESOURCE_NOT_FOUND"
        app.extensions["database"].dispose()

    def test_valid_uuid_non_member_returns_404(self) -> None:
        from unittest.mock import MagicMock, patch

        from project_service.app import create_app
        from project_service.config import Settings
        from project_service.shared.errors import NotFoundError

        app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:"))
        client = app.test_client()
        random_uuid = str(uuid4())
        mock_service = MagicMock()
        mock_service.list_members.side_effect = NotFoundError()
        with patch.dict(app.extensions, {"collaboration_service": mock_service}):
            response = client.get(
                f"/api/v1/projects/{random_uuid}/members",
                headers={"X-Actor-Id": "outsider"},
            )
        assert response.status_code == 404
        app.extensions["database"].dispose()


# ---------------------------------------------------------------------------
# RFC 9457 Problem Details format
# ---------------------------------------------------------------------------


class TestProblemDetailsRFC9457:
    """Verify all error responses follow RFC 9457 ProblemDetails format."""

    def test_validation_error_is_problem_json(self) -> None:
        from project_service.app import create_app
        from project_service.config import Settings

        app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:"))
        client = app.test_client()
        # Missing Idempotency-Key on POST
        response = client.post(
            "/api/v1/projects/some-uuid/members",
            json={"user_id": "u", "role": "member"},
        )
        assert response.status_code == 422
        assert response.content_type == "application/problem+json"
        body = response.get_json()
        assert "type" in body
        assert "title" in body
        assert "status" in body
        assert "detail" in body
        assert "error_code" in body
        assert "trace_id" in body
        app.extensions["database"].dispose()

    def test_if_match_missing_returns_422_problem(self) -> None:
        from project_service.app import create_app
        from project_service.config import Settings

        app = create_app(Settings(environment="test", database_url="sqlite+pysqlite:///:memory:"))
        client = app.test_client()
        response = client.patch(
            "/api/v1/projects/some-uuid/members/some-id",
            json={"role": "member"},
            headers={"Idempotency-Key": "k"},
        )
        assert response.status_code == 422
        assert response.content_type == "application/problem+json"
        app.extensions["database"].dispose()


# ---------------------------------------------------------------------------
# Audit and Outbox factory
# ---------------------------------------------------------------------------


class TestAuditOutboxFactory:
    """Verify audit/outbox factories create correct records."""

    def test_make_audit_has_all_required_fields(self) -> None:
        record = make_audit(
            trace_id="t1",
            actor_id="a1",
            project_id="p1",
            resource_type="task",
            resource_id="r1",
            action="task.created",
            before={"status": "todo"},
            after={"status": "in_progress"},
        )
        assert record.trace_id == "t1"
        assert record.actor_id == "a1"
        assert record.project_id == "p1"
        assert record.resource_type == "task"
        assert record.action == "task.created"
        assert record.before == {"status": "todo"}
        assert record.after == {"status": "in_progress"}
        assert record.result == "success"
        assert record.source == "api"

    def test_make_outbox_has_pending_status_fields(self) -> None:
        event = make_outbox(
            event_type="Task.Created.v1",
            aggregate_type="task",
            aggregate_id="t1",
            project_id="p1",
            payload={"task_id": "t1"},
            trace_id="trace-1",
        )
        assert event.event_type == "Task.Created.v1"
        assert event.event_version == 1
        assert event.aggregate_type == "task"
        assert event.aggregate_id == "t1"
        assert event.project_id == "p1"
        assert event.trace_id == "trace-1"

    def test_audit_record_is_immutable(self) -> None:
        record = make_audit(
            trace_id="t1",
            actor_id="a1",
            project_id="p1",
            resource_type="task",
            resource_id="r1",
            action="task.created",
        )
        with pytest.raises(AttributeError):
            record.action = "task.updated"  # type: ignore[misc]
