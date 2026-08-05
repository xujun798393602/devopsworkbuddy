from notification_service.notifications.templates import (
    TemplateRenderer,
    validate_target_url,
)


def test_strict_template_and_internal_url() -> None:
    title, body = TemplateRenderer().render(
        "workflow.started", {"instance_id": "<x>"}
    )
    assert title == "Workflow started" and "<x>" not in body
    try:
        validate_target_url("https://evil.test/app/")
        assert False
    except ValueError:
        assert True
