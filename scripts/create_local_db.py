#!/usr/bin/env python3
"""Create a local users.db and a per-user tracker.db seeded from a CSV.

Usage: python3 scripts/create_local_db.py [csv_path] [username] [password]

Defaults: csv_path=transactions_20260509.csv, username=local, password=local
"""
import os, sys, csv
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
CSV_DEFAULT = ROOT / 'transactions_20260509.csv'

sys.path.insert(0, str(ROOT))
from users import open_users_db, ensure_users_schema, get_user_by_username, create_user, user_db_path
from db_migrations import ensure_schema


def parse_bool(val):
    if not val: return 0
    v = str(val).strip().lower()
    return 1 if v in ('1','yes','y','true','t') else 0


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else CSV_DEFAULT
    username = sys.argv[2] if len(sys.argv) > 2 else 'local'
    password = sys.argv[3] if len(sys.argv) > 3 else 'local'

    data_dir = str(ROOT)
    users_conn = open_users_db(data_dir)
    ensure_users_schema(users_conn)

    user = get_user_by_username(users_conn, username)
    if not user:
        user = create_user(users_conn, username, password, is_admin=True)
        print(f"Created user: {username}")
    else:
        print(f"Using existing user: {username}")

    # Ensure user's tracker.db exists and schema applied
    tdb_path = user_db_path(data_dir, user['dir_name'])
    os.makedirs(os.path.dirname(tdb_path), exist_ok=True)
    conn = sqlite3.connect(tdb_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_schema(conn)

    # Read CSV and insert months + transactions
    if not csv_path.exists():
        print(f"CSV file not found: {csv_path}")
        return

    with open(csv_path, newline='') as fh:
        reader = csv.DictReader(fh)
        months_seen = set(r['Month'] for r in reader if r.get('Month'))
    # Insert months
    for m in sorted(months_seen):
        conn.execute("INSERT OR IGNORE INTO months(month) VALUES(?)", (m,))
    conn.commit()

    with open(csv_path, newline='') as fh:
        reader = csv.DictReader(fh)
        inserted = 0
        for row in reader:
            month = (row.get('Month') or '')
            date = (row.get('Date') or '').strip() or None
            payee = (row.get('Payee') or '').strip()
            category = (row.get('Category') or '').strip()
            try:
                amount = float((row.get('Amount') or '0') or 0)
            except Exception:
                amount = 0.0
            entry_type = 'credit' if (row.get('Type') or '').strip().lower() == 'income' else 'debit'
            status = (row.get('Status') or 'estimated')
            recurs_monthly = parse_bool(row.get('Recurring'))
            is_automatic = parse_bool(row.get('Auto Pay'))
            notes = (row.get('Memo') or '')
            conn.execute(
                "INSERT INTO transactions(month,date,payee,category,amount,entry_type,status,recurs_monthly,is_automatic,is_adhoc,notes,sort_order) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (month, date, payee, category, amount, entry_type, status, recurs_monthly, is_automatic, 0, notes, 0)
            )
            inserted += 1
    conn.commit()
    conn.close()
    print(f"Inserted {inserted} transactions into {tdb_path}")
    print("Done. Run: python3 finance_tracker.py and open http://localhost:5757")


if __name__ == '__main__':
    main()
