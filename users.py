"""
User database management for Finance Tracker.

users.db lives at the root of DATA_DIR and contains:

    users(id, username, password_hash, dir_name, is_admin, created_at)
    api_keys(id, user_id, name, prefix, key_hash, created_at, last_used_at)

Each user's data lives at  DATA_DIR/<dir_name>/tracker.db
The dir_name is a UUID string, which prevents path-traversal attacks.
"""
import os, sqlite3, uuid, secrets, string, hashlib
from werkzeug.security import generate_password_hash, check_password_hash

USERS_DB_NAME = "users.db"
_ALPHABET = string.ascii_letters + string.digits
API_KEY_PREFIX = "ftk_"


# ── path helpers ──────────────────────────────────────────────────────────────

def users_db_path(data_dir: str) -> str:
    return os.path.join(data_dir, USERS_DB_NAME)


def users_db_exists(data_dir: str) -> bool:
    return os.path.exists(users_db_path(data_dir))


def user_data_dir(data_dir: str, dir_name: str) -> str:
    """Return the absolute path to a user's data directory."""
    return os.path.join(data_dir, dir_name)


def user_db_path(data_dir: str, dir_name: str) -> str:
    return os.path.join(user_data_dir(data_dir, dir_name), "tracker.db")


# ── connection ────────────────────────────────────────────────────────────────

def open_users_db(data_dir: str) -> sqlite3.Connection:
    path = users_db_path(data_dir)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── schema ────────────────────────────────────────────────────────────────────

def ensure_users_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            dir_name      TEXT    NOT NULL UNIQUE,
            is_admin      INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS api_keys (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name          TEXT    NOT NULL,
            prefix        TEXT    NOT NULL,
            key_hash      TEXT    NOT NULL UNIQUE,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            last_used_at  TEXT
        );
    """)
    conn.commit()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_user(conn: sqlite3.Connection,
                username: str,
                password: str,
                is_admin: bool = False) -> dict:
    dir_name      = str(uuid.uuid4())
    password_hash = generate_password_hash(password)
    cur = conn.execute(
        "INSERT INTO users(username, password_hash, dir_name, is_admin) VALUES(?,?,?,?)",
        (username, password_hash, dir_name, int(is_admin)),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id,username,dir_name,is_admin,created_at FROM users WHERE id=?",
        (cur.lastrowid,),
    ).fetchone()
    return dict(row)


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_username(conn: sqlite3.Connection, username: str) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def verify_password(conn: sqlite3.Connection,
                    username: str,
                    password: str) -> dict | None:
    """Return the user dict on success, None on failure."""
    user = get_user_by_username(conn, username)
    if not user:
        return None
    if check_password_hash(user["password_hash"], password):
        return user
    return None


def list_users(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT id,username,dir_name,is_admin,created_at FROM users ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


def update_password(conn: sqlite3.Connection,
                    user_id: int,
                    new_password: str) -> None:
    conn.execute(
        "UPDATE users SET password_hash=? WHERE id=?",
        (generate_password_hash(new_password), user_id),
    )
    conn.commit()


def set_admin(conn: sqlite3.Connection, user_id: int, is_admin: bool) -> None:
    conn.execute("UPDATE users SET is_admin=? WHERE id=?", (int(is_admin), user_id))
    conn.commit()


def rename_user(conn: sqlite3.Connection,
                user_id: int,
                new_username: str) -> None:
    conn.execute("UPDATE users SET username=? WHERE id=?", (new_username, user_id))
    conn.commit()


def delete_user(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()


# ── API keys ──────────────────────────────────────────────────────────────────
# Only a SHA-256 hash of each key is stored. Keys are 256-bit random values, so a
# fast hash is sufficient (no salt/KDF needed, unlike passwords). The raw key is
# returned once, at creation, and cannot be recovered afterwards.

_API_KEY_COLS = "id,user_id,name,prefix,created_at,last_used_at"


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_api_key(conn: sqlite3.Connection, user_id: int, name: str) -> tuple[dict, str]:
    """Create a key for user_id. Returns (key metadata, raw key)."""
    raw_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    cur = conn.execute(
        "INSERT INTO api_keys(user_id, name, prefix, key_hash) VALUES(?,?,?,?)",
        (user_id, name, raw_key[:len(API_KEY_PREFIX) + 8], _hash_api_key(raw_key)),
    )
    conn.commit()
    row = conn.execute(
        f"SELECT {_API_KEY_COLS} FROM api_keys WHERE id=?", (cur.lastrowid,)
    ).fetchone()
    return dict(row), raw_key


def list_api_keys(conn: sqlite3.Connection, user_id: int) -> list:
    rows = conn.execute(
        f"SELECT {_API_KEY_COLS} FROM api_keys WHERE user_id=? ORDER BY id", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def delete_api_key(conn: sqlite3.Connection, user_id: int, key_id: int) -> bool:
    """Revoke one of user_id's keys. Returns False if no such key."""
    cur = conn.execute("DELETE FROM api_keys WHERE id=? AND user_id=?", (key_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def get_user_by_api_key(conn: sqlite3.Connection, raw_key: str) -> dict | None:
    """Return the owning user (plus api_key_id) for a valid key, else None.

    Records the key's last_used_at as a side effect.
    """
    row = conn.execute(
        "SELECT k.id AS api_key_id, u.* FROM api_keys k JOIN users u ON u.id = k.user_id "
        "WHERE k.key_hash=?",
        (_hash_api_key(raw_key),),
    ).fetchone()
    if not row:
        return None
    conn.execute("UPDATE api_keys SET last_used_at=datetime('now') WHERE id=?",
                 (row["api_key_id"],))
    conn.commit()
    return dict(row)


# ── utilities ─────────────────────────────────────────────────────────────────

def generate_random_password(length: int = 16) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
