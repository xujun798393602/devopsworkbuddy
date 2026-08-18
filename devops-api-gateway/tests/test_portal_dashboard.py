"""Portal dashboard aggregation tests (route + collector fan-out)."""
from __future__ import annotations

from typing import Any

from gateway.app import create_app
from gateway.portal_dashboard import (
    _ACTIVITY_LIMIT,
    PORTAL_CROSS_PROJECT_PERMISSION,
    PortalSettings,
    ScopeDecision,
)

PROJECT_IDS = ["prj-1", "prj-2"]


class FakeUpstream:
    """In-memory upstream returning canned portal responses keyed by route."""

    def __init__(self, responses: dict[tuple[str, str], tuple[int, Any]], principal: dict[str, Any]) -> None:
        self._responses = responses
        self._principal = principal
        self.calls: list[tuple[str, str, str]] = []

    def principal(self, access_token: str) -> dict[str, Any]:
        return self._principal

    def fetch(self, service_key, path, token, headers=None, qs="", timeout=None):
        self.calls.append((service_key, path, qs))
        return self._responses.get((service_key, path), (404, {"error_code": "NO_ROUTE"}))


def _project_response(ids):
    return (
        200,
        {
            "data": {
                "total": len(ids),
                "items": [{"id": i, "name": i} for i in ids],
                "project_ids": list(ids),
            }
        },
    )


def _ok(data):
    return 200, {"data": data}


def _build_responses() -> dict[tuple[str, str], tuple[int, Any]]:
    return {
        ("project", "v1/portal/projects-overview"): _project_response(PROJECT_IDS),
        ("requirement", "v1/portal/requirement-summary"): _ok(
            {"total": 10, "by_status": {"approved": 8}, "baseline_total": 2, "pending_reviews": {"count": 3, "items": [{"id": "r1"}]}}
        ),
        ("tp", "v1/portal/tp-summary"): _ok(
            {"case_total": 100, "plan_total": 5, "execution_total": 20, "execution_by_status": {"passed": 18, "failed": 2}, "pass_rate": 0.9, "pending_executions": {"count": 4, "items": [{"id": "e1"}]}}
        ),
        ("td", "v1/portal/td-summary"): _ok(
            {"total": 30, "by_status": {"new": 5}, "by_severity": {"high": 3}, "sla_breached": 1, "my_open_defects": {"count": 2, "items": [{"id": "d1"}]}}
        ),
        ("workflow", "v1/portal/pending-approvals"): _ok(
            {"count": 1, "items": [{"id": "w1", "project_id": "prj-1"}]}
        ),
        ("audit", "v1/audit-records"): _ok({"items": [{"id": "a1"}]}),
        ("notification", "v1/me/notifications"): _ok({"items": [{"id": "n1"}]}),
    }


def _client(responses, principal, settings=None, session=True):
    upstream = FakeUpstream(responses, principal)
    app = create_app(upstream, portal_settings=settings or PortalSettings())
    client = app.test_client()
    if session:
        client.set_cookie("devops_session", "tok")
    return client, upstream


def _principal(permissions=()):
    return {"id": "actor-1", "permissions": list(permissions)}


def test_mine_scope_fans_out_with_project_ids() -> None:
    client, upstream = _client(_build_responses(), _principal())
    resp = client.get("/bff/api/portal/dashboard?scope=mine")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["scope"] == "mine"
    assert data["can_cross_project"] is False
    assert "project_ids" not in data["projects"]
    # downstream collectors received the resolved project_ids
    tp_call = next(c for c in upstream.calls if c[0] == "tp")
    assert "prj-1" in tp_call[2] and "prj-2" in tp_call[2]


def test_cross_project_scope_with_permission_runs_parallel() -> None:
    principal = _principal([PORTAL_CROSS_PROJECT_PERMISSION])
    client, upstream = _client(_build_responses(), principal)
    resp = client.get("/bff/api/portal/dashboard?scope=cross-project")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["scope"] == "cross-project"
    assert data["can_cross_project"] is True
    assert data["scope_downgraded"] is False
    # project_ids passed empty -> full platform
    tp_call = next(c for c in upstream.calls if c[0] == "tp")
    assert tp_call[2] == "project_ids=&execution_limit=5"


def test_cross_project_without_permission_downgrades_to_mine() -> None:
    client, _ = _client(_build_responses(), _principal())
    resp = client.get("/bff/api/portal/dashboard?scope=cross-project")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["scope"] == "mine"
    assert data["scope_requested"] == "cross-project"
    assert data["scope_downgraded"] is True


