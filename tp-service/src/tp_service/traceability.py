"""Source-owned traceability links and an idempotent event projection."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from tp_service.domain import DomainError


@dataclass(frozen=True, slots=True)
class TraceEndpoint:
    """Stable identity and observed revision of one domain object."""

    project_id: UUID
    domain: str
    resource_type: str
    resource_id: UUID
    revision: int


@dataclass(frozen=True, slots=True)
class TraceabilityLink:
    """Immutable source-owned relationship; supersession creates another fact."""

    id: UUID
    source: TraceEndpoint
    target: TraceEndpoint
    link_type: str
    source_event_id: UUID
    occurred_at: datetime
    status: str = "active"

    def __post_init__(self) -> None:
        if self.source.project_id != self.target.project_id:
            raise DomainError("RESOURCE_NOT_FOUND", "Cross-project trace endpoint is not visible", 404)
        if self.source.domain == self.target.domain and self.source.resource_id == self.target.resource_id:
            raise DomainError("INVALID_TRACE_LINK", "A resource cannot link to itself", 422)
        if self.status not in {"active", "superseded", "broken"}:
            raise DomainError("INVALID_TRACE_STATUS", "Unsupported trace link status", 422)


@dataclass(frozen=True, slots=True)
class TraceGraph:
    """Bounded graph response with projection health and completeness."""

    nodes: tuple[TraceEndpoint, ...]
    links: tuple[TraceabilityLink, ...]
    truncated: bool
    stale: bool
    broken: bool
    completeness: str


@dataclass(slots=True)
class TraceProjectionService:
    """Consume link events once and serve bounded forward/reverse graph queries."""

    links: dict[UUID, TraceabilityLink] = field(default_factory=dict)
    consumed_events: set[UUID] = field(default_factory=set)
    last_event_at: datetime | None = None
    stale_after: timedelta = timedelta(seconds=30)

    def consume(self, event: dict[str, object]) -> TraceabilityLink:
        """Project a minimal v1 link event idempotently and reject malformed facts."""
        event_id = UUID(str(event["event_id"]))
        if event_id in self.consumed_events:
            return next(link for link in self.links.values() if link.source_event_id == event_id)
        project_id = UUID(str(event["project_id"]))
        source = TraceEndpoint(project_id, str(event["source_domain"]), str(event["source_type"]), UUID(str(event["source_id"])), int(event.get("source_revision", 1)))
        target = TraceEndpoint(project_id, str(event["target_domain"]), str(event["target_type"]), UUID(str(event["target_id"])), int(event.get("target_revision", 1)))
        link = TraceabilityLink(UUID(str(event.get("link_id", uuid4()))), source, target, str(event["link_type"]), event_id, datetime.fromisoformat(str(event.get("occurred_at", datetime.now(UTC).isoformat()))), str(event.get("status", "active")))
        self.links[link.id] = link
        self.consumed_events.add(event_id)
        self.last_event_at = max(self.last_event_at or link.occurred_at, link.occurred_at)
        return link

    def query(
        self,
        project_id: UUID,
        resource_id: UUID,
        direction: str = "both",
        depth: int = 4,
        limit: int = 500,
        now: datetime | None = None,
    ) -> TraceGraph:
        """Traverse a project graph in forward, reverse or both directions."""
        if direction not in {"forward", "reverse", "both"} or not 1 <= depth <= 8 or not 1 <= limit <= 500:
            raise DomainError("INVALID_TRACE_QUERY", "Direction, depth or limit is invalid", 422)
        visible = [link for link in self.links.values() if link.source.project_id == project_id]
        frontier = {resource_id}
        node_map: dict[UUID, TraceEndpoint] = {}
        selected: list[TraceabilityLink] = []
        truncated = False
        for _ in range(depth):
            next_frontier: set[UUID] = set()
            for link in visible:
                forward = direction in {"forward", "both"} and link.source.resource_id in frontier
                reverse = direction in {"reverse", "both"} and link.target.resource_id in frontier
                if not forward and not reverse:
                    continue
                if link not in selected:
                    if len(node_map | {link.source.resource_id: link.source, link.target.resource_id: link.target}) > limit:
                        truncated = True
                        break
                    selected.append(link)
                    node_map[link.source.resource_id] = link.source
                    node_map[link.target.resource_id] = link.target
                next_frontier.add(link.target.resource_id if forward else link.source.resource_id)
            if truncated or not next_frontier:
                break
            frontier = next_frontier
        if not node_map:
            raise DomainError("RESOURCE_NOT_FOUND", "Trace root is not visible", 404)
        statuses = {link.status for link in selected}
        broken = "broken" in statuses
        has_requirement = any(node.domain == "requirement" for node in node_map.values())
        has_test = any(node.domain == "tp" for node in node_map.values())
        has_failure = any(node.resource_type in {"case_run", "defect"} for node in node_map.values())
        completeness = "unknown" if broken or truncated else "fail" if not (has_requirement and has_test) else "pass" if not has_failure else "fail"
        current = now or datetime.now(UTC)
        stale = self.last_event_at is None or current - self.last_event_at > self.stale_after
        return TraceGraph(tuple(node_map.values()), tuple(selected), truncated, stale, broken, completeness)


__all__ = ["TraceEndpoint", "TraceGraph", "TraceProjectionService", "TraceabilityLink"]
