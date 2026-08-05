"""Test management domain tests."""
from uuid import uuid4

import pytest

from tp_service.domain import (
    DomainError,
    deterministic_mock,
)
from tp_service.domain import (
    TestCase as Case,
)
from tp_service.domain import (
    TestCaseVersion as CaseVersion,
)
from tp_service.domain import (
    TestEnvironment as Environment,
)
from tp_service.domain import (
    TestExecution as Execution,
)
from tp_service.domain import (
    TestReport as Report,
)
from tp_service.domain import (
    TestStep as Step,
)


def test_case_versions_are_immutable_and_publishable() -> None:
    case = Case(uuid4(), uuid4(), "TP-1", uuid4(), "Login", uuid4(), requirement_refs=(uuid4(),))
    version = CaseVersion.create(case.id, 1, [Step(1, "Submit", "Dashboard")], "manual")
    case.publish(version)
    assert case.current_version_id == version.id
    assert case.status == "active"


def test_execution_rerun_appends_attempt_and_report_uses_latest() -> None:
    case_ref = uuid4()
    execution = Execution(uuid4(), uuid4(), uuid4(), uuid4(), uuid4())
    execution.start((case_ref,))
    execution.attempts[case_ref][-1].transition("running")
    execution.attempts[case_ref][-1].transition("failed", "Timeout")
    retry = execution.rerun(case_ref)
    retry.transition("running")
    retry.transition("passed")
    report = Report.publish(execution, uuid4())
    assert [run.attempt_no for run in execution.attempts[case_ref]] == [1, 2]
    assert report.summary["passed"] == 1
    assert report.summary["failed"] == 0


def test_mock_is_explicit_and_deterministic() -> None:
    first = deterministic_mock("analysis", {"requirement": "REQ-1"})
    second = deterministic_mock("analysis", {"requirement": "REQ-1"})
    assert first == second
    assert b'"provider":"mock"' in first


def test_environment_rejects_secret_variable_names() -> None:
    with pytest.raises(DomainError) as captured:
        Environment(uuid4(), uuid4(), "Staging", "https://staging.example", ("API_TOKEN",))
    assert captured.value.code == "SECRET_METADATA_FORBIDDEN"
