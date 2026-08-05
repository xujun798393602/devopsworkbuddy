"""Append-only audit ingest and bounded query Flask API."""

import base64
import json
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from flask import Flask, Response, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from audit_service.persistence import (
    DatabaseSettings,
    SqlAlchemyAuditRepository,
    SqlAlchemyRuntime,
)
from audit_service.records.ingest_service import AuditIngestService
from audit_service.records.models import AuditRecord
from audit_service.records.repository import InMemoryAuditRepository


class AuditRepository(Protocol):
    """Audit repository operations used by HTTP routes."""

    def append(self, record: AuditRecord) -> AuditRecord:
        """Append or replay one record."""

    def list(self) -> list[AuditRecord]:
        """List records in stable order."""


def create_app(repo: AuditRepository | None = None) -> Flask:
    """Create the audit app with explicit memory injection or SQL production."""
    app = Flask(__name__)
    runtime: SqlAlchemyRuntime | None = None
    if repo is None:
        settings = DatabaseSettings.from_env()
        runtime = SqlAlchemyRuntime(settings.database_url)
    app.extensions["audit_runtime"] = runtime
    app.extensions["audit_repository"] = repo

    def current_repository() -> AuditRepository:
        if repo is not None:
            return repo
        if "audit_repository" not in g:
            if runtime is None:
                raise RuntimeError("Audit SQL runtime is not configured")
            session = runtime.session()
            g.audit_session = session
            g.audit_repository = SqlAlchemyAuditRepository(session)
        return g.audit_repository

    @app.before_request
    def trace() -> None:
        g.trace_id = request.headers.get("X-Trace-Id", str(uuid4()))

    @app.teardown_request
    def close_session(error: BaseException | None) -> None:
        session: Session | None = g.pop("audit_session", None)
        g.pop("audit_repository", None)
        if session is not None:
            if error is not None:
                session.rollback()
            session.close()

    @app.get("/health")
    def health() -> Response:
        return jsonify({"status": "ok", "service": "audit-service"})

    @app.get("/ready")
    def ready():
        if runtime is None:
            return jsonify({"status": "ready", "adapter": "memory"})
        try:
            runtime.ready()
        except SQLAlchemyError:
            return jsonify({"status": "not_ready"}), 503
        return jsonify({"status": "ready", "adapter": "sqlalchemy"})

    @app.post("/internal/api/v1/audit-records")
    def append_record():
        scopes = set(request.headers.get("X-Service-Scopes", "").split())
        session: Session | None = None
        try:
            repository = current_repository()
            record = AuditIngestService(repository).ingest(
                request.get_json(silent=True) or {}, scopes
            )
            session = g.get("audit_session")
            if session is not None:
                session.commit()
        except PermissionError as error:
            return problem(403, str(error), "Audit ingest forbidden")
        except (KeyError, TypeError, ValueError) as error:
            if session is not None:
                session.rollback()
            return problem(422, str(error), str(error))
        except SQLAlchemyError:
            if session is not None:
                session.rollback()
            return problem(503, "DATABASE_UNAVAILABLE", "Audit database unavailable")
        return success(record_data(record)), 201

    @app.get("/api/v1/audit-records")
    def query_records():
        permissions = set(
            request.headers.get("X-Platform-Permissions", "").split()
        )
        if "audit.read" not in permissions:
            return problem(403, "PERMISSION_DENIED", "Audit read permission required")
        try:
            start = datetime.fromisoformat(request.args["from"])
            end = datetime.fromisoformat(request.args["to"])
            limit = min(max(int(request.args.get("limit", 50)), 1), 100)
        except (KeyError, TypeError, ValueError):
            return problem(422, "TIME_RANGE_REQUIRED", "Valid from and to are required")
        if start >= end:
            return problem(422, "INVALID_TIME_RANGE", "from must be before to")
        try:
            filtered = [
                record
                for record in current_repository().list()
                if start <= record.occurred_at <= end
            ]
        except SQLAlchemyError:
            return problem(503, "DATABASE_UNAVAILABLE", "Audit database unavailable")
        mappings = {
            "actor_id": "actor_id",
            "project_id": "project_id",
            "resource_type": "resource_type",
            "action": "action",
            "result": "result",
        }
        for query_name, attribute in mappings.items():
            value = request.args.get(query_name)
            if value is not None:
                filtered = [
                    record
                    for record in filtered
                    if str(getattr(record, attribute)) == value
                ]
        cursor = decode_cursor(request.args.get("cursor"))
        if cursor:
            filtered = [
                record
                for record in filtered
                if (record.occurred_at.isoformat(), record.id) < cursor
            ]
        page = filtered[:limit]
        next_cursor = encode_cursor(page[-1]) if len(filtered) > limit and page else None
        return jsonify(
            {
                "data": [record_data(record) for record in page],
                "meta": {"trace_id": g.trace_id, "next_cursor": next_cursor},
            }
        )

    return app


def record_data(record: AuditRecord) -> dict[str, object]:
    """Serialize an audit fact."""
    return {
        name: value.isoformat() if isinstance(value, datetime) else value
        for name in record.__dataclass_fields__
        if (value := getattr(record, name)) is not None
    } | ({"project_id": None} if record.project_id is None else {})


def encode_cursor(record: AuditRecord) -> str:
    """Encode the stable pagination tuple."""
    raw = json.dumps(
        [record.occurred_at.isoformat(), record.id], separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(value: str | None) -> tuple[str, str] | None:
    """Decode a cursor, treating malformed input as an absent cursor."""
    if not value:
        return None
    try:
        decoded = json.loads(base64.urlsafe_b64decode(value))
        return str(decoded[0]), str(decoded[1])
    except (ValueError, json.JSONDecodeError, IndexError, TypeError):
        return None


def success(data: object) -> Response:
    """Build a successful API envelope."""
    return jsonify({"data": data, "meta": {"trace_id": g.trace_id}})


def problem(status: int, code: str, detail: str):
    """Build an RFC 7807-compatible error response."""
    return (
        jsonify(
            {
                "type": "about:blank",
                "title": code,
                "status": status,
                "detail": detail,
                "error_code": code,
                "trace_id": g.trace_id,
            }
        ),
        status,
        {"Content-Type": "application/problem+json"},
    )


def create_test_app() -> Flask:
    """Create an explicit in-memory app for unit and integration tests."""
    return create_app(InMemoryAuditRepository())
