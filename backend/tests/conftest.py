import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.models import Base


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def db():
    # check_same_thread=False + StaticPool: TestClient dispatches requests on a
    # worker thread distinct from the test's main thread, so an in-memory sqlite
    # session created here must be usable across threads and must not spawn a
    # second (empty) in-memory database when checked out from that other thread.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


@pytest.fixture
def client_with_db(db):
    from app.db import get_session

    app = create_app()
    app.dependency_overrides[get_session] = lambda: (yield db)
    return TestClient(app)
