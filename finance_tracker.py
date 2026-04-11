#!/usr/bin/env python3
"""
Finance Tracker — Monthly Budget & Transaction Tracking App
Run with: python3 finance_tracker.py  →  http://localhost:5757

Environment variables:
  FINANCE_TRACKER_DATA_DIR   Root data directory (default: script directory)
  FINANCE_TRACKER_SECRET     Persistent JWT signing key (auto-generated if unset)
  FINANCE_TRACKER_TOKEN_TTL  Token lifetime in seconds (default: 604800 = 7 days)
  ADMIN_USER                 Admin username for first-time setup (default: admin)
  ADMIN_PASSWORD             Admin password for first-time setup (random if unset)

CLI flags:
  --reset-admin-password     Reset the first user's password (uses ADMIN_PASSWORD
                             env var, or generates a random one and prints it)
"""

import os, sys, sqlite3, calendar, shutil
from collections import defaultdict
from datetime import date
from flask import (Flask, request, jsonify, render_template,
                   g, redirect, url_for, make_response)

from db_migrations import ensure_schema
from version import APP_VERSION
from users import (
    users_db_exists, open_users_db, ensure_users_schema,
    create_user, get_user_by_id, get_user_by_username, verify_password,
    list_users, update_password, set_admin, rename_user, delete_user,
    generate_random_password, user_data_dir, user_db_path,
)
from auth import (
    require_auth, require_admin,
    generate_token, decode_token,
    cookie_kwargs, clear_cookie_kwargs,
    init_secret,
)

app = Flask(__name__)
app.config["APP_VERSION"] = APP_VERSION

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.abspath(os.environ.get("FINANCE_TRACKER_DATA_DIR", SCRIPT_DIR))


# ──────────────────────────── DB helpers ────────────────────────────

def get_users_conn():
    return open_users_db(DATA_DIR)


def get_user_db():
    """Return a connection to the current authenticated user's tracker.db.
    Runs ensure_schema() so per-user DBs are migrated on first access.
    """
    uc   = get_users_conn()
    user = get_user_by_id(uc, g.user_id)
    uc.close()
    if not user:
        raise RuntimeError("User not found")
    udir   = user_data_dir(DATA_DIR, user["dir_name"])
    dbpath = user_db_path(DATA_DIR, user["dir_name"])
    os.makedirs(udir, exist_ok=True)
    c = sqlite3.connect(dbpath)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    ensure_schema(c)
    return c


def D(row):
    return dict(row) if row else None


def signed(entry_type, amount):
    return amount if entry_type == "credit" else -amount


def get_first_month(c):
    row = c.execute("SELECT month FROM months ORDER BY month LIMIT 1").fetchone()
    return row["month"] if row else None


def compute_bf_for_month(c, month):
    first = c.execute(
        "SELECT month,bf_estimated,bf_actual,bf_reconciled FROM months ORDER BY month LIMIT 1"
    ).fetchone()
    if not first or month <= first["month"]:
        if not first:
            return (0.0, 0.0, 0.0)
        return (float(first["bf_estimated"]), float(first["bf_actual"]), float(first["bf_reconciled"]))
    all_rows = c.execute(
        "SELECT month,entry_type,amount,status FROM transactions "
        "WHERE month >= ? AND month < ? ORDER BY month",
        (first["month"], month)).fetchall()
    months_txns = defaultdict(list)
    for r in all_rows:
        months_txns[r["month"]].append(r)
    all_months = sorted(set(months_txns.keys()) | {first["month"]})
    bf_est = float(first["bf_estimated"])
    bf_act = float(first["bf_actual"])
    bf_rec = float(first["bf_reconciled"])
    for m in all_months:
        if m >= month:
            break
        txns = months_txns.get(m, [])
        bf_est = round(bf_est + sum(signed(r["entry_type"], r["amount"]) for r in txns), 2)
        bf_act = round(bf_act + sum(signed(r["entry_type"], r["amount"]) for r in txns
                                    if r["status"] in ("actual", "reconciled")), 2)
        bf_rec = round(bf_rec + sum(signed(r["entry_type"], r["amount"]) for r in txns
                                    if r["status"] == "reconciled"), 2)
    return (bf_est, bf_act, bf_rec)


# ──────────────────────────── Auth / login routes ────────────────────────────