def test_strict_scope_returns_403_when_downgraded() -> None:
    settings = PortalSettings(strict_scope=True)
    client, _ = _client(_build_responses(), _principal(), settings=settings)
    resp = client.get("/bff/api/portal/dashboard?scope=cross-project")
    assert resp.status_code == 403
    assert resp.get_json()["error_code"] == "CROSS_PROJECT_FORBIDDEN"


def test_missing_session_is_401() -> None:
    client, _ = _client(_build_responses(), _principal(), session=False)
    resp = client.get("/bff/api/portal/dashboard")
    assert resp.status_code == 401


def test_project_failure_degrades_downstream_to_zero() -> None:
    responses = _build_responses()
    responses[("project", "v1/portal/projects-overview")] = (500, {"error": "boom"})
    client, upstream = _client(responses, _principal())
    resp = client.get("/bff/api/portal/dashboard?scope=mine")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert {"domain": "project", "reason": "UPSTREAM_ERROR"} in data["degraded"]
    # downstream ran with empty project_ids (real domains return zero for empty scope)
    tp_call = next(c for c in upstream.calls if c[0] == "tp")
    assert tp_call[2] == "project_ids=&execution_limit=5"


def test_domain_timeout_records_degradation() -> None:
    class SlowUpstream(FakeUpstream):
        def fetch(self, service_key, path, token, headers=None, qs="", timeout=None):
            if service_key == "tp":
                raise TimeoutError("slow")
            return super().fetch(service_key, path, token, headers, qs, timeout)

    upstream = SlowUpstream(_build_responses(), _principal())
    app = create_app(upstream)
    client = app.test_client()
    client.set_cookie("devops_session", "tok")
    resp = client.get("/bff/api/portal/dashboard?scope=mine")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert {"domain": "tp", "reason": "UPSTREAM_TIMEOUT"} in data["degraded"]
    assert data["tp_stats"]["case_total"] == 0


def test_activity_falls_back_to_notification() -> None:
    responses = _build_responses()
    responses[("audit", "v1/audit-records")] = (403, {"error_code": "PERMISSION_DENIED"})
    # notification-service returns the list-shaped envelope ``{"data": [...], "meta": {...}}``.
    responses[("notification", "v1/me/notifications")] = (
        200,
        {"data": [{"id": "n1"}], "meta": {"trace_id": "t"}},
    )
    client, _ = _client(responses, _principal())
    resp = client.get("/bff/api/portal/dashboard?scope=mine")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    # fallback is not a degradation
    assert not any(d["domain"] == "activity" for d in data["degraded"])
    assert data["recent_activities"]["source"] == "notification"
    assert data["recent_activities"]["items"] == [{"id": "n1"}]


def test_activity_fallback_uses_list_shaped_notifications() -> None:
    responses = _build_responses()
    responses[("audit", "v1/audit-records")] = (403, {"error_code": "PERMISSION_DENIED"})
    responses[("notification", "v1/me/notifications")] = (
        200,
        {"data": [{"id": "n1"}, {"id": "n2"}], "meta": {"trace_id": "t"}},
    )
    client, _ = _client(responses, _principal())
    resp = client.get("/bff/api/portal/dashboard?scope=mine")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert not any(d["domain"] == "activity" for d in data["degraded"])
    assert data["recent_activities"]["source"] == "notification"
    assert data["recent_activities"]["items"] == [{"id": "n1"}, {"id": "n2"}]


def test_activity_fallback_empty_notifications_is_not_degraded() -> None:
    responses = _build_responses()
    responses[("audit", "v1/audit-records")] = (403, {"error_code": "PERMISSION_DENIED"})
    responses[("notification", "v1/me/notifications")] = (
        200,
        {"data": [], "meta": {"trace_id": "t"}},
    )
    client, _ = _client(responses, _principal())
    resp = client.get("/bff/api/portal/dashboard?scope=mine")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    # An empty feed is a valid (empty) state, not a failure.
    assert not any(d["domain"] == "activity" for d in data["degraded"])
    assert data["recent_activities"] == {"source": "notification", "items": []}


