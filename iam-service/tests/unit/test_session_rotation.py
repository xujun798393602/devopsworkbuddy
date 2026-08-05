import base64
import json

import pytest

from iam_service.auth.providers import LocalDevProvider
from iam_service.auth.repository import InMemoryIamRepository
from iam_service.auth.service import SessionService
from iam_service.auth.tokens import TokenService
from iam_service.config import Settings


def make_service() -> SessionService:
    settings = Settings()
    return SessionService(InMemoryIamRepository(), TokenService(settings), LocalDevProvider(True), settings.refresh_ttl)


def test_refresh_rotates_and_reuse_revokes_family() -> None:
    service = make_service()
    first = service.login("developer")
    second = service.refresh(str(first["refresh_token"]))
    assert second["refresh_token"] != first["refresh_token"]
    try:
        service.refresh(str(first["refresh_token"]))
        assert False
    except PermissionError:
        assert next(iter(service.repo.sessions.values())).status == "revoked"


def test_access_token_rejects_none_algorithm() -> None:
    service = make_service()
    claims = {"sub": "attacker"}
    encoded_header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=")
    encoded_claims = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    token = f"{encoded_header.decode()}.{encoded_claims.decode()}."
    with pytest.raises(ValueError, match="JWT_ALGORITHM_REJECTED"):
        service.tokens.verify_access(token)
