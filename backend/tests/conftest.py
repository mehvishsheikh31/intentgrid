import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401  (registers the tables)
from app.config import settings, to_sqlalchemy_url
from app.db import Base


@pytest.fixture(scope="session")
def test_engine():
    if not settings.test_database_url:
        pytest.fail("TEST_DATABASE_URL is missing in backend/.env", pytrace=False)
    if settings.test_database_url == settings.database_url:
        pytest.fail("TEST_DATABASE_URL must be a separate Neon branch, not DATABASE_URL", pytrace=False)
    engine = create_engine(to_sqlalchemy_url(settings.test_database_url), pool_pre_ping=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(test_engine):
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db):
    """FastAPI test client that uses the rolled-back test session."""
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
