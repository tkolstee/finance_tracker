"""Shared pytest fixtures for finance_tracker tests.

Each test function gets a fresh temporary data directory, a pre-created
test user, and an authenticated Flask test client.
"""
import json
import pytest
from unittest.mock import patch


@pytest.fixture
def client(tmp_path):
    """Authenticated Flask test client backed by a fresh per-test database."""
    import finance_tracker as ft
    from auth import init_secret
    from users import open_users_db, ensure_users_schema, create_user

    data_dir = str(tmp_path)
    init_secret(data_dir)

    uc = open_users_db(data_dir)
    ensure_users_schema(uc)
    create_user(uc, "testuser", "testpass")
    uc.close()

    ft.app.config["TESTING"] = True
    with patch.object(ft, "DATA_DIR", data_dir):
        with ft.app.test_client() as c:
            c.post(
                "/api/login",
                data=json.dumps({"username": "testuser", "password": "testpass"}),
                content_type="application/json",
            )
            yield c