@app.route("/login")
def login_page():
    # If already authenticated, go straight to the app
    token   = request.cookies.get("ft_token")
    payload = decode_token(token) if token else None
    if payload:
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/api/login", methods=["POST"])
def api_login():
    d        = request.get_json() or {}
    username = d.get("username", "").strip()
    password = d.get("password", "")
    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400
    uc   = get_users_conn()
    user = verify_password(uc, username, password)
    uc.close()
    if not user:
        return jsonify({"error": "Invalid username or password"}), 401
    token = generate_token(user["id"], user["username"], bool(user["is_admin"]))
    resp  = make_response(jsonify({
        "username": user["username"],
        "is_admin": bool(user["is_admin"]),
    }))
    resp.set_cookie(**cookie_kwargs(token))
    return resp


@app.route("/api/logout", methods=["POST"])
def api_logout():
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie(**clear_cookie_kwargs())
    return resp


@app.route("/api/me")
@require_auth
def api_me():
    return jsonify({"user_id": g.user_id, "username": g.username, "is_admin": g.is_admin})


# ──────────────────────────── Admin UI route ─────────────────────────────────

@app.route("/admin")
def admin_page():
    token   = request.cookies.get("ft_token")
    payload = decode_token(token) if token else None
    if not payload:
        return redirect(url_for("login_page"))
    if not payload.get("is_admin"):
        return redirect(url_for("index"))
    return render_template("admin.html", current_user=payload["username"])


# ──────────────────────────── Admin API routes ───────────────────────────────

@app.route("/api/admin/users")
@require_admin
def admin_list_users():
    uc    = get_users_conn()
    users = list_users(uc)
    uc.close()
    return jsonify([{k: v for k, v in u.items() if k != "password_hash"} for u in users])


@app.route("/api/admin/users", methods=["POST"])
@require_admin
def admin_create_user():
    d        = request.get_json() or {}
    username = d.get("username", "").strip()
    password = d.get("password", "").strip()
    is_admin = bool(d.get("is_admin", False))
    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400
    uc = get_users_conn()
    try:
        user = create_user(uc, username, password, is_admin=is_admin)
    except Exception as e:
        uc.close()
        return jsonify({"error": str(e)}), 400
    uc.close()
    os.makedirs(user_data_dir(DATA_DIR, user["dir_name"]), exist_ok=True)
    return jsonify(user), 201


@app.route("/api/admin/users/<int:uid>", methods=["PUT"])
@require_admin
def admin_update_user(uid):
    d  = request.get_json() or {}
    uc = get_users_conn()
    if not get_user_by_id(uc, uid):
        uc.close()
        return jsonify({"error": "not found"}), 404
    if "username" in d and d["username"].strip():
        try:
            rename_user(uc, uid, d["username"].strip())
        except Exception as e:
            uc.close()
            return jsonify({"error": str(e)}), 400
    if "is_admin" in d:
        if uid == g.user_id and not d["is_admin"]:
            uc.close()
            return jsonify({"error": "Cannot remove your own admin status"}), 400
        set_admin(uc, uid, bool(d["is_admin"]))
    updated = get_user_by_id(uc, uid)
    uc.close()
    return jsonify({k: v for k, v in updated.items() if k != "password_hash"})


@app.route("/api/admin/users/<int:uid>/reset-password", methods=["POST"])
@require_admin
def admin_reset_password(uid):
    d         = request.get_json() or {}
    new_pass  = d.get("password", "").strip()
    generated = False
    if not new_pass:
        new_pass  = generate_random_password()
        generated = True
    uc   = get_users_conn()
    user = get_user_by_id(uc, uid)
    if not user:
        uc.close()
        return jsonify({"error": "not found"}), 404
    update_password(uc, uid, new_pass)
    uc.close()
    result = {"ok": True}
    if generated:
        result["generated_password"] = new_pass
    return jsonify(result)


@app.route("/api/admin/users/<int:uid>", methods=["DELETE"])
@require_admin
def admin_delete_user(uid):
    if uid == g.user_id:
        return jsonify({"error": "Cannot delete yourself"}), 400
    uc   = get_users_conn()
    user = get_user_by_id(uc, uid)
    if not user:
        uc.close()
        return jsonify({"error": "not found"}), 404
    delete_user(uc, uid)
    uc.close()
    return jsonify({"deleted": uid})


