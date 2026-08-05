from iam_service.app import create_app
from iam_service.config import Settings


def test_login_me_logout() -> None:
    client = create_app(Settings()).test_client()
    login = client.post("/api/v1/auth/login", json={"username": "developer"})
    assert login.status_code == 201
    tokens = login.get_json()["data"]
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 204


def test_production_dev_auth_fails_fast() -> None:
    try:
        Settings(app_env="production", local_dev_auth_enabled=True).validate()
        assert False
    except RuntimeError:
        assert True
