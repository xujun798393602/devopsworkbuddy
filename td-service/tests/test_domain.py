"""TD aggregate state-machine tests."""
from uuid import uuid4

import pytest

from td_service.domain import Defect, DefectStatus, DomainError, FixEvidence, VerificationEvidence


def make_defect(**overrides: object) -> Defect:
    values: dict[str, object] = {
        "id": uuid4(),
        "project_id": uuid4(),
        "business_no": "TD-1",
        "title": "Login fails",
        "description": "User cannot sign in",
        "severity": "major",
        "priority": "p2",
        "defect_type": "functional",
        "reporter_id": uuid4(),
        "expected_result": "Login succeeds",
        "actual_result": "An error is shown",
        "reproduction_steps": ("Open login", "Submit credentials"),
    }
    values.update(overrides)
    return Defect(**values)  # type: ignore[arg-type]


def test_fix_and_human_verification_require_evidence() -> None:
    defect = make_defect()
    assignee = uuid4()
    verifier = uuid4()
    defect.transition("assign", uuid4(), assignee_id=assignee)
    defect.transition("start", assignee)
    defect.transition(
        "mark_fixed",
        assignee,
        fix_version_id=uuid4(),
        fix_evidence=FixEvidence("commit", "abc123", "Null guard"),
    )
    defect.transition("submit_verification", assignee, verifier_id=verifier)
    defect.transition(
        "verify_close",
        verifier,
        verification=VerificationEvidence("staging", "passed", ("run-42",)),
        root_cause="Missing null check",
    )
    assert defect.status is DefectStatus.CLOSED
    assert defect.sla is not None and defect.sla.resolved_at is not None
    assert [entry["sequence_no"] for entry in defect.history] == [1, 2, 3, 4, 5]


def test_duplicate_chain_rejects_cycle() -> None:
    defect = make_defect()
    master_id = uuid4()
    with pytest.raises(DomainError, match="cycle") as captured:
        defect.transition(
            "mark_duplicate",
            uuid4(),
            privileged=True,
            duplicate_of_id=master_id,
            duplicate_ancestors={master_id, defect.id},
            reason="Same root issue",
        )
    assert captured.value.code == "DUPLICATE_CYCLE"


def test_high_severity_requires_reproduction_steps() -> None:
    with pytest.raises(DomainError) as captured:
        make_defect(severity="critical", reproduction_steps=())
    assert captured.value.code == "REPRODUCTION_REQUIRED"