@app.route("/api/admin/users/<int:uid>/reset-data", methods=["POST"])
@require_admin
def admin_reset_user_data(uid):
    """Reset a user's transaction/template data.
    mode: 'monthly'  → delete transactions + months (keep templates)
          'template' → delete templates only
          'all'      → delete everything
    """
    d    = request.get_json() or {}
    mode = d.get("mode", "monthly")
    if mode not in ("monthly", "template", "all"):
        return jsonify({"error": "mode must be monthly, template, or all"}), 400
    uc   = get_users_conn()
    user = get_user_by_id(uc, uid)
    uc.close()
    if not user:
        return jsonify({"error": "not found"}), 404
    dbpath = user_db_path(DATA_DIR, user["dir_name"])
    if not os.path.exists(dbpath):
        return jsonify({"ok": True, "note": "No database found for this user"})
    c = sqlite3.connect(dbpath)
    if mode == "all":
        c.execute("DELETE FROM transactions")
        c.execute("DELETE FROM templates")
        c.execute("DELETE FROM months")
    elif mode == "monthly":
        c.execute("DELETE FROM transactions")
        c.execute("DELETE FROM months")
    elif mode == "template":
        c.execute("DELETE FROM templates")
    c.commit()
    c.close()
    return jsonify({"ok": True, "mode": mode, "user": user["username"]})


# ──────────────────────────── Month API ──────────────────────────────────────

@app.route("/api/months/list")
@require_auth
def months_list():
    c    = get_user_db()
    rows = c.execute("SELECT month, COUNT(*) n FROM transactions GROUP BY month").fetchall()
    c.close()
    return jsonify({r["month"]: r["n"] for r in rows})


@app.route("/api/months/<month>")
@require_auth
def get_month(month):
    c        = get_user_db()
    first    = get_first_month(c)
    is_first = (first is None or month == first)
    c.close()
    return jsonify({"month": month, "is_first_month": is_first})


@app.route("/api/months/<month>/bf", methods=["PUT"])
@require_auth
def update_month_bf(month):
    d   = request.get_json() or {}
    bfe = float(d.get("bf_estimated", 0))
    bfa = float(d.get("bf_actual", 0))
    bfr = float(d.get("bf_reconciled", 0))
    c   = get_user_db()
    c.execute(
        "INSERT INTO months(month,bf_estimated,bf_actual,bf_reconciled) VALUES(?,?,?,?) "
        "ON CONFLICT(month) DO UPDATE SET bf_estimated=excluded.bf_estimated,"
        "bf_actual=excluded.bf_actual,bf_reconciled=excluded.bf_reconciled",
        (month, bfe, bfa, bfr))
    c.commit()
    c.close()
    return jsonify({"month": month, "bf_estimated": bfe, "bf_actual": bfa, "bf_reconciled": bfr})


@app.route("/api/months/<month>/balances")
@require_auth
def month_balances(month):
    c        = get_user_db()
    first    = get_first_month(c)
    is_first = (first is None or month == first)
    bf_est, bf_act, bf_rec = compute_bf_for_month(c, month)
    rows = c.execute(
        "SELECT entry_type,amount,status FROM transactions WHERE month=?", (month,)
    ).fetchall()
    c.close()
    s = lambda r: signed(r["entry_type"], r["amount"])
    return jsonify({
        "bf_est":         bf_est,
        "bf_act":         bf_act,
        "bf_rec":         bf_rec,
        "estimated":      round(bf_est + sum(s(r) for r in rows), 2),
        "actual":         round(bf_act + sum(s(r) for r in rows if r["status"] in ("actual", "reconciled")), 2),
        "reconciled":     round(bf_rec + sum(s(r) for r in rows if r["status"] == "reconciled"), 2),
        "is_first_month": is_first,
    })


@app.route("/api/balances/global")
@require_auth
def global_balances():
    c     = get_user_db()
    first = c.execute(
        "SELECT bf_estimated,bf_actual,bf_reconciled FROM months ORDER BY month LIMIT 1"
    ).fetchone()
    bf_est = float(first["bf_estimated"]) if first else 0.0
    bf_act = float(first["bf_actual"])    if first else 0.0
    bf_rec = float(first["bf_reconciled"]) if first else 0.0
    today  = date.today().isoformat()
    rows   = c.execute(
        "SELECT entry_type,amount,status FROM transactions WHERE date IS NOT NULL AND date<=?",
        (today,)
    ).fetchall()
    c.close()
    s = lambda r: signed(r["entry_type"], r["amount"])
    return jsonify({
        "estimated":  round(bf_est + sum(s(r) for r in rows), 2),
        "actual":     round(bf_act + sum(s(r) for r in rows if r["status"] in ("actual", "reconciled")), 2),
        "reconciled": round(bf_rec + sum(s(r) for r in rows if r["status"] == "reconciled"), 2),
    })


