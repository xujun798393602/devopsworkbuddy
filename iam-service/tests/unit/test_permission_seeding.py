"""Provisioning of the portal dashboard permission point onto dev identities."""
import base64
import json

from iam_service.auth.models import User
from iam_service.auth.providers import LocalDevProvider
from iam_service.auth.repository import InMemoryIamRepository
from iam_service.auth.service import (
    DEV_PERMISSION_SEEDS,
    PORTAL_CROSS_PROJECT_VIEW,
    PORTAL_MANAGEMENT_PERMISSIONS,
    SessionService,
)
from iam_service.auth.tokens import TokenService
from iam_service.config import Settings


def make_service(repo: InMemoryIamRepository | None = None) -> SessionService:
    settings = Settings()
    return SessionService(
        repo if repo is not None else InMemoryIamRepository(),
        TokenService(settings),
        LocalDevProvider(True),
        settings.refresh_ttl,
    )


def access_claims(pair: dict[str, object]) -> dict[str, object]:
    """Decode the (unverified) access token payload for claim assertions."""
    payload = str(pair["access_token"]).split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def test_permission_point_is_registered_for_developer() -> None:
    assert PORTAL_CROSS_PROJECT_VIEW == "portal:cross-project-view"
    assert set(DEV_PERMISSION_SEEDS["developer"]) == {
        PORTAL_CROSS_PROJECT_VIEW,
        *PORTAL_MANAGEMENT_PERMISSIONS,
    }


def test_new_developer_receives_cross_project_permission() -> None:
    service = make_service()

    pair = service.login("developer")

    principal = pair["principal"]
    assert isinstance(principal, dict)
    assert PORTAL_CROSS_PROJECT_VIEW in principal["permissions"]


def test_permission_is_published_in_the_access_token_claim() -> None:
    """The gateway reads `platform_permissions`, not the principal payload."""
    service = make_service()

    claims = access_claims(service.login("developer"))

    assert PORTAL_CROSS_PROJECT_VIEW in claims["platform_permissions"]


def test_existing_developer_is_backfilled_on_login() -> None:
    """Users provisioned before the permission point existed still get it."""
    repo = InMemoryIamRepository()
    repo.save_user(User("u-1", "developer", "Developer", permissions=()))
    service = make_service(repo)

    pair = service.login("developer")

    principal = pair["principal"]
    assert isinstance(principal, dict)
    assert principal["id"] == "u-1"
    assert set(principal["permissions"]) == {
        PORTAL_CROSS_PROJECT_VIEW,
        *PORTAL_MANAGEMENT_PERMISSIONS,
    }


def test_backfill_is_idempotent_and_preserves_existing_permissions() -> None:
    repo = InMemoryIamRepository()
    repo.save_user(User("u-1", "developer", "Developer", permissions=("project.read",)))
    service = make_service(repo)

    service.login("developer")
    first = service.login("developer")

    expected = {"project.read", PORTAL_CROSS_PROJECT_VIEW, *PORTAL_MANAGEMENT_PERMISSIONS}
    assert set(repo.users["u-1"].permissions) == expected
    assert set(first["principal"]["permissions"]) == expected


def test_other_identities_keep_their_own_seeds() -> None:
    service = make_service()

    auditor = service.login("auditor")
    admin = service.login("workflow-admin")

    auditor_principal, admin_principal = auditor["principal"], admin["principal"]
    assert isinstance(auditor_principal, dict)
    assert isinstance(admin_principal, dict)
    assert auditor_principal["permissions"] == ["audit.read"]
    assert admin_principal["permissions"] == ["workflow.template.manage"]
    assert PORTAL_CROSS_PROJECT_VIEW not in auditor_principal["permissions"]
