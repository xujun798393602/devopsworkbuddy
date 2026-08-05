"""TP planning, execution, reporting and automation domain models."""
from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4
from xml.etree import ElementTree

from tp_service.domain import CaseRun, DomainError, TestExecution, TestReport

MAX_RESULT_BYTES = 10 * 1024 * 1024
MAX_RESULTS = 10_000
MAX_RESULT_TEXT = 20_000


@dataclass(frozen=True, slots=True)
class PlanScopeSnapshot:
    """Immutable requirement/case/environment scope captured at ready."""

    requirement_ref: UUID
    requirement_revision: int
    requirement_hash: str
    case_version_ref: UUID
    environment_id: UUID


@dataclass(slots=True)
class ManagedPlan:
    """Plan head with an immutable ready-time scope."""

    id: UUID
    project_id: UUID
    business_no: str
    owner_id: UUID
    status: str = "draft"
    scope: tuple[PlanScopeSnapshot, ...] = ()
    scope_hash: str = ""
    version: int = 1

    def freeze(self, scope: tuple[PlanScopeSnapshot, ...], valid_case_versions: set[UUID]) -> None:
        """Freeze a complete and currently valid scope."""
        if self.status != "draft" or not scope:
            raise DomainError("PLAN_NOT_FREEZABLE", "Only a draft plan with scope can become ready")
        requirements = {item.requirement_ref for item in scope}
        covered = {item.requirement_ref for item in scope if item.case_version_ref in valid_case_versions}
        if requirements != covered or any(item.requirement_revision < 1 or len(item.requirement_hash) != 64 for item in scope):
            raise DomainError("PLAN_SCOPE_INCOMPLETE", "Every requirement needs a valid immutable case version", 422)
        canonical = json.dumps(
            [
                {
                    "requirement_ref": str(item.requirement_ref),
                    "requirement_revision": item.requirement_revision,
                    "requirement_hash": item.requirement_hash,
                    "case_version_ref": str(item.case_version_ref),
                    "environment_id": str(item.environment_id),
                }
                for item in scope
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        self.scope = scope
        self.scope_hash = hashlib.sha256(canonical).hexdigest()
        self.status = "ready"
        self.version += 1

    def replace_scope(self, scope: tuple[PlanScopeSnapshot, ...]) -> None:
        """Allow draft editing but never mutate a frozen snapshot."""
        if self.status != "draft":
            raise DomainError("PLAN_SCOPE_FROZEN", "Ready plan scope is immutable")
        self.scope = scope
        self.version += 1

    def transition(self, target: str) -> None:
        """Apply the fixed plan lifecycle."""
        allowed = {
            ("ready", "in_progress"),
            ("in_progress", "completed"),
            ("completed", "closed"),
            ("draft", "canceled"),
            ("ready", "canceled"),
            ("in_progress", "canceled"),
        }
        if (self.status, target) not in allowed:
            raise DomainError("INVALID_PLAN_TRANSITION", f"Cannot move plan from {self.status} to {target}")
        self.status = target
        self.version += 1


@dataclass(frozen=True, slots=True)
class ManagedEnvironment:
    """Environment metadata containing references but no secrets."""

    id: UUID
    project_id: UUID
    name: str
    classification: str
    base_url: str
    configuration_summary: str = ""
    variable_keys: tuple[str, ...] = ()
    secret_ref_count: int = 0

    def __post_init__(self) -> None:
        if self.classification not in {"development", "test", "staging", "production"}:
            raise DomainError("INVALID_ENVIRONMENT", "Unsupported environment classification", 422)
        if not self.name.strip() or not self.base_url.startswith(("http://", "https://")):
            raise DomainError("INVALID_ENVIRONMENT", "Environment name and HTTP(S) URL are required", 422)
        if len(self.configuration_summary.encode()) > 8 * 1024 or self.secret_ref_count < 0:
            raise DomainError("INVALID_ENVIRONMENT", "Environment summary or secret reference count is invalid", 422)
        if any(any(word in key.casefold() for word in ("secret", "token", "password")) for key in self.variable_keys):
            raise DomainError("SECRET_METADATA_FORBIDDEN", "Secret-like variable names are forbidden", 422)


@dataclass(slots=True)
class ManagedExecution:
    """Execution whose case result history is append-only."""

    aggregate: TestExecution
    round_no: int

    def transition_attempt(self, case_version_ref: UUID, result: str, actual_result: str = "") -> CaseRun:
        """Transition only the latest attempt; terminal attempts cannot be overwritten."""
        attempts = self.aggregate.attempts.get(case_version_ref)
        if not attempts:
            raise DomainError("CASE_RUN_NOT_FOUND", "Case version is not in this execution", 404)
        latest = attempts[-1]
        latest.transition(result, actual_result)
        self.aggregate.version += 1
        return latest

    def correct_terminal(self, case_version_ref: UUID, result: str, actual_result: str = "") -> CaseRun:
        """Correct a terminal outcome by appending attempt N+1."""
        attempt = self.aggregate.rerun(case_version_ref)
        attempt.transition("running")
        attempt.transition(result, actual_result)
        return attempt


@dataclass(frozen=True, slots=True)
class PublishedReport:
    """Immutable published report revision."""

    report: TestReport
    project_id: UUID
    revision: int


@dataclass(frozen=True, slots=True)
class AutomationAsset:
    id: UUID
    project_id: UUID
    name: str
    repository_ref: str
    case_version_ref: UUID | None = None


@dataclass(frozen=True, slots=True)
class AutomationSuite:
    id: UUID
    project_id: UUID
    name: str
    asset_ids: tuple[UUID, ...]


@dataclass(slots=True)
class AutomationTask:
    id: UUID
    project_id: UUID
    suite_id: UUID
    environment_id: UUID
    status: str = "queued"
    external_run_ref: str = ""
    version: int = 1

    def transition(self, target: str, external_run_ref: str = "") -> None:
        allowed = {("queued", "running"), ("running", "completed"), ("running", "failed"), ("queued", "canceled")}
        if (self.status, target) not in allowed:
            raise DomainError("INVALID_AUTOMATION_TASK_TRANSITION", "Automation task transition is invalid")
        if target in {"completed", "failed"} and not external_run_ref.strip():
            raise DomainError("EXTERNAL_RUN_REF_REQUIRED", "Terminal automation task needs an external run reference", 422)
        self.status = target
        self.external_run_ref = external_run_ref or self.external_run_ref
        self.version += 1


@dataclass(frozen=True, slots=True)
class AutomationResultItem:
    external_case_ref: str
    status: str
    case_version_ref: UUID | None
    duration_ms: int
    message: str = ""


@dataclass(frozen=True, slots=True)
class AutomationIngestion:
    id: UUID
    project_id: UUID
    source: str
    external_run_ref: str
    payload_hash: str
    items: tuple[AutomationResultItem, ...]

    @property
    def summary(self) -> dict[str, int]:
        statuses = ("passed", "failed", "skipped", "unknown", "unmapped")
        return {status: sum(item.status == status for item in self.items) for status in statuses}


def _bounded_text(value: object) -> str:
    text = str(value or "")
    if len(text) > MAX_RESULT_TEXT:
        raise DomainError("AUTOMATION_TEXT_TOO_LONG", "Automation result text exceeds limit", 422)
    return text


def _map_item(item: dict[str, Any], mappings: dict[str, UUID]) -> AutomationResultItem:
    external_ref = _bounded_text(item.get("external_case_ref"))
    status = str(item.get("status", "unknown")).casefold()
    if status not in {"passed", "failed", "skipped", "unknown"}:
        status = "unknown"
    case_ref = mappings.get(external_ref)
    if case_ref is None:
        status = "unmapped"
    duration = item.get("duration_ms", 0)
    if not isinstance(duration, int) or duration < 0:
        raise DomainError("INVALID_AUTOMATION_RESULT", "Duration must be a non-negative integer", 422)
    return AutomationResultItem(external_ref, status, case_ref, duration, _bounded_text(item.get("message")))


def ingest_automation_json(
    project_id: UUID,
    payload: bytes,
    mappings: dict[str, UUID],
    prior: AutomationIngestion | None = None,
) -> AutomationIngestion:
    """Parse strict bounded JSON with source/run/hash idempotency."""
    if len(payload) > MAX_RESULT_BYTES:
        raise DomainError("PAYLOAD_TOO_LARGE", "Automation payload exceeds 10 MiB", 413)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise DomainError("INVALID_AUTOMATION_RESULT", "Malformed automation JSON", 422) from error
    if not isinstance(data, dict) or set(data) != {"source", "external_run_ref", "results"}:
        raise DomainError("INVALID_AUTOMATION_RESULT", "Automation JSON shape is invalid", 422)
    results = data["results"]
    if not isinstance(results, list) or len(results) > MAX_RESULTS or not all(isinstance(item, dict) for item in results):
        raise DomainError("INVALID_AUTOMATION_RESULT", "Automation results exceed schema limits", 422)
    source = _bounded_text(data["source"])
    run_ref = _bounded_text(data["external_run_ref"])
    if not source or not run_ref:
        raise DomainError("INVALID_AUTOMATION_RESULT", "Source and external run reference are required", 422)
    digest = hashlib.sha256(payload).hexdigest()
    if (
        prior is not None
        and prior.project_id == project_id
        and prior.source == source
        and prior.external_run_ref == run_ref
    ):
        if prior.payload_hash != digest:
            raise DomainError(
                "INGESTION_PAYLOAD_CONFLICT",
                "Run reference already has another payload",
            )
        return prior
    return AutomationIngestion(uuid4(), project_id, source, run_ref, digest, tuple(_map_item(item, mappings) for item in results))


def ingest_junit_xml(
    project_id: UUID,
    payload: bytes,
    source: str,
    external_run_ref: str,
    mappings: dict[str, UUID],
    prior: AutomationIngestion | None = None,
) -> AutomationIngestion:
    """Parse bounded JUnit XML without DTD, entities or external references."""
    if len(payload) > MAX_RESULT_BYTES:
        raise DomainError("PAYLOAD_TOO_LARGE", "JUnit payload exceeds 10 MiB", 413)
    lowered = payload[:4096].lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered or b"system" in lowered:
        raise DomainError("UNSAFE_JUNIT_XML", "DTD, entities and external references are forbidden", 422)
    try:
        root = ElementTree.parse(io.BytesIO(payload)).getroot()
    except Exception as error:
        raise DomainError("INVALID_JUNIT_XML", "Malformed JUnit XML", 422) from error
    cases = list(root.iter("testcase"))
    if len(cases) > MAX_RESULTS:
        raise DomainError("INVALID_JUNIT_XML", "JUnit test count exceeds 10000", 422)
    raw_items: list[dict[str, Any]] = []
    for case in cases:
        external_ref = _bounded_text(case.attrib.get("name", ""))
        duration_ms = int(float(case.attrib.get("time", "0")) * 1000)
        failure = next(iter(case.findall("failure")), None) or next(iter(case.findall("error")), None)
        skipped = next(iter(case.findall("skipped")), None)
        status = "failed" if failure is not None else "skipped" if skipped is not None else "passed"
        raw_items.append({"external_case_ref": external_ref, "status": status, "duration_ms": duration_ms, "message": _bounded_text(failure.text if failure is not None else "")})
    canonical = json.dumps({"source": source, "external_run_ref": external_run_ref, "results": raw_items}, sort_keys=True, separators=(",", ":")).encode()
    return ingest_automation_json(project_id, canonical, mappings, prior)


__all__ = [
    "AutomationAsset",
    "AutomationIngestion",
    "AutomationSuite",
    "AutomationTask",
    "ManagedEnvironment",
    "ManagedExecution",
    "ManagedPlan",
    "PlanScopeSnapshot",
    "PublishedReport",
    "ingest_automation_json",
    "ingest_junit_xml",
]
