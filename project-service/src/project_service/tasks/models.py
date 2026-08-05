"""Task and immutable Worklog domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from project_service.shared.errors import ValidationError, VersionConflictError


@dataclass(slots=True)
class Task:
    id: str
    business_no: str
    project_id: str
    title: str
    description: str
    task_type: str
    priority: str
    status: str
    creator_id: str
    assignee_id: str | None
    release_version_id: str | None
    iteration_id: str | None
    estimated_minutes: int
    planned_start_at: datetime | None
    planned_end_at: datetime | None
    actual_start_at: datetime | None
    actual_end_at: datetime | None
    workflow_template_key: str
    workflow_version: int
    version: int
    created_at: datetime
    updated_at: datetime
    participant_ids: list[str] = field(default_factory=list)
    actual_minutes: int = 0

    def __post_init__(self) -> None:
        if not self.release_version_id and not self.iteration_id:
            raise ValidationError("A task must reference a version or iteration")
        if not 0 <= self.estimated_minutes <= 10_000_000:
            raise ValidationError("estimated_minutes is out of range")
        if (
            self.planned_start_at
            and self.planned_end_at
            and self.planned_end_at < self.planned_start_at
        ):
            raise ValidationError("planned_end_at must not precede planned_start_at")

    def update(self, fields: dict[str, object], expected_version: int) -> None:
        if self.version != expected_version:
            raise VersionConflictError()
        forbidden = {
            "status",
            "actual_start_at",
            "actual_end_at",
            "actual_minutes",
            "version",
        } & fields.keys()
        if forbidden:
            raise ValidationError("Status and actual fields are read-only")
        for key, value in fields.items():
            setattr(self, key, value)
        self.__post_init__()
        self.participant_ids = list(dict.fromkeys(self.participant_ids))
        self.version += 1

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        return {
            key: value.isoformat() if isinstance(value, date | datetime) else value
            for key, value in data.items()
        }


@dataclass(frozen=True, slots=True)
class Worklog:
    id: str
    project_id: str
    task_id: str
    user_id: str
    recorded_by: str
    work_date: date
    minutes_delta: int
    description: str
    corrects_worklog_id: str | None
    correction_reason: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        if self.minutes_delta == 0 or not -1440 <= self.minutes_delta <= 1440:
            raise ValidationError("minutes_delta must be between -1440 and 1440 and non-zero")
        if self.corrects_worklog_id is None and self.minutes_delta < 1:
            raise ValidationError("A normal Worklog must add positive minutes")
        if self.corrects_worklog_id and not self.correction_reason:
            raise ValidationError("correction_reason is required")
        if not self.description.strip():
            raise ValidationError("description is required")

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["work_date"] = self.work_date.isoformat()
        data["created_at"] = self.created_at.isoformat()
        return data
