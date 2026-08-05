"""Double-submit CSRF enforcement."""
import hmac

from flask import Request

SAFE = {"GET", "HEAD", "OPTIONS"}


def validate_csrf(request: Request, trusted_origins: set[str]) -> bool:
    if request.method in SAFE:
        return True
    cookie = request.cookies.get("devops_csrf", "")
    header = request.headers.get("X-CSRF-Token", "")
    origin = request.headers.get("Origin", "")
    fetch_site = request.headers.get("Sec-Fetch-Site", "same-origin")
    return bool(cookie and header and hmac.compare_digest(cookie, header) and origin in trusted_origins and fetch_site in {"same-origin", "same-site"})
