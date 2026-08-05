"""Persistence tests proving IAM state survives repository reconstruction."""

from sqlalchemy import create_engine

from iam_service.auth.providers import LocalDevProvider
from iam_service.auth.repository import SqlAlchemyIamRepository
from iam_service.auth.service import SessionService
from iam_service.auth.tokens import TokenService
from iam_service.config import Settings
from iam_service.persistence import Base


def make_service(database_url: str) -> SessionService:
    """Build an IAM service against a fresh SQLAlchemy adapter instance."""
    settings = Settings(database_url=database_url)
    engine = create_engine(database_url)
    return SessionService(
        SqlAlchemyIamRepository(engine),
        TokenService(settings),
        LocalDevProvider(True),
        settings.refresh_ttl,
    )


def test_user_and_refresh_session_survive_repository_reconstruction(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'iam.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)

    first_service = make_service(database_url)
    first_pair = first_service.login("developer")

    reconstructed_service = make_service(database_url)
    principal = reconstructed_service.repo.get_user(
        str(first_pair["principal"]["id"])
    )
    assert principal is not None
    assert principal.username == "developer"

    refreshed = reconstructed_service.refresh(str(first_pair["refresh_token"]))
    assert refreshed["refresh_token"] != first_pair["refresh_token"]

    final_service = make_service(database_url)
    final_service.logout(str(refreshed["refresh_token"]))
    session = final_service.repo.find_session_hash(
        final_service.tokens.hash_refresh(str(refreshed["refresh_token"]))
    )
    assert session is not None
    assert session.status == "revoked"
