"""Break-glass authentication boundary with injectable TOTP verification."""

from ipaddress import ip_address, ip_network
from typing import Protocol

from iam_service.auth.service import SessionService


class TotpVerifier(Protocol):
    """Verify a TOTP without exposing its secret to the application service."""

    def verify(self, code: str) -> bool: ...


class BreakGlassService:
    """Enforce network, reason, ticket, and TOTP controls before login."""

    def __init__(self, sessions: SessionService, verifier: TotpVerifier, allowed_cidrs: tuple[str, ...]) -> None:
        self.sessions = sessions
        self.verifier = verifier
        self.allowed_networks = tuple(ip_network(value) for value in allowed_cidrs)

    def login(self, username: str, code: str, reason: str, ticket: str, remote_ip: str) -> dict[str, object]:
        if not reason.strip() or len(reason) > 500 or not ticket.strip() or len(ticket) > 100:
            raise PermissionError("BREAK_GLASS_CONTEXT_REQUIRED")
        address = ip_address(remote_ip)
        if not any(address in network for network in self.allowed_networks):
            raise PermissionError("BREAK_GLASS_NETWORK_DENIED")
        if not self.verifier.verify(code):
            raise PermissionError("BREAK_GLASS_TOTP_DENIED")
        pair = self.sessions.login(username)
        principal = dict(pair["principal"])
        principal["break_glass"] = True
        pair["principal"] = principal
        session = next(item for item in self.sessions.repo.sessions.values() if item.user_id == principal["id"] and item.status == "active")
        user = self.sessions.repo.get_user(str(principal["id"]))
        pair["access_token"] = self.sessions.tokens.issue_access(user, session, break_glass=True)
        self.sessions.audit_events.append({"action": "identity.break_glass", "actor_id": principal["id"], "result": "success", "reason_present": True, "ticket_present": True})
        return pair
