import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Importing app.main initializes its default engine. Point that one-time
# initialization at an isolated temp file before import, never at user data.
_bootstrap_dir = Path(tempfile.mkdtemp(prefix="vyrnexis-pytest-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_bootstrap_dir / 'bootstrap.db'}"
os.environ.setdefault("JWT_SECRET", "pytest-only-signing-key-never-for-deployment")

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VYRNEXIS_EVIDENCE_DIR", str(tmp_path / "evidence-storage"))
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'isolated-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.state.test_session_factory = TestSession
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.test_session_factory
    test_engine.dispose()
