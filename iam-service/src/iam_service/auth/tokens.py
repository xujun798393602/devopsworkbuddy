"""Fixed-algorithm JWT and opaque refresh token services."""

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from iam_service.auth.models import Session, User
from iam_service.config import Settings


class TokenService:
    """Issue and verify HS256 development JWTs with a fixed allowlist."""

    ALGORITHMS: tuple[str, ...] = ("HS256",)
    REQUIRED_CLAIMS: tuple[str, ...] = (
        "exp",
        "iat",
        "nbf",
        "iss",
        "aud",
        "sub",
        "sid",
        "jti",
        "auth_method",
        "platform_permissions",
        "break_glass",
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def hash_refresh(self, raw: str) -> str:
        """Return the peppered HMAC digest stored for a refresh token."""
        return hmac.new(
            self.settings.refresh_pepper.encode(),
            raw.encode(),
            hashlib.sha256,
        ).hexdigest()

    def new_refresh(self) -> tuple[str, str]:
        """Create a high-entropy opaque refresh token and its digest."""
        raw = secrets.token_urlsafe(48)
        return raw, self.hash_refresh(raw)

    def issue_access(
        self,
        user: User,
        session: Session,
        break_glass: bool = False,
    ) -> str:
        """Issue a short-lived signed access token for an active session."""
        now = datetime.now(UTC)
        claims: dict[str, object] = {
            "iss": self.settings.jwt_issuer,
            "aud": self.settings.jwt_audience,
            "sub": user.id,
            "sid": session.id,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self.settings.access_ttl)).timestamp()),
            "jti": str(uuid4()),
            "auth_method": session.auth_method,
            "platform_permissions": list(user.permissions),
            "break_glass": break_glass,
        }
        header = {"alg": "HS256", "typ": "JWT", "kid": "local-v1"}
        signing_input = b".".join((_encode_json(header), _encode_json(claims)))
        signature = hmac.new(
            self.settings.jwt_signing_key.encode(),
            signing_input,
            hashlib.sha256,
        ).digest()
        return f"{signing_input.decode()}.{_b64encode(signature)}"

    def verify_access(self, token: str) -> dict[str, object]:
        """Verify signature, fixed algorithm, issuer, audience, and time claims."""
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("MALFORMED_JWT")
        header = _decode_json(parts[0])
        claims = _decode_json(parts[1])
        algorithm = header.get("alg")
        if algorithm not in self.ALGORITHMS:
            raise ValueError("JWT_ALGORITHM_REJECTED")
        signing_input = f"{parts[0]}.{parts[1]}".encode()
        expected = hmac.new(
            self.settings.jwt_signing_key.encode(),
            signing_input,
            hashlib.sha256,
        ).digest()
        supplied = _b64decode(parts[2])
        if not hmac.compare_digest(supplied, expected):
            raise ValueError("JWT_SIGNATURE_INVALID")
        missing = [name for name in self.REQUIRED_CLAIMS if name not in claims]
        if missing:
            raise ValueError("JWT_REQUIRED_CLAIM_MISSING")
        now = int(datetime.now(UTC).timestamp())
        if claims["iss"] != self.settings.jwt_issuer:
            raise ValueError("JWT_ISSUER_INVALID")
        if claims["aud"] != self.settings.jwt_audience:
            raise ValueError("JWT_AUDIENCE_INVALID")
        if not isinstance(claims["nbf"], int) or now < claims["nbf"]:
            raise ValueError("JWT_NOT_ACTIVE")
        if not isinstance(claims["exp"], int) or now >= claims["exp"]:
            raise ValueError("JWT_EXPIRED")
        return claims


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, UnicodeEncodeError) as error:
        raise ValueError("MALFORMED_JWT") from error


def _encode_json(value: dict[str, object]) -> bytes:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _b64encode(encoded).encode()


def _decode_json(value: str) -> dict[str, object]:
    try:
        decoded = json.loads(_b64decode(value))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("MALFORMED_JWT") from error
    if not isinstance(decoded, dict):
        raise TypeError("MALFORMED_JWT")
    return decoded