@app.route("/api/meta")
@require_auth
def app_meta():
    c              = get_user_db()
    schema_version = int(c.execute("PRAGMA user_version").fetchone()[0] or 0)
    c.close()
    return jsonify({
        "app_version":       APP_VERSION,
        "db_schema_version": schema_version,
        "username":          g.username,
        "is_admin":          g.is_admin,
    })


# ──────────────────────────── Transaction API ─────────────────────────────────

@app.route("/api/months/<month>/transactions")
@require_auth
def list_txns(month):
    c    = get_user_db()
    rows = c.execute(
        "SELECT id,month,date,payee,category,amount,entry_type,status,"
        "recurs_monthly,is_automatic,is_adhoc,notes,sort_order "
        "FROM transactions WHERE month=? ORDER BY is_adhoc,entry_type DESC,sort_order,id",
        (month,)
    ).fetchall()
    c.close()
    return jsonify([D(r) for r in rows])


@app.route("/api/months/<month>/transactions", methods=["POST"])
@require_auth
def add_txn(month):
    d = request.get_json()
    c = get_user_db()
    c.execute("INSERT OR IGNORE INTO months(month) VALUES(?)", (month,))
    cur = c.execute(
        "INSERT INTO transactions(month,date,payee,category,amount,entry_type,"
        "status,recurs_monthly,is_automatic,is_adhoc,notes,sort_order) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (month, d.get("date"), d.get("payee", ""), d.get("category", ""),
         float(d.get("amount", 0)), d.get("entry_type", "debit"), d.get("status", "estimated"),
         int(d.get("recurs_monthly", 0)), int(d.get("is_automatic", 0)),
         int(d.get("is_adhoc", 0)), d.get("notes"), int(d.get("sort_order", 0))))
    new_id = cur.lastrowid
    c.commit()
    return jsonify(D(c.execute("SELECT * FROM transactions WHERE id=?", (new_id,)).fetchone())), 201


@app.route("/api/transactions/<int:tid>", methods=["PUT"])
@require_auth
def update_txn(tid):
    d = request.get_json()
    fields, vals = [], []
    for f in ["date", "payee", "category", "amount", "entry_type", "status",
              "recurs_monthly", "is_automatic", "is_adhoc", "notes", "sort_order"]:
        if f not in d:
            continue
        fields.append(f"{f}=?")
        v = d[f]
        if f == "amount":
            v = float(v)
        elif f in ("recurs_monthly", "is_automatic", "is_adhoc", "sort_order"):
            v = int(v)
        vals.append(v)
    if not fields:
        return jsonify({"error": "no fields"}), 400
    vals.append(tid)
    c = get_user_db()
    c.execute(f"UPDATE transactions SET {','.join(fields)} WHERE id=?", vals)
    c.commit()
    return jsonify(D(c.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()))


@app.route("/api/transactions/all")
@require_auth
def list_all_txns():
    """Return every transaction across all months, ordered by date."""
    c = get_user_db()
    rows = c.execute(
        "SELECT id,month,date,payee,category,amount,entry_type,status,"
        "recurs_monthly,is_automatic,is_adhoc,notes,sort_order "
        "FROM transactions ORDER BY date,id"
    ).fetchall()
    c.close()
    return jsonify([D(r) for r in rows])


