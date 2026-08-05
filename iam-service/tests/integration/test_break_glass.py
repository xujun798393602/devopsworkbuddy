from iam_service.app import create_app
from iam_service.config import Settings


class FakeTotp:
    def verify(self, code: str) -> bool:
        return code == "123456"


def test_break_glass_requires_context_network_and_totp() -> None:
    app = create_app(Settings(), totp_verifier=FakeTotp())
    client = app.test_client()
    denied = client.post("/api/v1/emergency-auth/login", json={"username": "developer", "code": "bad", "reason": "incident", "ticket": "INC-1"}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert denied.status_code == 401
    allowed = client.post("/api/v1/emergency-auth/login", json={"username": "developer", "code": "123456", "reason": "incident", "ticket": "INC-1"}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert allowed.status_code == 201
    assert allowed.get_json()["data"]["principal"]["break_glass"] is True
    assert "123456" not in str(app.extensions["session_service"].audit_events)


def test_production_rejects_development_jwt_provider() -> None:
    settings = Settings(app_env="production", local_dev_auth_enabled=False, jwt_signing_key="external", refresh_pepper="external", jwt_provider="development-hs256", break_glass_enabled=False)
    try:
        settings.validate()
        assert False
    except RuntimeError:
        assert True
