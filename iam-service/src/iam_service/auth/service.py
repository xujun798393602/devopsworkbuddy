"""IAM session application service with refresh reuse detection."""
from uuid import uuid4

from iam_service.auth.models import Session, User, UserStatus
from iam_service.auth.providers import IdentityProviderAdapter
from iam_service.auth.repository import IamRepository
from iam_service.auth.tokens import TokenService


class SessionService:
    def __init__(
        self,
        repo: IamRepository,
        tokens: TokenService,
        provider: IdentityProviderAdapter,
        refresh_ttl: int,
    ) -> None:
        self.repo, self.tokens, self.provider, self.refresh_ttl = repo, tokens, provider, refresh_ttl
        self.audit_events: list[dict[str, object]] = []

    def login(self, username: str) -> dict[str, object]:
        identity = self.provider.authenticate_dev(username)
        user = self.repo.get_user_by_username(identity.username)
        if user is None:
            permissions = ("audit.read",) if username == "auditor" else (("workflow.template.manage",) if username == "workflow-admin" else ())
            user = User(str(uuid4()), identity.username, identity.display_name, permissions=permissions)
            self.repo.save_user(user)
        if user.status != UserStatus.ACTIVE:
            raise PermissionError("Authentication failed")
        raw, digest = self.tokens.new_refresh()
        session = Session.create(user.id, digest, self.refresh_ttl)
        self.repo.save_session(session)
        self.audit_events.append({"action": "identity.login", "actor_id": user.id, "result": "success"})
        return self._pair(user, session, raw)

    def refresh(self, raw_token: str) -> dict[str, object]:
        digest = self.tokens.hash_refresh(raw_token)
        session = self.repo.find_session_hash(digest)
        if session is None or session.status != "active":
            raise PermissionError("Invalid refresh token")
        if hmac_compare(digest, session.previous_refresh_hash):
            self.repo.revoke_family(session.family_id, "refresh_token_reused")
            self.audit_events.append({"action": "identity.refresh_reuse", "actor_id": session.user_id, "result": "denied"})
            raise PermissionError("Refresh token reused")
        if not hmac_compare(digest, session.current_refresh_hash):
            raise PermissionError("Invalid refresh token")
        user = self.repo.get_user(session.user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            session.revoke("user_inactive")
            raise PermissionError("Invalid refresh token")
        raw, new_hash = self.tokens.new_refresh()
        session.rotate(new_hash)
        self.repo.save_session(session)
        return self._pair(user, session, raw)

    def logout(self, raw_token: str) -> None:
        session = self.repo.find_session_hash(self.tokens.hash_refresh(raw_token))
        if session is not None and session.status == "active":
            session.revoke("logout")
            self.repo.save_session(session)

    def _pair(self, user: User, session: Session, refresh: str) -> dict[str, object]:
        return {"access_token": self.tokens.issue_access(user, session), "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.tokens.settings.access_ttl, "principal": {"id": user.id, "username": user.username, "display_name": user.display_name, "permissions": list(user.permissions), "break_glass": False}}


def hmac_compare(left: str, right: str | None) -> bool:
    import hmac
    return right is not None and hmac.compare_digest(left, right)
