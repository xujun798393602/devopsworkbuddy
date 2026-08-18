"""IAM session application service with refresh reuse detection."""
from uuid import uuid4

from iam_service.auth.models import Session, User, UserStatus
from iam_service.auth.providers import IdentityProviderAdapter
from iam_service.auth.repository import IamRepository
from iam_service.auth.tokens import TokenService

# Platform permission point that unlocks the portal dashboard's cross-project
# ("全平台") scope. The gateway is the authority that enforces it — see
# devops-portal/docs/architecture-portal-dashboard.md §5.2 — and it reaches the
# gateway via the access token's `platform_permissions` claim.
PORTAL_CROSS_PROJECT_VIEW = "portal:cross-project-view"

# Baseline permissions granted to the well-known local dev identities. This is
# the local-development provisioning path only: `LocalDevProvider` refuses to
# authenticate at all unless dev login is enabled, so these grants can never be
# applied to a real IdP-backed identity.
# Portal management page permission points (architecture §9.D.1). The four
# management pages (project / requirement / defect / test-case) read and write
# through these eight points; the local dev `developer` identity is seeded with
# all of them so the portal write-gates can be exercised in P0 without a real
# RBAC role assignment.
PORTAL_MANAGEMENT_PERMISSIONS: tuple[str, ...] = (
    "requirement.read",
    "requirement.write",
    "defect.read",
    "defect.write",
    "testcase.read",
    "testcase.write",
    "project.read",
    "project.write",
)

DEV_PERMISSION_SEEDS: dict[str, tuple[str, ...]] = {
    "auditor": ("audit.read",),
    "workflow-admin": ("workflow.template.manage",),
    "developer": (PORTAL_CROSS_PROJECT_VIEW, *PORTAL_MANAGEMENT_PERMISSIONS),
}


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
            permissions = DEV_PERMISSION_SEEDS.get(identity.username, ())
            user = User(str(uuid4()), identity.username, identity.display_name, permissions=permissions)
            self.repo.save_user(user)
        if user.status != UserStatus.ACTIVE:
            raise PermissionError("Authentication failed")
        self._grant_seeded_permissions(user)
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

    def _grant_seeded_permissions(self, user: User) -> None:
        """Idempotently top up a dev identity with its seeded permissions.

        Seeding otherwise only runs at first login, so identities provisioned
        before a permission point was registered (e.g. `developer` predating
        `portal:cross-project-view`) would never receive it. Only missing
        permissions are appended, and the user is persisted only when something
        actually changed, so repeated logins are a no-op.
        """
        missing = tuple(
            permission
            for permission in DEV_PERMISSION_SEEDS.get(user.username, ())
            if permission not in user.permissions
        )
        if not missing:
            return
        user.permissions = user.permissions + missing
        self.repo.save_user(user)

    def _pair(self, user: User, session: Session, refresh: str) -> dict[str, object]:
        return {"access_token": self.tokens.issue_access(user, session), "refresh_token": refresh, "token_type": "Bearer", "expires_in": self.tokens.settings.access_ttl, "principal": {"id": user.id, "username": user.username, "display_name": user.display_name, "permissions": list(user.permissions), "break_glass": False}}


def hmac_compare(left: str, right: str | None) -> bool:
    import hmac
    return right is not None and hmac.compare_digest(left, right)
