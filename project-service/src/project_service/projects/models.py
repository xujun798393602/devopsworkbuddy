from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from project_service.shared.errors import ConflictError, VersionConflictError


@dataclass(slots=True)
class Project:
    """Project aggregate exposed by the application layer."""

    id: str
    business_no: str
    name: str
    description: str
    owner_id: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    def archive(self, expected_version: int) -> None:
        """Archive the project using optimistic concurrency control."""
        if self.version != expected_version:
            raise VersionConflictError()
        if self.status == "archived":
            raise ConflictError("Project is already archived")
        self.status = "archived"
        self.version += 1
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, object]:
        """Serialize the aggregate without leaking persistence details."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def create(cls, *, project_id: str, business_no: str, name: str, description: str, owner_id: str) -> "Project":
        now = datetime.now(UTC)
        return cls(project_id, business_no, name, description, owner_id, "active", 1, now, now)