def test_activity_fallback_truncates_list_shaped_notifications() -> None:
    """notification-service ignores ``limit``; the gateway must cap the feed itself.

    ``list_notifications`` returns *every* delivery for the recipient, so a user
    with hundreds of notifications would otherwise get an unbounded activity
    payload embedded in the portal dashboard response.
    """
    responses = _build_responses()
    responses[("audit", "v1/audit-records")] = (403, {"error_code": "PERMISSION_DENIED"})
    oversized = [{"id": f"n{i}"} for i in range(25)]
    responses[("notification", "v1/me/notifications")] = (
        200,
        {"data": oversized, "meta": {"trace_id": "t"}},
    )
    client, upstream = _client(responses, _principal())
    resp = client.get("/bff/api/portal/dashboard?scope=mine")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert not any(d["domain"] == "activity" for d in data["degraded"])
    activities = data["recent_activities"]
    assert activities["source"] == "notification"
    assert len(activities["items"]) == _ACTIVITY_LIMIT == 10
    # Truncation keeps the head of the feed (newest-first ordering from upstream).
    assert activities["items"] == oversized[:_ACTIVITY_LIMIT]
    # The advisory limit is still sent upstream even though it is ignored there.
    notif_call = next(c for c in upstream.calls if c[0] == "notification")
    assert notif_call[2] == f"limit={_ACTIVITY_LIMIT}"


def test_activity_fallback_truncates_dict_shaped_notifications() -> None:
    """The ``{"data": {"items": [...]}}`` variant must be capped identically."""
    responses = _build_responses()
    responses[("audit", "v1/audit-records")] = (403, {"error_code": "PERMISSION_DENIED"})
    oversized = [{"id": f"n{i}"} for i in range(25)]
    responses[("notification", "v1/me/notifications")] = (
        200,
        {"data": {"items": oversized}, "meta": {"trace_id": "t"}},
    )
    client, _ = _client(responses, _principal())
    resp = client.get("/bff/api/portal/dashboard?scope=mine")
    assert resp.status_code == 200
    activities = resp.get_json()["data"]["recent_activities"]
    assert activities["source"] == "notification"
    assert len(activities["items"]) == _ACTIVITY_LIMIT
    assert activities["items"] == oversized[:_ACTIVITY_LIMIT]


def test_activity_audit_source_is_also_truncated() -> None:
    """The primary audit source is capped too, so the payload has a hard bound."""
    responses = _build_responses()
    oversized = [{"id": f"a{i}"} for i in range(25)]
    responses[("audit", "v1/audit-records")] = _ok({"items": oversized})
    client, _ = _client(responses, _principal())
    resp = client.get("/bff/api/portal/dashboard?scope=mine")
    assert resp.status_code == 200
    activities = resp.get_json()["data"]["recent_activities"]
    assert activities["source"] == "audit"
    assert len(activities["items"]) == _ACTIVITY_LIMIT
    assert activities["items"] == oversized[:_ACTIVITY_LIMIT]


def test_static_route_priority_over_generic_proxy() -> None:
    client, _ = _client(_build_responses(), _principal())
    resp = client.get("/bff/api/portal/dashboard")
    # The generic /bff/api/<path:path> proxy would 401 (no upstream route for portal);
    # the static rule must win and return a real dashboard payload.
    assert resp.status_code == 200
    assert "projects" in resp.get_json()["data"]


def test_isolation_route_returns_404_not_401() -> None:
    client, _ = _client(_build_responses(), _principal())
    # Unknown portal paths (e.g. the typo'd v1 variant) must answer 404 here,
    # before the generic proxy can bounce them upstream and leak a 401.
    resp = client.get("/bff/api/v1/portal/dashboard")
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == "NOT_FOUND"
    # Even without a session cookie it must stay 404 (never a 401).
    anon, _ = _client(_build_responses(), _principal(), session=False)
    resp2 = anon.get("/bff/api/v1/portal/anything")
    assert resp2.status_code == 404


def test_scope_decision_from_principal() -> None:
    with_perm = ScopeDecision.from_principal(_principal([PORTAL_CROSS_PROJECT_PERMISSION]), "cross-project")
    assert with_perm.effective == "cross-project" and with_perm.can_cross_project is True
    without = ScopeDecision.from_principal(_principal(), "cross-project")
    assert without.effective == "mine" and without.downgraded is True and without.can_cross_project is False
    bad_request = ScopeDecision.from_principal(_principal(), "garbage")
    assert bad_request.effective == "mine"


def test_limit_is_hardcoded_by_gateway() -> None:
    client, upstream = _client(_build_responses(), _principal())
    client.get("/bff/api/portal/dashboard?scope=mine")
    project_call = next(c for c in upstream.calls if c[0] == "project")
    assert project_call[2] == "limit=8"
    workflow_call = next(c for c in upstream.calls if c[0] == "workflow")
    assert "limit=5" in workflow_call[2]