@app.route("/api/transactions", methods=["POST"])
@require_auth
def add_txn_any():
    """Create a transaction, deriving month from the full YYYY-MM-DD date field."""
    d = request.get_json()
    date = (d.get("date") or "").strip()
    month = date[:7] if len(date) >= 7 else ""
    if not month:
        return jsonify({"error": "date (YYYY-MM-DD) is required"}), 400
    c = get_user_db()
    c.execute("INSERT OR IGNORE INTO months(month) VALUES(?)", (month,))
    cur = c.execute(
        "INSERT INTO transactions(month,date,payee,category,amount,entry_type,"
        "status,recurs_monthly,is_automatic,is_adhoc,notes,sort_order) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (month, date, d.get("payee", ""), d.get("category", ""),
         float(d.get("amount", 0)), d.get("entry_type", "debit"), d.get("status", "estimated"),
         int(d.get("recurs_monthly", 0)), int(d.get("is_automatic", 0)),
         int(d.get("is_adhoc", 0)), d.get("notes"), int(d.get("sort_order", 0))))
    new_id = cur.lastrowid
    c.commit()
    return jsonify(D(c.execute("SELECT * FROM transactions WHERE id=?", (new_id,)).fetchone())), 201


@app.route("/api/transactions/<int:tid>", methods=["DELETE"])
@require_auth
def del_txn(tid):
    c = get_user_db()
    c.execute("DELETE FROM transactions WHERE id=?", (tid,))
    c.commit()
    c.close()
    return jsonify({"deleted": tid})


@app.route("/api/transactions/<int:tid>/to-template", methods=["POST"])
@require_auth
def push_to_template(tid):
    c   = get_user_db()
    txn = c.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()
    if not txn:
        c.close()
        return jsonify({"error": "not found"}), 404
    peers = c.execute(
        "SELECT id FROM transactions WHERE month=? AND payee=? AND entry_type=? "
        "AND is_adhoc=0 ORDER BY COALESCE(date,'9999'), id",
        (txn["month"], txn["payee"], txn["entry_type"])).fetchall()
    order_num   = next((i + 1 for i, r in enumerate(peers) if r["id"] == tid), 1)
    tmpl_peers  = c.execute(
        "SELECT * FROM templates WHERE payee=? AND entry_type=? ORDER BY sort_order,id",
        (txn["payee"], txn["entry_type"])).fetchall()
    day = None
    if txn["date"]:
        try:
            day = int(txn["date"].split("-")[2])
        except Exception:
            pass
    if order_num - 1 < len(tmpl_peers):
        tmpl = tmpl_peers[order_num - 1]
        c.execute(
            "UPDATE templates SET category=?,amount=?,is_automatic=?,notes=?,day_of_month=? WHERE id=?",
            (txn["category"], txn["amount"], txn["is_automatic"], txn["notes"], day, tmpl["id"]))
        rid = tmpl["id"]
    else:
        cur = c.execute(
            "INSERT INTO templates(payee,category,entry_type,amount,day_of_month,is_automatic,notes,sort_order)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (txn["payee"], txn["category"], txn["entry_type"], txn["amount"], day,
             txn["is_automatic"], txn["notes"], order_num * 10))
        rid = cur.lastrowid
    c.commit()
    result = D(c.execute("SELECT * FROM templates WHERE id=?", (rid,)).fetchone())
    c.close()
    return jsonify(result)


