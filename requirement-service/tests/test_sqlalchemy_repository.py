"""Production persistence tests for requirement-service."""
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from requirement_service.config import Config
from requirement_service.domain import Baseline, ChangeRequest, ReviewRound
from requirement_service.persistence import (
    Base,
    IdempotencyRow,
    OutboxRow,
    RequirementRevisionRow,
    RequirementRow,
)
from requirement_service.repository import AllowAllAuthorizer, SqlAlchemyUnitOfWork
from requirement_service.service import RequirementService


def test_sqlalchemy_uow_persists_aggregate_revision_outbox_and_idempotency() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    project_id = uuid4()
    actor_id = uuid4()
    with Session(engine, expire_on_commit=False) as session:
        uow = SqlAlchemyUnitOfWork(session)
        service = RequirementService(uow, AllowAllAuthorizer())
        requirement = service.create(
            actor_id,
            project_id,
            {
                "title": "Checkout",
                "type": "user_story",
                "owner_id": str(uuid4()),
                "release_version_id": str(uuid4()),
                "acceptance_criteria": [{"id": "ac-1"}],
            },
        )
        uow.save_idempotency(
            str(project_id), "actor", "once", "hash", {"id": "response"}, 201
        )
        uow.commit()

    with Session(engine) as session:
        assert session.get(RequirementRow, str(requirement.id)) is not None
        assert session.scalar(select(OutboxRow)) is not None
        assert session.get(
            IdempotencyRow, (str(project_id), "actor", "once")
        ) is not None
        loaded = SqlAlchemyUnitOfWork(session).requirements.get(
            (project_id, requirement.id)
        )
        assert loaded is not None
        assert loaded.title == "Checkout"


def test_governance_round_trip_is_project_scoped_and_revision_is_append_only() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()
    reviewer_id = uuid4()
    with Session(engine, expire_on_commit=False) as session:
        uow = SqlAlchemyUnitOfWork(session)
        requirement = RequirementService(uow, AllowAllAuthorizer()).create(
            actor_id,
            project_id,
            {
                "title": "Govern checkout",
                "type": "user_story",
                "owner_id": str(uuid4()),
                "release_version_id": str(uuid4()),
                "acceptance_criteria": [{"id": "ac-1"}],
            },
        )
        revision = uow.revisions[requirement.id][0]
        review = ReviewRound(
            uuid4(), 1, revision.id, actor_id, (reviewer_id,)
        )
        review.decide(reviewer_id, "approved", "complete")
        review.close()
        baseline = Baseline(
            uuid4(),
            project_id,
            "BL-1",
            requirement.release_version_id,
            ((revision.id, revision.content_hash),),
        )
        baseline.activate()
        change = ChangeRequest(
            uuid4(), requirement.id, revision.id, {"title": "Govern checkout v2"}
        )
        change.transition("submit")
        uow.reviews[review.id] = review
        uow.baselines[(project_id, baseline.id)] = baseline
        uow.change_requests[(project_id, change.id)] = change
        uow.save_idempotency(
            str(project_id), str(actor_id), "governance", "f" * 64,
            {"data": {"id": str(change.id)}}, 201,
        )
        uow.outbox.append(
            {
                "event_type": "Requirement.ChangeRequested",
                "project_id": str(project_id),
                "requirement_id": str(requirement.id),
            }
        )
        uow.commit()

    with Session(engine) as session:
        restarted = SqlAlchemyUnitOfWork(session)
        assert restarted.reviews[review.id].decisions[0]["comments"] == "complete"
        assert restarted.baselines[(project_id, baseline.id)].revision_refs == baseline.revision_refs
        assert restarted.change_requests[(project_id, change.id)].status == "in_review"
        assert (other_project_id, baseline.id) not in restarted.baselines
        assert restarted.requirements.get((other_project_id, requirement.id)) is None
        assert restarted.get_idempotency(
            str(project_id), str(actor_id), "governance"
        ) is not None
        assert restarted.get_idempotency(
            str(other_project_id), str(actor_id), "governance"
        ) is None
        with pytest.raises(TypeError, match="append-only"):
            del restarted.revisions[requirement.id]
        assert session.scalar(select(RequirementRevisionRow)) is not None
        assert session.scalar(select(OutboxRow)) is not None


def test_config_fails_closed_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        Config.from_env()
