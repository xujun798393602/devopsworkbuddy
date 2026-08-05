import logging
from typing import Any

from flask import Flask, g, jsonify, request

from project_service.authorization import check_authorization
from project_service.collaboration.api import collaboration_blueprint
from project_service.collaboration.service import CollaborationService
from project_service.config import Settings
from project_service.database import Database
from project_service.persistence.uow import SqlAlchemyUnitOfWorkFactory
from project_service.projects.api import projects_blueprint
from project_service.projects.service import ProjectService
from project_service.shared.errors import AppError
from project_service.shared.request_context import RequestContext
from project_service.tasks.api import tasks_blueprint
from project_service.tasks.service import TaskService


def create_app(settings: Settings | None = None) -> Flask:
    """Build the application and production persistence graph."""
    app = Flask(__name__)
    resolved_settings = settings or Settings.from_env()
    database = Database(resolved_settings)
    factory = SqlAlchemyUnitOfWorkFactory(database)
    app.config["SETTINGS"] = resolved_settings
    app.extensions.update(
        database=database,
        project_service=ProjectService(factory),
        collaboration_service=CollaborationService(factory),
        task_service=TaskService(factory),
        event_store=[],
    )

    @app.before_request
    def attach_request_context() -> None:
        g.request_context = RequestContext.from_request(request)

    @app.after_request
    def add_trace_header(response):
        response.headers["X-Trace-Id"] = g.request_context.trace_id
        return response

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": resolved_settings.service_name})

    @app.post("/internal/api/v1/authorization/check")
    def internal_authorization_check():
        """Authorize a project-scoped workflow action for a trusted service."""
        supplied_token = request.headers.get("X-Internal-Service-Token", "")
        if supplied_token != resolved_settings.internal_service_token:
            return (
                jsonify(
                    {
                        "type": "about:blank",
                        "title": "INTERNAL_SERVICE_UNAUTHORIZED",
                        "status": 401,
                        "detail": "Internal service authentication failed",
                        "error_code": "INTERNAL_SERVICE_UNAUTHORIZED",
                        "trace_id": g.request_context.trace_id,
                    }
                ),
                401,
                {"Content-Type": "application/problem+json"},
            )
        payload = request.get_json(silent=True) or {}
        required = ("actor_id", "project_id", "action")
        if any(not isinstance(payload.get(field), str) or not payload[field] for field in required):
            return (
                jsonify(
                    {
                        "type": "about:blank",
                        "title": "VALIDATION_FAILED",
                        "status": 422,
                        "detail": "actor_id, project_id, and action are required",
                        "error_code": "VALIDATION_FAILED",
                        "trace_id": g.request_context.trace_id,
                    }
                ),
                422,
                {"Content-Type": "application/problem+json"},
            )
        result = check_authorization(
            factory,
            str(payload["actor_id"]),
            str(payload["project_id"]),
            str(payload["action"]),
        )
        return jsonify({"data": result, "meta": {"trace_id": g.request_context.trace_id}})

    @app.get("/ready")
    def ready():
        if database.ping():
            return jsonify({"status": "ok", "checks": {"database": {"status": "ok"}}})
        return jsonify({"status": "unavailable", "checks": {"database": {"status": "fail"}}}), 503

    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        body: dict[str, Any] = {
            "type": error.error_type,
            "title": error.error_code,
            "status": error.status_code,
            "detail": error.message,
            "error_code": error.error_code,
            "trace_id": g.request_context.trace_id,
        }
        if error.errors:
            body["errors"] = error.errors
        return jsonify(body), error.status_code, {"Content-Type": "application/problem+json"}

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        trace_id = g.request_context.trace_id
        logging.getLogger(__name__).error(
            "Unhandled application error trace_id=%s error_type=%s",
            trace_id,
            type(error).__name__,
            exc_info=False,
        )
        return (
            jsonify(
                {
                    "type": "about:blank",
                    "title": "INTERNAL_SERVER_ERROR",
                    "status": 500,
                    "detail": "An unexpected error occurred",
                    "error_code": "INTERNAL_SERVER_ERROR",
                    "trace_id": trace_id,
                }
            ),
            500,
            {"Content-Type": "application/problem+json"},
        )

    @app.errorhandler(404)
    def handle_route_not_found(_error):
        return (
            jsonify(
                {
                    "type": "about:blank",
                    "title": "ROUTE_NOT_FOUND",
                    "status": 404,
                    "detail": "The requested route does not exist",
                    "error_code": "ROUTE_NOT_FOUND",
                    "trace_id": g.request_context.trace_id,
                }
            ),
            404,
            {"Content-Type": "application/problem+json"},
        )

    app.register_blueprint(projects_blueprint)
    app.register_blueprint(collaboration_blueprint)
    app.register_blueprint(tasks_blueprint)
    return app