@app.route("/api/months/<month>/init", methods=["POST"])
@require_auth
def init_month(month):
    d    = request.get_json() or {}
    mode = d.get("mode", "replace_all")
    c    = get_user_db()
    c.execute("INSERT OR IGNORE INTO months(month) VALUES(?)", (month,))
    tmpls    = c.execute("SELECT * FROM templates ORDER BY entry_type DESC,sort_order,id").fetchall()
    year, mo = int(month[:4]), int(month[5:])
    last_day = calendar.monthrange(year, mo)[1]

    def txn_date(tmpl):
        dv = tmpl["day_of_month"]
        return f"{year:04d}-{mo:02d}-{min(int(dv), last_day):02d}" if dv else None

    if mode == "replace_all":
        c.execute("DELETE FROM transactions WHERE month=? AND is_adhoc=0", (month,))
        for i, tmpl in enumerate(tmpls):
            c.execute(
                "INSERT INTO transactions(month,date,payee,category,amount,entry_type,"
                "status,recurs_monthly,is_automatic,is_adhoc,notes,sort_order)"
                " VALUES(?,?,?,?,?,?,'estimated',1,?,0,?,?)",
                (month, txn_date(tmpl), tmpl["payee"], tmpl["category"], float(tmpl["amount"]),
                 tmpl["entry_type"], int(tmpl["is_automatic"]), tmpl["notes"], i))
    else:
        groups = defaultdict(list)
        for t in tmpls:
            groups[(t["payee"], t["entry_type"])].append(t)
        for (payee, etype), grp in groups.items():
            existing = c.execute(
                "SELECT * FROM transactions WHERE month=? AND payee=? AND entry_type=? "
                "AND is_adhoc=0 ORDER BY COALESCE(date,'9999'),id",
                (month, payee, etype)).fetchall()
            for i, tmpl in enumerate(grp):
                td = txn_date(tmpl)
                if i < len(existing):
                    c.execute(
                        "UPDATE transactions SET category=?,amount=?,is_automatic=?,"
                        "notes=?,recurs_monthly=1,sort_order=? WHERE id=?",
                        (tmpl["category"], float(tmpl["amount"]), int(tmpl["is_automatic"]),
                         tmpl["notes"], i, existing[i]["id"]))
                    if td and not existing[i]["date"]:
                        c.execute("UPDATE transactions SET date=? WHERE id=?", (td, existing[i]["id"]))
                else:
                    c.execute(
                        "INSERT INTO transactions(month,date,payee,category,amount,entry_type,"
                        "status,recurs_monthly,is_automatic,is_adhoc,notes,sort_order)"
                        " VALUES(?,?,?,?,?,?,'estimated',1,?,0,?,?)",
                        (month, td, payee, tmpl["category"], float(tmpl["amount"]), etype,
                         int(tmpl["is_automatic"]), tmpl["notes"], i))
    c.commit()
    n = c.execute("SELECT COUNT(*) n FROM transactions WHERE month=?", (month,)).fetchone()["n"]
    c.close()
    return jsonify({"count": n, "month": month, "mode": mode})


@app.route("/api/months/<month>/daily-balances")
@require_auth
def daily_balances(month):
    c = get_user_db()
    bf_est, bf_act, _ = compute_bf_for_month(c, month)
    rows = c.execute(
        "SELECT date,amount,entry_type,status FROM transactions "
        "WHERE month=? AND date IS NOT NULL ORDER BY date,id", (month,)
    ).fetchall()
    c.close()
    year, mo = int(month[:4]), int(month[5:])
    last  = calendar.monthrange(year, mo)[1]
    today = date.today().isoformat()
    all_d, act_d = defaultdict(float), defaultdict(float)
    for r in rows:
        s = signed(r["entry_type"], r["amount"])
        all_d[r["date"]] += s
        if r["status"] in ("actual", "reconciled"):
            act_d[r["date"]] += s
    result  = []
    bal_all = bf_est
    bal_act = bf_act
    for day in range(1, last + 1):
        ds      = f"{year:04d}-{mo:02d}-{day:02d}"
        bal_all = round(bal_all + all_d.get(ds, 0), 2)
        bal_act = round(bal_act + act_d.get(ds, 0), 2)
        result.append({"date": ds, "estimated": bal_all, "actual": bal_act if ds <= today else None})
    return jsonify(result)


@app.route("/api/months/<month>/sync-templates", methods=["POST"])
@require_auth
def sync_templates(month):
    c    = get_user_db()
    rows = c.execute(
        "SELECT * FROM transactions WHERE month=? AND recurs_monthly=1 AND is_adhoc=0 "
        "ORDER BY entry_type DESC, COALESCE(date,'9999'), id", (month,)
    ).fetchall()
    updated = 0
    groups  = defaultdict(list)
    for r in rows:
        groups[(r["payee"], r["entry_type"])].append(r)
    for (payee, etype), grp in groups.items():
        tmpl_peers = c.execute(
            "SELECT * FROM templates WHERE payee=? AND entry_type=? ORDER BY sort_order,id",
            (payee, etype)).fetchall()
        for i, txn in enumerate(grp):
            day = None
            if txn["date"]:
                try:
                    day = int(txn["date"].split("-")[2])
                except Exception:
                    pass
            if i < len(tmpl_peers):
                c.execute(
                    "UPDATE templates SET category=?,amount=?,is_automatic=?,notes=?,day_of_month=? WHERE id=?",
                    (txn["category"], txn["amount"], txn["is_automatic"], txn["notes"], day, tmpl_peers[i]["id"]))
            else:
                c.execute(
                    "INSERT INTO templates(payee,category,entry_type,amount,day_of_month,"
                    "is_automatic,notes,sort_order) VALUES(?,?,?,?,?,?,?,?)",
                    (payee, txn["category"], etype, txn["amount"], day,
                     txn["is_automatic"], txn["notes"], (i + 1) * 10))
            updated += 1
    c.commit()
    c.close()
    return jsonify({"synced": updated})


