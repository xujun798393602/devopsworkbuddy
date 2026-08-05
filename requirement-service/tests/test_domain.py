"""Requirement lifecycle tests."""
from uuid import uuid4

import pytest

from requirement_service.domain import DomainError, Requirement, RequirementType


def make(kind=RequirementType.USER_STORY):
    project = uuid4()
    return Requirement(uuid4(), project, "REQ-1", "Story", kind, uuid4(), uuid4(), acceptance_criteria=[{"id":"ac1","given":"g","when":"w","then":"t"}])


def test_fixed_hierarchy_and_cross_project_hiding():
    epic = make(RequirementType.EPIC)
    feature = Requirement(uuid4(), epic.project_id, "REQ-2", "Feature", RequirementType.FEATURE, uuid4(), uuid4())
    feature.set_parent(epic)
    assert feature.parent_id == epic.id
    with pytest.raises(DomainError) as caught:
        make().set_parent(epic)
    assert caught.value.code == "INVALID_REQUIREMENT_HIERARCHY"


def test_review_activation_and_completion_are_explicit():
    value = make()
    value.transition("submit_review")
    value.transition("approve", approved_review=True)
    value.transition("activate", baselined=True)
    value.transition("complete", completion_evidence=True)
    assert value.status == "completed"
