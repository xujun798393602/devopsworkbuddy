from dataclasses import dataclass
from uuid import uuid4

from flask import Request


@dataclass(frozen=True, slots=True)
class RequestContext:
    trace_id: str
    actor_id: str

    @classmethod
    def from_request(cls, request: Request) -> "RequestContext":
        trace_id = request.headers.get("X-Trace-Id", str(uuid4()))
        actor_id = request.headers.get("X-Actor-Id", "development-user")
        return cls(trace_id=trace_id, actor_id=actor_id)
