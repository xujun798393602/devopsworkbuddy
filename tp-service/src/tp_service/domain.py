"""Test management domain models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class DomainError(ValueError):
    def __init__(self, code: str, detail: str, status: int = 409) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


@dataclass(slots=True)
class TestFolder:
    id: UUID
    project_id: UUID
    name: str
    parent_id: UUID | None = None
    version: int = 1

    def move(self, target: TestFolder | None, descendant_ids: set[UUID]) -> None:
        """Move within one project without forming a folder cycle."""
        if target and target.project_id != self.project_id:
            raise DomainError("RESOURCE_NOT_FOUND", "Target folder is not visible", 404)
        if target and (target.id == self.id or target.id in descendant_ids):
            raise DomainError("FOLDER_CYCLE", "Folder cannot be moved below itself")
        self.parent_id = target.id if target else None
        self.version += 1


@dataclass(frozen=True, slots=True)
class TestStep:
    sequence: int
    action: str
    expected: str
    test_data: str = ""

    def __post_init__(self) -> None:
        if not 1 <= self.sequence <= 500 or not self.action.strip() or not self.expected.strip():
            raise DomainError("INVALID_TEST_STEP", "Test step is invalid", 422)


@dataclass(frozen=True, slots=True)
class TestCaseVersion:
    id: UUID
    case_id: UUID
    version_no: int
    content_hash: str
    steps: tuple[TestStep, ...]
    source: str

    @classmethod
    def create(cls, case_id: UUID, version: int, steps: list[TestStep], source: str) -> TestCaseVersion:
        if source not in {"design", "manual", "import", "automation"}:
            raise DomainError("INVALID_CASE_SOURCE", "Unsupported case source", 422)
        payload = [
            {"sequence": s.sequence, "action": s.action, "expected": s.expected, "test_data": s.test_data}
            for s in steps
        ]
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return cls(uuid4(), case_id, version, digest, tuple(steps), source)


class SessionStatus(StrEnum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    ANALYSIS_REVIEW = "analysis_review"
    DESIGNING = "designing"
    DESIGN_REVIEW = "design_review"
    GENERATING_CASES = "generating_cases"
    CASES_REVIEW = "cases_review"
    READY_TO_IMPORT = "ready_to_import"
    IMPORTED = "imported"
    FAILED = "failed"
    CANCELED = "canceled"


_STAGE_FLOW = {
    "analysis": (SessionStatus.DRAFT, SessionStatus.ANALYZING, SessionStatus.ANALYSIS_REVIEW),
    "design": (SessionStatus.ANALYSIS_REVIEW, SessionStatus.DESIGNING, SessionStatus.DESIGN_REVIEW),
    "cases": (SessionStatus.DESIGN_REVIEW, SessionStatus.GENERATING_CASES, SessionStatus.CASES_REVIEW),
}


@dataclass(slots=True)
class StageRun:
    id: UUID
    stage: str
    attempt: int
    input_hash: str
    status: str = "queued"
    provider: str = "mock"
    output_hash: str = ""
    adapter_key: str = "deterministic-mock"
    model_version: str = "mock-v1"
    prompt_version: str = "v1"

    def complete(self, output: bytes) -> None:
        self.output_hash = hashlib.sha256(output).hexdigest()
        self.status = "completed"


@dataclass(frozen=True, slots=True)
class ReviewGate:
    """Immutable human review decision attached to a stage run."""

    id: UUID
    stage_run_id: UUID
    reviewer_id: UUID
    decision: str
    privileged_exception: bool
    comments: str
    created_at: datetime


@dataclass(slots=True)
class DesignSession:
    id: UUID
    project_id: UUID
    created_by: UUID
    requirement_snapshot_refs: tuple[str, ...]
    target_folder_id: UUID
    status: SessionStatus = SessionStatus.DRAFT
    version: int = 1
    runs: list[StageRun] = field(default_factory=list)
    approved_stages: set[str] = field(default_factory=set)
    review_gates: list[ReviewGate] = field(default_factory=list)

    def start_stage(self, stage: str, input_hash: str) -> StageRun:
        """Queue the next deterministic stage only after the prior human gate."""
        flow = _STAGE_FLOW.get(stage)
        if flow is None or self.status != flow[0]:
            raise DomainError("GATE_REQUIRED", "Previous human gate is required")
        self.status = flow[1]
        self.version += 1
        run = StageRun(uuid4(), stage, 1 + sum(item.stage == stage for item in self.runs), input_hash)
        self.runs.append(run)
        return run

    def complete_stage(self, run: StageRun, output: bytes) -> None:
        flow = _STAGE_FLOW[run.stage]
        run.complete(output)
        self.status = flow[2]
        self.version += 1

    def apply_gate(
        self,
        stage: str,
        reviewer_id: UUID,
        decision: str,
        privileged: bool = False,
        comments: str = "",
        created_at: datetime | None = None,
    ) -> ReviewGate:
        """Append a complete human review fact and advance an approved stage."""
        if reviewer_id == self.created_by and not privileged:
            raise DomainError("SELF_GATE_FORBIDDEN", "A different human reviewer is required", 403)
        flow = _STAGE_FLOW[stage]
        if self.status != flow[2] or decision != "approved":
            raise DomainError("GATE_REJECTED", "Stage cannot advance without approval")
        run = next(
            (item for item in reversed(self.runs) if item.stage == stage and item.status == "completed"),
            None,
        )
        if run is None:
            raise DomainError("STAGE_RUN_NOT_REVIEWABLE", "A completed stage run is required")
        gate = ReviewGate(
            uuid4(),
            run.id,
            reviewer_id,
            decision,
            privileged,
            comments.strip(),
            created_at or datetime.now(UTC),
        )
        self.review_gates.append(gate)
        self.approved_stages.add(stage)
        self.status = {
            "analysis": SessionStatus.ANALYSIS_REVIEW,
            "design": SessionStatus.DESIGN_REVIEW,
            "cases": SessionStatus.READY_TO_IMPORT,
        }[stage]
        self.version += 1
        return gate

    def mark_imported(self) -> None:
        if self.status != SessionStatus.READY_TO_IMPORT or self.approved_stages != {"analysis", "design", "cases"}:
            raise DomainError("GATE_REQUIRED", "Every generated artifact requires a human gate")
        self.status = SessionStatus.IMPORTED
        self.version += 1


@dataclass(slots=True)
class TestPlan:
    id: UUID
    case_version_refs: tuple[UUID, ...]
    requirement_refs: tuple[UUID, ...]
    status: str = "draft"
    frozen_scope_hash: str = ""
    version: int = 1

    def freeze(self, coverage: dict[UUID, set[UUID]]) -> None:
        if self.status != "draft" or any(not coverage.get(req) for req in self.requirement_refs):
            raise DomainError("PLAN_SCOPE_INCOMPLETE", "Every requirement needs a case")
        canonical = sorted(map(str, self.case_version_refs + self.requirement_refs))
        self.frozen_scope_hash = hashlib.sha256("|".join(canonical).encode()).hexdigest()
        self.status = "ready"
        self.version += 1


@dataclass(slots=True)
class CaseRun:
    id: UUID
    case_version_ref: UUID
    attempt_no: int = 1
    status: str = "not_run"
    actual_result: str = ""
    version: int = 1

    def transition(self, result: str, actual_result: str = "") -> None:
        allowed = {
            ("not_run", "running"),
            ("running", "passed"),
            ("running", "failed"),
            ("running", "blocked"),
            ("running", "skipped"),
        }
        if (self.status, result) not in allowed or result in {"failed", "blocked"} and not actual_result.strip():
            raise DomainError("INVALID_CASE_RUN_TRANSITION", "Case result transition is invalid")
        self.status, self.actual_result = result, actual_result
        self.version += 1

    def rerun(self) -> CaseRun:
        if self.status not in {"passed", "failed", "blocked", "skipped"}:
            raise DomainError("RERUN_NOT_ALLOWED", "Only terminal attempts can be rerun")
        return CaseRun(uuid4(), self.case_version_ref, self.attempt_no + 1)


@dataclass(slots=True)
class ResultIngestion:
    source: str
    external_run_ref: str
    payload_hash: str
    results: tuple[dict[str, Any], ...]


@dataclass(slots=True)
class TestCase:
    """Mutable case head pointing to immutable case versions."""

    id: UUID
    project_id: UUID
    business_no: str
    folder_id: UUID
    title: str
    owner_id: UUID
    type: str = "functional"
    priority: str = "p2"
    status: str = "draft"
    automation_mode: str = "manual"
    current_version_id: UUID | None = None
    requirement_refs: tuple[UUID, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        if self.type not in {"functional", "api", "ui", "android", "android_tv", "other"}:
            raise DomainError("INVALID_CASE_TYPE", "Unsupported case type", 422)
        if self.priority not in {"p0", "p1", "p2", "p3"}:
            raise DomainError("INVALID_CASE_PRIORITY", "Unsupported case priority", 422)
        if self.automation_mode not in {"manual", "automated", "candidate"} or not self.title.strip():
            raise DomainError("INVALID_TEST_CASE", "Case title or automation mode is invalid", 422)

    def publish(self, case_version: TestCaseVersion) -> None:
        """Activate a validated immutable version."""
        if case_version.case_id != self.id or not case_version.steps:
            raise DomainError("INVALID_CASE_VERSION", "A non-empty version for this case is required", 422)
        self.current_version_id = case_version.id
        self.status = "active"
        self.version += 1


@dataclass(frozen=True, slots=True)
class TestEnvironment:
    """Execution environment reference without secret values."""

    id: UUID
    project_id: UUID
    name: str
    base_url: str
    variable_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.base_url.startswith(("http://", "https://")):
            raise DomainError("INVALID_ENVIRONMENT", "Environment name and HTTP(S) URL are required", 422)
        if any(
            "secret" in key.lower() or "token" in key.lower() or "password" in key.lower() for key in self.variable_keys
        ):
            raise DomainError("SECRET_METADATA_FORBIDDEN", "Environment variables may contain keys only", 422)


@dataclass(slots=True)
class TestExecution:
    """Execution aggregate whose attempts append rather than overwrite."""

    id: UUID
    project_id: UUID
    plan_id: UUID
    environment_id: UUID
    assignee_id: UUID
    status: str = "draft"
    attempts: dict[UUID, list[CaseRun]] = field(default_factory=dict)
    version: int = 1

    def start(self, case_version_refs: tuple[UUID, ...]) -> None:
        if self.status != "draft" or not case_version_refs:
            raise DomainError("EXECUTION_NOT_STARTABLE", "A draft execution with cases is required")
        self.attempts = {ref: [CaseRun(uuid4(), ref)] for ref in case_version_refs}
        self.status = "running"
        self.version += 1

    def rerun(self, case_version_ref: UUID) -> CaseRun:
        current = self.attempts.get(case_version_ref, [])
        if not current:
            raise DomainError("CASE_RUN_NOT_FOUND", "Case run is not part of the execution", 404)
        attempt = current[-1].rerun()
        current.append(attempt)
        self.version += 1
        return attempt


@dataclass(frozen=True, slots=True)
class TestReport:
    """Published immutable report snapshot."""

    id: UUID
    execution_id: UUID
    published_by: UUID
    summary: dict[str, int]
    content_hash: str

    @classmethod
    def publish(cls, execution: TestExecution, actor_id: UUID) -> TestReport:
        if execution.status not in {"running", "completed"} or not execution.attempts:
            raise DomainError("REPORT_NOT_PUBLISHABLE", "Execution has no attempts", 422)
        latest = [runs[-1] for runs in execution.attempts.values()]
        if any(run.status not in {"passed", "failed", "blocked", "skipped"} for run in latest):
            raise DomainError("REPORT_NOT_PUBLISHABLE", "Every latest attempt must be terminal", 422)
        summary = {
            status: sum(run.status == status for run in latest) for status in ("passed", "failed", "blocked", "skipped")
        }
        digest = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()
        return cls(uuid4(), execution.id, actor_id, summary, digest)


def deterministic_mock(stage: str, input_payload: dict[str, Any]) -> bytes:
    """Return stable offline AI output that is explicitly identified as mock data."""
    if stage not in _STAGE_FLOW:
        raise DomainError("INVALID_DESIGN_STAGE", "Unsupported design stage", 422)
    canonical = json.dumps(input_payload, sort_keys=True, separators=(",", ":"))
    return json.dumps(
        {
            "provider": "mock",
            "adapter_key": "deterministic-mock",
            "stage": stage,
            "input_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def ingest_json(payload: bytes, prior: ResultIngestion | None = None) -> ResultIngestion:
    """Parse bounded, strict automation JSON and enforce run/hash idempotency."""
    if len(payload) > 10 * 1024 * 1024:
        raise DomainError("PAYLOAD_TOO_LARGE", "Automation payload exceeds 10 MiB", 413)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise DomainError("INVALID_AUTOMATION_RESULT", str(error), 422) from error
    if (
        set(data) != {"source", "external_run_ref", "results"}
        or not isinstance(data["results"], list)
        or len(data["results"]) > 10_000
    ):
        raise DomainError("INVALID_AUTOMATION_RESULT", "Automation JSON shape is invalid", 422)
    digest = hashlib.sha256(payload).hexdigest()
    if prior and prior.external_run_ref == data["external_run_ref"]:
        if prior.payload_hash != digest:
            raise DomainError("INGESTION_PAYLOAD_CONFLICT", "Run reference already has another hash")
        return prior
    return ResultIngestion(str(data["source"]), str(data["external_run_ref"]), digest, tuple(data["results"]))