# ──────────────────────────── Template API ────────────────────────────────────

@app.route("/api/templates")
@require_auth
def list_templates():
    c    = get_user_db()
    rows = c.execute("SELECT * FROM templates ORDER BY entry_type DESC,sort_order,id").fetchall()
    c.close()
    return jsonify([D(r) for r in rows])


@app.route("/api/templates", methods=["POST"])
@require_auth
def add_template():
    d   = request.get_json()
    c   = get_user_db()
    cur = c.execute(
        "INSERT INTO templates(payee,category,entry_type,amount,day_of_month,"
        "is_automatic,notes,sort_order) VALUES(?,?,?,?,?,?,?,?)",
        (d.get("payee", ""), d.get("category", ""), d.get("entry_type", "debit"),
         float(d.get("amount", 0)), d.get("day_of_month"), int(d.get("is_automatic", 0)),
         d.get("notes"), int(d.get("sort_order", 0))))
    new_id = cur.lastrowid
    c.commit()
    return jsonify(D(c.execute("SELECT * FROM templates WHERE id=?", (new_id,)).fetchone())), 201


@app.route("/api/templates/<int:tid>", methods=["PUT"])
@require_auth
def update_template(tid):
    d = request.get_json()
    fields, vals = [], []
    for f in ["payee", "category", "entry_type", "amount", "day_of_month",
              "is_automatic", "notes", "sort_order"]:
        if f not in d:
            continue
        fields.append(f"{f}=?")
        v = d[f]
        if f == "amount":
            v = float(v) if v is not None else 0
        elif f in ("is_automatic", "sort_order"):
            v = int(v) if v is not None else 0
        elif f == "day_of_month":
            v = int(v) if v else None
        vals.append(v)
    if not fields:
        return jsonify({"error": "no fields"}), 400
    vals.append(tid)
    c = get_user_db()
    c.execute(f"UPDATE templates SET {','.join(fields)} WHERE id=?", vals)
    c.commit()
    return jsonify(D(c.execute("SELECT * FROM templates WHERE id=?", (tid,)).fetchone()))


@app.route("/api/templates/<int:tid>", methods=["DELETE"])
@require_auth
def del_template(tid):
    c = get_user_db()
    c.execute("DELETE FROM templates WHERE id=?", (tid,))
    c.commit()
    c.close()
    return jsonify({"deleted": tid})


# ──────────────────────────── Autocomplete API ───────────────────────────────

@app.route("/api/categories")
@require_auth
def list_categories():
    c = get_user_db()
    rows = c.execute("""SELECT DISTINCT category FROM (
        SELECT category FROM transactions WHERE category!=''
        UNION SELECT category FROM templates WHERE category!='') ORDER BY category""").fetchall()
    c.close()
    return jsonify([r["category"] for r in rows])


@app.route("/api/payees")
@require_auth
def list_payees():
    c = get_user_db()
    rows = c.execute("""SELECT DISTINCT payee FROM (
        SELECT payee FROM transactions WHERE payee!=''
        UNION SELECT payee FROM templates WHERE payee!='') ORDER BY payee""").fetchall()
    c.close()
    return jsonify([r["payee"] for r in rows])


@app.route("/api/payee-defaults")
@require_auth
def payee_defaults():
    c = get_user_db()
    rows = c.execute(
        "SELECT payee, category FROM transactions "
        "WHERE payee!='' AND category!='' ORDER BY month DESC, created_at DESC"
    ).fetchall()
    c.close()
    defaults = {}
    for r in rows:
        if r["payee"] not in defaults:
            defaults[r["payee"]] = r["category"]
    return jsonify(defaults)


# ──────────────────────────── Frontend ───────────────────────────────────────

@app.route("/")
def index():
    token   = request.cookies.get("ft_token")
    payload = decode_token(token) if token else None
    if not payload:
        return redirect(url_for("login_page"))
    return render_template("index.html",
                           current_user=payload["username"],
                           is_admin=payload["is_admin"])


# ──────────────────────────── Startup helpers ─────────────────────────────────

