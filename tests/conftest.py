from __future__ import annotations

import os
import re
from collections.abc import Generator
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_engine, get_session_factory, reset_db_caches
import app.models  # noqa: F401


@pytest.fixture
def db_setup(tmp_path, monkeypatch) -> Generator[None, None, None]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("RMS_DATABASE_URL", db_url)
    monkeypatch.setenv("RMS_SECRET_KEY", "test-secret")
    monkeypatch.setenv("RMS_ENV", "development")
    monkeypatch.setenv("RMS_SUPPORTED_LANGUAGES", "de,en,fr,pt,es,yo,sw")
    monkeypatch.setenv("RMS_DEFAULT_LANGUAGE", "de")
    monkeypatch.setenv("RMS_DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("RMS_OIDC_ENABLED", "true")
    monkeypatch.setenv("RMS_REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("RMS_S3_ENDPOINT_URL", "http://localhost:9000")
    monkeypatch.setenv("RMS_S3_ACCESS_KEY_ID", "minioadmin")
    monkeypatch.setenv("RMS_S3_SECRET_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("RMS_S3_BUCKET", "rms-test")
    monkeypatch.setenv("RMS_S3_KEY_PREFIX", "rms")

    get_settings.cache_clear()
    reset_db_caches()

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

    get_settings.cache_clear()
    reset_db_caches()


@pytest.fixture
def db_session(db_setup):
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_setup):
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    if not match:
        raise AssertionError("CSRF token not found in login HTML")
    return match.group(1)


@pytest.fixture
def dev_login(client):
    def _login(*, role: str = "super_admin", email: str = "admin@example.com", display_name: str = "Admin User"):
        login_page = client.get("/auth/login")
        assert login_page.status_code == 200
        csrf = extract_csrf(login_page.text)
        resp = client.post(
            "/auth/dev-login",
            data={
                "csrf_token": csrf,
                "email": email,
                "display_name": display_name,
                "role": role,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        return me.json()["csrf_token"]

    return _login


@pytest.fixture
def postgres_engine():
    """A real PostgreSQL engine, or skip.

    The rest of the suite runs on SQLite, which cannot exercise the advisory
    lock that guarantees two concurrent requests cannot book the same slot.
    Set RMS_TEST_POSTGRES_URL to run those tests:

        RMS_TEST_POSTGRES_URL=postgresql+psycopg://user@host:5432/db pytest
    """
    import sqlalchemy as sa

    url = os.getenv("RMS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("RMS_TEST_POSTGRES_URL not set; skipping PostgreSQL-only test")

    from app.db.base import Base
    import app.models  # noqa: F401

    engine = sa.create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
