from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    message: str
    error_code: str
    status_code: int
    error_type: str = "about:blank"
    errors: list[dict[str, Any]] | None = None


class ValidationError(AppError):
    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message, "VALIDATION_ERROR", 422, errors=errors)


class NotFoundError(AppError):
    def __init__(self, resource: str = "Resource", resource_id: str = "") -> None:
        detail = "Resource not found" if not resource_id else f"{resource} not found: {resource_id}"
        super().__init__(detail, "RESOURCE_NOT_FOUND", 404)


class ForbiddenError(AppError):
    def __init__(self, message: str = "The actor is not allowed to perform this action") -> None:
        super().__init__(message, "FORBIDDEN", 403)


class ConflictError(AppError):
    def __init__(self, message: str, error_code: str = "RESOURCE_CONFLICT") -> None:
        super().__init__(message, error_code, 409)


class VersionConflictError(AppError):
    def __init__(self) -> None:
        super().__init__("The resource version does not match If-Match", "VERSION_CONFLICT", 412)
