import sqlite3

SCHEMA_VERSION = 2


def _column_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def migrate_1_create_core_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS months (
            month TEXT PRIMARY KEY,
            bf_estimated REAL NOT NULL DEFAULT 0,
            bf_actual REAL NOT NULL DEFAULT 0,
            bf_reconciled REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,
            date TEXT,
            payee TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            amount REAL NOT NULL DEFAULT 0,
            entry_type TEXT NOT NULL DEFAULT 'debit',
            status TEXT NOT NULL DEFAULT 'estimated',
            recurs_monthly INTEGER NOT NULL DEFAULT 0,
            is_automatic INTEGER NOT NULL DEFAULT 0,
            is_adhoc INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payee TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            entry_type TEXT NOT NULL DEFAULT 'debit',
            amount REAL NOT NULL DEFAULT 0,
            day_of_month INTEGER,
            is_automatic INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )


def migrate_2_add_month_balance_columns(connection: sqlite3.Connection) -> None:
    for column_name in ("bf_estimated", "bf_actual", "bf_reconciled"):
        if not _column_exists(connection, "months", column_name):
            connection.execute(
                f"ALTER TABLE months ADD COLUMN {column_name} REAL NOT NULL DEFAULT 0"
            )


MIGRATIONS = (
    (1, migrate_1_create_core_schema),
    (2, migrate_2_add_month_balance_columns),
)


def ensure_schema(connection: sqlite3.Connection) -> int:
    current_version = int(connection.execute("PRAGMA user_version").fetchone()[0] or 0)
    for target_version, migration in MIGRATIONS:
        if current_version < target_version:
            migration(connection)
            connection.execute(f"PRAGMA user_version = {target_version}")
            connection.commit()
            current_version = target_version
    return current_version