def init_users(data_dir: str) -> None:
    """Bootstrap the user DB on startup.

    Always ensures the schema exists.  Creates the admin user only when there
    are no users at all — handles both a completely missing users.db AND a
    users.db that was created but left empty (e.g. after a mid-init crash).

    If an old tracker.db exists at data_dir root it is copied into the new
    admin's UUID directory so existing data is not lost.
    """
    uc = open_users_db(data_dir)
    ensure_users_schema(uc)
    existing = list_users(uc)
    if existing:
        uc.close()
        return  # Normal subsequent startup — nothing to do

    # No users found — create the admin account
    admin_user = os.environ.get("ADMIN_USER", "admin")
    admin_pass = os.environ.get("ADMIN_PASSWORD", "")
    generated  = False
    if not admin_pass:
        admin_pass = generate_random_password()
        generated  = True

    admin = create_user(uc, admin_user, admin_pass, is_admin=True)
    uc.close()

    admin_dir = user_data_dir(data_dir, admin["dir_name"])
    os.makedirs(admin_dir, exist_ok=True)

    # Migrate any existing tracker.db at the data root
    old_db = os.path.join(data_dir, "tracker.db")
    new_db = user_db_path(data_dir, admin["dir_name"])
    if os.path.exists(old_db):
        shutil.copy2(old_db, new_db)
        print(f"  ✓  Migrated existing tracker.db → {admin['dir_name']}/tracker.db")

    print("")
    print("  ┌─ First-time setup ──────────────────────────────────────────")
    print(f"  │  Admin username : {admin_user}")
    if generated:
        print(f"  │  Admin password : {admin_pass}")
        print(f"  │                   ↑ SAVE THIS — it will not be shown again")
    else:
        print(f"  │  Admin password : (set via ADMIN_PASSWORD env var)")
    print(f"  │  Data directory : {data_dir}")
    print("  └─────────────────────────────────────────────────────────────")
    print("")


# ──────────────────────────── Entry point ────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Finance Tracker")
    parser.add_argument(
        "--reset-admin-password", action="store_true",
        help="Reset the first admin user's password (uses ADMIN_PASSWORD env var or generates random)")
    parser.add_argument(
        "--list-users", action="store_true",
        help="Print all users in users.db (diagnostic tool)")
    args = parser.parse_args()

    if args.list_users:
        users_path = os.path.join(DATA_DIR, "users.db")
        print(f"\n  users.db path : {users_path}")
        print(f"  exists        : {os.path.exists(users_path)}")
        if os.path.exists(users_path):
            uc    = open_users_db(DATA_DIR)
            users = list_users(uc)
            uc.close()
            print(f"  user count    : {len(users)}")
            for u in users:
                print(f"\n    id={u['id']}  username={u['username']}  "
                      f"is_admin={u['is_admin']}  dir={u['dir_name']}  "
                      f"created={u['created_at']}")
        print()
        sys.exit(0)

    if args.reset_admin_password:
        os.makedirs(DATA_DIR, exist_ok=True)
        uc = open_users_db(DATA_DIR)
        ensure_users_schema(uc)
        users = list_users(uc)
        if not users:
            # No users at all — run full init instead
            uc.close()
            print("  No users found — running first-time setup instead.")
            init_users(DATA_DIR)
            sys.exit(0)
        # Reset password for the first admin user (or first user if none are admin)
        admins = [u for u in users if u["is_admin"]]
        target = admins[0] if admins else users[0]
        new_pass  = os.environ.get("ADMIN_PASSWORD", "")
        generated = False
        if not new_pass:
            new_pass  = generate_random_password()
            generated = True
        update_password(uc, target["id"], new_pass)
        uc.close()
        print(f"\n  Password reset for user : {target['username']}")
        if generated:
            print(f"  New password           : {new_pass}")
            print(f"                           ↑ SAVE THIS")
        else:
            print(f"  New password           : (set via ADMIN_PASSWORD env var)")
        print()
        sys.exit(0)

    # Normal startup
    os.makedirs(DATA_DIR, exist_ok=True)
    init_secret(DATA_DIR)   # must come before any JWT operations
    init_users(DATA_DIR)

    print(f"\n  Finance Tracker v{APP_VERSION}  →  http://localhost:5757")
    print(f"  Data directory : {DATA_DIR}")
    print()
    app.run(host="0.0.0.0", port=5757, debug=True)
