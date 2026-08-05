"""Collaboration domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum

from project_service.shared.errors import ConflictError, ValidationError, VersionConflictError


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


@dataclass(slots=True)
class ProjectMembership:
    id: str
    project_id: str
    user_id: str
    role: Role
    status: str
    joined_at: datetime
    joined_by: str
    removed_at: datetime | None = None
    removed_by: str | None = None
    version: int = 1

    def change_role(self, role: Role, expected_version: int) -> None:
        if self.version != expected_version:
            raise VersionConflictError()
        if self.role == Role.OWNER or role == Role.OWNER:
            raise ConflictError(
                "Owner role can only change through owner transfer", "OWNER_TRANSFER_REQUIRED"
            )
        self.role = role
        self.version += 1

    def remove(self, actor_id: str, expected_version: int, now: datetime) -> None:
        if self.version != expected_version:
            raise VersionConflictError()
        if self.role == Role.OWNER:
            raise ConflictError("Owner cannot be removed", "OWNER_TRANSFER_REQUIRED")
        self.status, self.removed_by, self.removed_at = "removed", actor_id, now
        self.version += 1

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["role"] = self.role.value
        for field in ("joined_at", "removed_at"):
            value = data[field]
            data[field] = value.isoformat() if value else None
        return data


_VERSION_TRANSITIONS = {
    "planned": {"active", "canceled"},
    "active": {"released", "canceled"},
    "released": {"archived"},
}
_ITERATION_TRANSITIONS = {"planned": {"active", "canceled"}, "active": {"completed", "canceled"}}


@dataclass(slots=True)
class ReleaseVersion:
    id: str
    project_id: str
    business_no: str
    name: str
    description: str
    status: str
    planned_release_date: date | None
    release_date: date | None
    version: int
    created_at: datetime
    updated_at: datetime

    def update(self, fields: dict[str, object], expected_version: int) -> None:
        _check_version(self.version, expected_version)
        for key in ("name", "description", "planned_release_date"):
            if key in fields:
                setattr(self, key, fields[key])
        self.version += 1

    def transition(self, target: str, force: bool, reason: str | None, today: date) -> None:
        if target not in _VERSION_TRANSITIONS.get(self.status, set()):
            raise ConflictError("Invalid version state transition", "INVALID_STATE_TRANSITION")
        if force and not reason:
            raise ValidationError("reason is required for a forced transition")
        self.status = target
        if target == "released":
            self.release_date = today
        self.version += 1

    def to_dict(self) -> dict[str, object]:
        return _serialize(asdict(self))


@dataclass(slots=True)
class Iteration:
    id: str
    project_id: str
    business_no: str
    name: str
    goal: str
    start_date: date
    end_date: date
    capacity_minutes: int | None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValidationError("end_date must not be earlier than start_date")
        if self.capacity_minutes is not None and self.capacity_minutes < 0:
            raise ValidationError("capacity_minutes must be non-negative")

    def update(self, fields: dict[str, object], expected_version: int) -> None:
        _check_version(self.version, expected_version)
        for key in ("name", "goal", "start_date", "end_date", "capacity_minutes"):
            if key in fields:
                setattr(self, key, fields[key])
        if self.end_date < self.start_date:
            raise ValidationError("end_date must not be earlier than start_date")
        self.version += 1

    def transition(self, target: str, force: bool, reason: str | None) -> None:
        if target not in _ITERATION_TRANSITIONS.get(self.status, set()):
            raise ConflictError("Invalid iteration state transition", "INVALID_STATE_TRANSITION")
        if force and not reason:
            raise ValidationError("reason is required for a forced transition")
        self.status = target
        self.version += 1

    def to_dict(self) -> dict[str, object]:
        return _serialize(asdict(self))


def _check_version(current: int, expected: int) -> None:
    if current != expected:
        raise VersionConflictError()


def _serialize(data: dict[str, object]) -> dict[str, object]:
    return {
        key: value.isoformat() if isinstance(value, date | datetime) else value
        for key, value in data.items()
    }
