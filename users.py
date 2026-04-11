"""
User database management for Finance Tracker.

users.db lives at the root of DATA_DIR and contains:

    users(id, username, password_hash, dir_name, is_admin, created_at)

Each user's data lives at  DATA_DIR/<dir_name>/tracker.db
The dir_name is a UUID string, which prevents path-traversal attacks.
"""
import os, sqlite3, uuid, secrets, string
from werkzeug.security import generate_password_hash, check_password_hash

USERS_DB_NAME = "users.db"
_ALPHABET = string.ascii_letters + string.digits


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


# ── utilities ─────────────────────────────────────────────────────────────────

def generate_random_password(length: int = 16) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
