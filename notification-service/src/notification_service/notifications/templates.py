"""Strict, escaped notification template rendering."""

from jinja2 import Environment, StrictUndefined, select_autoescape

TEMPLATES: dict[str, tuple[str, str]] = {
    "workflow.started": (
        "Workflow started",
        "Workflow {{ instance_id }} started.",
    ),
    "workflow.transitioned": (
        "Workflow updated",
        "Workflow {{ instance_id }} moved to {{ to_state }}.",
    ),
}


class TemplateRenderer:
    """Render allowlisted notification templates with strict escaping."""

    def __init__(self) -> None:
        self.env = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default=True),
        )

    def render(
        self,
        key: str,
        variables: dict[str, object],
    ) -> tuple[str, str]:
        """Render a title and body while preserving HTML entity escaping."""
        if key not in TEMPLATES:
            raise ValueError("UNKNOWN_TEMPLATE")
        title, body = TEMPLATES[key]
        return (
            self.env.from_string(title).render(**variables),
            self.env.from_string(body).render(**variables),
        )


def validate_target_url(value: str | None) -> str | None:
    """Accept only normalized internal application paths."""
    if value is None:
        return None
    if (
        not value.startswith("/app/")
        or "://" in value
        or "\\" in value
        or value.startswith("//")
    ):
        raise ValueError("UNSAFE_TARGET_URL")
    return value
