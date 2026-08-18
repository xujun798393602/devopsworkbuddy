"""Gateway BFF aggregation for the company DevOps portal dashboard.

The dashboard fans out to the six domain portal endpoints in at most two
phases: project-service first (to learn the caller's project scope), then the
remaining five in parallel. Every collector degrades to a structured zero so a
single slow or failing domain never takes down the whole homepage.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.error import URLError
from urllib.parse import quote

from gateway.singleflight import RefreshSingleFlight

logger = logging.getLogger("gateway.portal")

# Gateway-side constant mirrored by the frontend (src/api/portal.ts).
PORTAL_CROSS_PROJECT_PERMISSION = "portal:cross-project-view"
SCOPE_MINE = "mine"
SCOPE_CROSS_PROJECT = "cross-project"

# Centralised endpoint registry (test-friendly, single source of truth).
_ENDPOINTS: dict[str, str] = {
    "project": "v1/portal/projects-overview",
    "requirement": "v1/portal/requirement-summary",
    "tp": "v1/portal/tp-summary",
    "td": "v1/portal/td-summary",
    "workflow": "v1/portal/pending-approvals",
    "audit": "v1/audit-records",
    "notification": "v1/me/notifications",
}

# Hardcoded truncation limits (the browser may never supply a limit).
_PROJECT_LIMIT = 8
_REVIEW_LIMIT = 5
_EXECUTION_LIMIT = 5
_DEFECT_LIMIT = 5
_WORKFLOW_LIMIT = 5
_ACTIVITY_LIMIT = 10

_DEGRADATION_REASONS = frozenset(
    {"UPSTREAM_TIMEOUT", "UPSTREAM_ERROR", "PERMISSION_DENIED", "NOT_IMPLEMENTED"}
)


@dataclass(frozen=True, slots=True)
class PortalSettings:
    """Tunable portal aggregation knobs, all with safe defaults."""

    per_call_timeout: float = 3.0
    global_deadline: float = 4.0
    max_workers: int = 6
    strict_scope: bool = False
    cache_ttl_seconds: int = 0

    @classmethod
    def from_env(cls) -> PortalSettings:
        def as_float(name: str, default: float) -> float:
            raw = os.getenv(name)
            if raw is None or raw.strip() == "":
                return default
            return float(raw)

        def as_int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None or raw.strip() == "":
                return default
            return int(raw)

        def as_bool(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            if raw is None:
                return default
            return raw.strip().lower() == "true"

        return cls(
            per_call_timeout=as_float("PORTAL_PER_CALL_TIMEOUT", 3.0),
            global_deadline=as_float("PORTAL_GLOBAL_DEADLINE", 4.0),
            max_workers=as_int("PORTAL_MAX_WORKERS", 6),
            strict_scope=as_bool("PORTAL_STRICT_SCOPE", False),
            cache_ttl_seconds=as_int("PORTAL_CACHE_TTL_SECONDS", 0),
        )


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    """Authoritative scope resolution for a single dashboard request."""

    effective: str
    requested: str
    downgraded: bool
    can_cross_project: bool

    @classmethod
    def from_principal(
        cls, principal: Mapping[str, object], requested: str
    ) -> ScopeDecision:
        permissions = _permission_set(principal.get("permissions"))
        can_cross = PORTAL_CROSS_PROJECT_PERMISSION in permissions
        normalized = requested if requested in (SCOPE_MINE, SCOPE_CROSS_PROJECT) else SCOPE_MINE
        if normalized == SCOPE_CROSS_PROJECT and not can_cross:
            return cls(SCOPE_MINE, SCOPE_CROSS_PROJECT, True, can_cross)
        effective = SCOPE_CROSS_PROJECT if (normalized == SCOPE_CROSS_PROJECT and can_cross) else SCOPE_MINE
        return cls(effective, normalized, False, can_cross)


@dataclass(slots=True)
class Degradation:
    """Records one domain that failed to contribute to the dashboard."""

    domain: str
    reason: str


@dataclass(slots=True)
class CollectorContext:
    """Per-request context handed to every domain collector."""

    actor_id: str
    access_token: str
    trace_id: str
    cross_project: bool
    project_ids: tuple[str, ...]
    upstream: Any
    permissions: tuple[str, ...]
    timeout: float

    def with_project_ids(self, project_ids: tuple[str, ...]) -> CollectorContext:
        return CollectorContext(
            self.actor_id,
            self.access_token,
            self.trace_id,
            self.cross_project,
            project_ids,
            self.upstream,
            self.permissions,
            self.timeout,
        )

    def headers(self) -> dict[str, str]:
        return {
            "X-Actor-Id": self.actor_id,
            "X-Platform-Permissions": ",".join(self.permissions),
            "X-Trace-Id": self.trace_id,
            "X-Portal-Cross-Project": "true" if self.cross_project else "false",
        }

    def fetch(self, service_key: str, path: str, qs: str = "") -> tuple[int, object]:
        return self.upstream.fetch(
            service_key, path, self.access_token, self.headers(), qs, timeout=self.timeout
        )


class DomainCollector(Protocol):
    """A single domain projection feeding the dashboard."""

    domain: str

    def collect(self, ctx: CollectorContext) -> tuple[dict[str, object], Degradation | None]: ...
    def zero(self) -> dict[str, object]: ...


class ProjectsCollector:
    domain = "project"

    def zero(self) -> dict[str, object]:
        return {"total": 0, "items": [], "project_ids": []}

    def collect(self, ctx: CollectorContext) -> tuple[dict[str, object], Degradation | None]:
        try:
            status, body = ctx.fetch("project", _ENDPOINTS["project"], f"limit={_PROJECT_LIMIT}")
        except (URLError, OSError) as error:
            logger.warning("portal project failed: %s", error)
            return self.zero(), Degradation(self.domain, "UPSTREAM_TIMEOUT")
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            return self.zero(), Degradation(self.domain, "UPSTREAM_ERROR")
        data = body["data"]
        return (
            {
                "total": data.get("total", 0),
                "items": data.get("items", []),
                "project_ids": data.get("project_ids", []),
            },
            None,
        )


class RequirementCollector:
    domain = "requirement"

    def zero(self) -> dict[str, object]:
        return {
            "total": 0,
            "by_status": {},
            "baseline_total": 0,
            "pending_reviews": {"count": 0, "items": []},
        }

    def collect(self, ctx: CollectorContext) -> tuple[dict[str, object], Degradation | None]:
        qs = f"project_ids={','.join(ctx.project_ids)}&review_limit={_REVIEW_LIMIT}"
        try:
            status, body = ctx.fetch("requirement", _ENDPOINTS["requirement"], qs)
        except (URLError, OSError) as error:
            logger.warning("portal requirement failed: %s", error)
            return self.zero(), Degradation(self.domain, "UPSTREAM_TIMEOUT")
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            return self.zero(), Degradation(self.domain, "UPSTREAM_ERROR")
        return body["data"], None


class TpCollector:
    domain = "tp"

    def zero(self) -> dict[str, object]:
        return {
            "case_total": 0,
            "plan_total": 0,
            "execution_total": 0,
            "execution_by_status": {},
            "pass_rate": None,
            "pending_executions": {"count": 0, "items": []},
        }

    def collect(self, ctx: CollectorContext) -> tuple[dict[str, object], Degradation | None]:
        qs = f"project_ids={','.join(ctx.project_ids)}&execution_limit={_EXECUTION_LIMIT}"
        try:
            status, body = ctx.fetch("tp", _ENDPOINTS["tp"], qs)
        except (URLError, OSError) as error:
            logger.warning("portal tp failed: %s", error)
            return self.zero(), Degradation(self.domain, "UPSTREAM_TIMEOUT")
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            return self.zero(), Degradation(self.domain, "UPSTREAM_ERROR")
        return body["data"], None


class TdCollector:
    domain = "td"

    def zero(self) -> dict[str, object]:
        return {
            "total": 0,
            "by_status": {},
            "by_severity": {},
            "sla_breached": 0,
            "my_open_defects": {"count": 0, "items": []},
        }

    def collect(self, ctx: CollectorContext) -> tuple[dict[str, object], Degradation | None]:
        qs = f"project_ids={','.join(ctx.project_ids)}&defect_limit={_DEFECT_LIMIT}"
        try:
            status, body = ctx.fetch("td", _ENDPOINTS["td"], qs)
        except (URLError, OSError) as error:
            logger.warning("portal td failed: %s", error)
            return self.zero(), Degradation(self.domain, "UPSTREAM_TIMEOUT")
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            return self.zero(), Degradation(self.domain, "UPSTREAM_ERROR")
        return body["data"], None


class WorkflowCollector:
    domain = "workflow"

    def zero(self) -> dict[str, object]:
        return {"count": 0, "items": []}

    def collect(self, ctx: CollectorContext) -> tuple[dict[str, object], Degradation | None]:
        qs = f"project_ids={','.join(ctx.project_ids)}&limit={_WORKFLOW_LIMIT}"
        try:
            status, body = ctx.fetch("workflow", _ENDPOINTS["workflow"], qs)
        except (URLError, OSError) as error:
            logger.warning("portal workflow failed: %s", error)
            return self.zero(), Degradation(self.domain, "UPSTREAM_TIMEOUT")
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            return self.zero(), Degradation(self.domain, "UPSTREAM_ERROR")
        return body["data"], None


class ActivityCollector:
    domain = "activity"

    def zero(self) -> dict[str, object]:
        return {"source": "notification", "items": []}

    def collect(self, ctx: CollectorContext) -> tuple[dict[str, object], Degradation | None]:
        now = datetime.now(UTC)
        window_from = (now - timedelta(days=7)).isoformat()
        window_to = now.isoformat()
        audit_qs = (
            f"from={quote(window_from, safe='')}"
            f"&to={quote(window_to, safe='')}"
            f"&limit={_ACTIVITY_LIMIT}"
        )
        try:
            status, body = ctx.fetch("audit", _ENDPOINTS["audit"], audit_qs)
        except (URLError, OSError) as error:
            logger.warning("portal audit failed: %s", error)
            status, body = 0, None
        if status == 200 and isinstance(body, dict) and isinstance(body.get("data"), dict):
            audit_items = body["data"].get("items", [])
            if not isinstance(audit_items, list):
                audit_items = []
            return (
                {"source": "audit", "items": audit_items[:_ACTIVITY_LIMIT]},
                None,
            )
        # Fall back to the user's notifications feed (not a degradation).
        #
        # NOTE: ``notif_qs`` is advisory only. notification-service's
        # ``list_notifications`` ignores the ``limit`` query parameter and returns
        # every delivery for the recipient, so the gateway MUST enforce the cap
        # itself -- otherwise a user with hundreds of notifications would get an
        # unbounded activity payload on the portal home page.
        notif_qs = f"limit={_ACTIVITY_LIMIT}"
        try:
            status2, body2 = ctx.fetch("notification", _ENDPOINTS["notification"], notif_qs)
        except (URLError, OSError) as error:
            logger.warning("portal notification failed: %s", error)
            status2, body2 = 0, None
        if status2 == 200 and isinstance(body2, dict):
            data2 = body2.get("data")
            if isinstance(data2, list):
                # notification-service returns ``{"data": [items], "meta": {...}}``.
                return {"source": "notification", "items": data2[:_ACTIVITY_LIMIT]}, None
            if isinstance(data2, dict):
                nested = data2.get("items", [])
                if not isinstance(nested, list):
                    nested = []
                return {"source": "notification", "items": nested[:_ACTIVITY_LIMIT]}, None
        return self.zero(), Degradation(self.domain, "UPSTREAM_ERROR")


@dataclass(slots=True)
class DashboardResult:
    """Final dashboard payload (always 200, even when partially degraded)."""

    data: dict[str, object]
    meta: dict[str, object]

    def to_response(self) -> dict[str, object]:
        return {"data": self.data, "meta": self.meta}


@dataclass(slots=True)
class PortalDashboardService:
    """Orchestrates the two-phase fan-out and assembles the dashboard."""

    upstream: Any
    settings: PortalSettings
    _flight: RefreshSingleFlight = field(default_factory=RefreshSingleFlight)
    _cache: dict[str, tuple[float, DashboardResult]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def build(
        self,
        principal: Mapping[str, object],
        requested_scope: str,
        access_token: str,
        trace_id: str,
    ) -> tuple[DashboardResult | None, tuple[str, str] | None]:
        """Return ``(result, problem)``; problem is set only for strict-scope 403."""
        decision = ScopeDecision.from_principal(principal, requested_scope)
        if decision.downgraded and self.settings.strict_scope:
            return None, ("CROSS_PROJECT_FORBIDDEN", "Cross-project view is not permitted")
        actor_id = str(principal.get("id", ""))
        permissions = tuple(_permission_set(principal.get("permissions")))
        cache_key = f"{actor_id}:{decision.effective}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached, None
        started = time.monotonic()
        aggregate = self._flight.run(
            cache_key,
            lambda: self._aggregate(decision, actor_id, access_token, permissions, trace_id),
        )
        took_ms = int((time.monotonic() - started) * 1000)
        if aggregate is None:
            aggregate = self._empty_result(decision, trace_id, took_ms)
        else:
            aggregate.meta["took_ms"] = took_ms
            aggregate.meta["trace_id"] = trace_id
        if self.settings.cache_ttl_seconds > 0:
            self._cache_set(cache_key, aggregate)
        return aggregate, None

    def _aggregate(
        self,
        decision: ScopeDecision,
        actor_id: str,
        access_token: str,
        permissions: tuple[str, ...],
        trace_id: str,
    ) -> DashboardResult:
        cross = decision.effective == SCOPE_CROSS_PROJECT
        ctx = CollectorContext(
            actor_id,
            access_token,
            trace_id,
            cross,
            (),
            self.upstream,
            permissions,
            self.settings.per_call_timeout,
        )
        degradations: list[Degradation] = []
        projects_block, project_deg = ProjectsCollector().collect(ctx)
        if project_deg is not None:
            degradations.append(project_deg)
        project_ids = tuple(projects_block.get("project_ids", []))
        stage_ctx = ctx if cross else ctx.with_project_ids(project_ids)

        collectors: Sequence[DomainCollector] = (
            RequirementCollector(),
            TpCollector(),
            TdCollector(),
            WorkflowCollector(),
            ActivityCollector(),
        )
        blocks: dict[str, dict[str, object]] = {}
        with ThreadPoolExecutor(max_workers=self.settings.max_workers) as pool:
            futures = {pool.submit(collector.collect, stage_ctx): collector for collector in collectors}
            try:
                for future in as_completed(futures, timeout=self.settings.global_deadline):
                    collector = futures[future]
                    try:
                        block, degradation = future.result()
                    except Exception as error:  # noqa: BLE001 - one collector must never kill the dashboard
                        logger.warning("portal %s raised: %s", collector.domain, error)
                        block, degradation = collector.zero(), Degradation(collector.domain, "UPSTREAM_ERROR")
                    blocks[collector.domain] = block
                    if degradation is not None:
                        degradations.append(degradation)
            except TimeoutError:
                for future, collector in futures.items():
                    if not future.done():
                        blocks[collector.domain] = collector.zero()
                        degradations.append(Degradation(collector.domain, "UPSTREAM_TIMEOUT"))

        return self._assemble(decision, projects_block, blocks, degradations, trace_id)

    def _assemble(
        self,
        decision: ScopeDecision,
        projects_block: dict[str, object],
        blocks: dict[str, dict[str, object]],
        degradations: list[Degradation],
        trace_id: str,
    ) -> DashboardResult:
        requirement = blocks.get("requirement", RequirementCollector().zero())
        tp = blocks.get("tp", TpCollector().zero())
        td = blocks.get("td", TdCollector().zero())
        workflow = blocks.get("workflow", WorkflowCollector().zero())
        activity = blocks.get("activity", ActivityCollector().zero())

        data: dict[str, object] = {
            "scope": decision.effective,
            "scope_requested": decision.requested,
            "scope_downgraded": decision.downgraded,
            "can_cross_project": decision.can_cross_project,
            "generated_at": datetime.now(UTC).isoformat(),
            "projects": {
                "total": projects_block.get("total", 0),
                "items": projects_block.get("items", []),
            },
            "my_work": {
                "pending_requirement_reviews": _dig(requirement, "pending_reviews", default={"count": 0, "items": []}),
                "my_open_defects": _dig(td, "my_open_defects", default={"count": 0, "items": []}),
                "pending_test_executions": _dig(tp, "pending_executions", default={"count": 0, "items": []}),
                "pending_workflow_approvals": {"count": workflow.get("count", 0), "items": workflow.get("items", [])},
            },
            "requirement_stats": {
                "total": requirement.get("total", 0),
                "by_status": requirement.get("by_status", {}),
                "baseline_total": requirement.get("baseline_total", 0),
            },
            "tp_stats": {
                "case_total": tp.get("case_total", 0),
                "plan_total": tp.get("plan_total", 0),
                "execution_total": tp.get("execution_total", 0),
                "execution_by_status": tp.get("execution_by_status", {}),
                "pass_rate": tp.get("pass_rate"),
            },
            "td_stats": {
                "total": td.get("total", 0),
                "by_status": td.get("by_status", {}),
                "by_severity": td.get("by_severity", {}),
                "sla_breached": td.get("sla_breached", 0),
            },
            "recent_activities": activity,
            "degraded": [{"domain": d.domain, "reason": d.reason} for d in degradations],
        }
        return DashboardResult(data, {"trace_id": trace_id, "took_ms": 0})

    def _empty_result(
        self, decision: ScopeDecision, trace_id: str, took_ms: int
    ) -> DashboardResult:
        data: dict[str, object] = {
            "scope": decision.effective,
            "scope_requested": decision.requested,
            "scope_downgraded": decision.downgraded,
            "can_cross_project": decision.can_cross_project,
            "generated_at": datetime.now(UTC).isoformat(),
            "projects": {"total": 0, "items": []},
            "my_work": {
                "pending_requirement_reviews": {"count": 0, "items": []},
                "my_open_defects": {"count": 0, "items": []},
                "pending_test_executions": {"count": 0, "items": []},
                "pending_workflow_approvals": {"count": 0, "items": []},
            },
            "requirement_stats": {"total": 0, "by_status": {}, "baseline_total": 0},
            "tp_stats": {
                "case_total": 0,
                "plan_total": 0,
                "execution_total": 0,
                "execution_by_status": {},
                "pass_rate": None,
            },
            "td_stats": {"total": 0, "by_status": {}, "by_severity": {}, "sla_breached": 0},
            "recent_activities": {"source": "notification", "items": []},
            "degraded": [{"domain": "gateway", "reason": "UPSTREAM_ERROR"}],
        }
        return DashboardResult(data, {"trace_id": trace_id, "took_ms": took_ms})

    def _cache_get(self, key: str) -> DashboardResult | None:
        if self.settings.cache_ttl_seconds <= 0:
            return None
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            stamped, result = entry
            if time.monotonic() - stamped > self.settings.cache_ttl_seconds:
                self._cache.pop(key, None)
                return None
            return result

    def _cache_set(self, key: str, result: DashboardResult) -> None:
        with self._lock:
            self._cache[key] = (time.monotonic(), result)


def _permission_set(permissions: object) -> set[str]:
    if permissions is None:
        return set()
    if isinstance(permissions, str):
        return {item.strip() for item in permissions.split(",") if item.strip()}
    if isinstance(permissions, (list, tuple, set)):
        return {str(item).strip() for item in permissions if str(item).strip()}
    return set()


def _dig(block: Mapping[str, object], *path: str, default: object) -> object:
    current: object = block
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current
