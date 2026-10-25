"""Tests for API-key creation, use, and revocation."""
import pytest
from tests.helpers import post_json


def create_key(client, name="test key"):
    r = post_json(client, "/api/keys", {"name": name})
    assert r.status_code == 201
    return r.get_json()


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def anon(client):
    """A second test client with no session cookie, on the same data dir."""
    import finance_tracker as ft
    # Not used as a context manager: interleaving with the `client` fixture's
    # preserved request contexts would trip Flask's context-stack check.
    return ft.app.test_client()


def test_create_key_returns_raw_key_once(client):
    k = create_key(client, "agent")
    assert k["key"].startswith("ftk_")
    assert k["name"] == "agent"
    assert k["prefix"] == k["key"][:12]
    listed = client.get("/api/keys").get_json()
    assert [x["id"] for x in listed] == [k["id"]]
    assert "key" not in listed[0] and "key_hash" not in listed[0]


def test_create_key_requires_name(client):
    assert post_json(client, "/api/keys", {"name": "  "}).status_code == 400
    assert post_json(client, "/api/keys", {"name": "x" * 101}).status_code == 400


def test_key_authenticates_api_requests(client, anon):
    k = create_key(client)
    r = anon.get("/api/me", headers=bearer(k["key"]))
    assert r.status_code == 200
    assert r.get_json()["username"] == "testuser"
    assert anon.get("/api/accounts", headers=bearer(k["key"])).status_code == 200
    assert client.get("/api/keys").get_json()[0]["last_used_at"] is not None


def test_key_sees_owner_data(client, anon):
    post_json(client, "/api/accounts", {"name": "Key Checking", "type": "checking"})
    k = create_key(client)
    names = [a["name"] for a in anon.get("/api/accounts", headers=bearer(k["key"])).get_json()]
    assert "Key Checking" in names


def test_invalid_key_rejected(anon):
    assert anon.get("/api/me", headers=bearer("ftk_bogus")).status_code == 401


def test_revoked_key_rejected(client, anon):
    k = create_key(client)
    assert client.delete(f"/api/keys/{k['id']}").status_code == 200
    assert anon.get("/api/me", headers=bearer(k["key"])).status_code == 401
    assert client.delete(f"/api/keys/{k['id']}").status_code == 404


def test_key_cannot_manage_keys(client, anon):
    k = create_key(client)
    h = bearer(k["key"])
    assert anon.get("/api/keys", headers=h).status_code == 403
    assert anon.post("/api/keys", json={"name": "x"}, headers=h).status_code == 403
    assert anon.delete(f"/api/keys/{k['id']}", headers=h).status_code == 403


def test_key_never_grants_admin(tmp_path):
    import json
    import finance_tracker as ft
    from unittest.mock import patch
    from auth import init_secret
    from users import open_users_db, ensure_users_schema, create_user

    data_dir = str(tmp_path)
    init_secret(data_dir)
    uc = open_users_db(data_dir)
    ensure_users_schema(uc)
    create_user(uc, "boss", "pw", is_admin=True)
    uc.close()

    with patch.object(ft, "DATA_DIR", data_dir):
        with ft.app.test_client() as c:
            c.post("/api/login", data=json.dumps({"username": "boss", "password": "pw"}),
                   content_type="application/json")
            assert c.get("/api/admin/users").status_code == 200
            k = create_key(c)
        with ft.app.test_client() as anon:
            h = bearer(k["key"])
            assert anon.get("/api/me", headers=h).get_json()["is_admin"] is False
            assert anon.get("/api/admin/users", headers=h).status_code == 403


def test_cannot_revoke_another_users_key(client, anon):
    import json
    import finance_tracker as ft
    from users import open_users_db, create_user

    k = create_key(client)
    uc = open_users_db(ft.DATA_DIR)
    create_user(uc, "other", "pw")
    uc.close()
    anon.post("/api/login", data=json.dumps({"username": "other", "password": "pw"}),
              content_type="application/json")
    assert anon.get("/api/keys").get_json() == []
    assert anon.delete(f"/api/keys/{k['id']}").status_code == 404


def test_deleting_user_removes_their_keys(client):
    import finance_tracker as ft
    from users import open_users_db, get_user_by_username, delete_user, get_user_by_api_key

    k = create_key(client)
    uc = open_users_db(ft.DATA_DIR)
    delete_user(uc, get_user_by_username(uc, "testuser")["id"])
    assert get_user_by_api_key(uc, k["key"]) is None
    assert uc.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0] == 0
    uc.close()


def test_keys_page_requires_login(anon, client):
    assert anon.get("/keys").status_code == 302
    assert client.get("/keys").status_code == 200
