"""Integration tests for the modified/new API endpoints.

Covers:
  - Auth (login / logout / protected routes)
  - GET /api/months/<month>/transactions  (account_ids filter + collapse)
  - GET /api/months/<month>/totals        (income/expense/transfer/net)
  - GET /api/templates                    (account_ids filter)
"""
import json
import pytest
from tests.helpers import post_json, create_account, create_txn, create_transfer


MONTH = "2099-01"


# ── auth ─────────────────────────────────────────────────────────────────────

def test_login_succeeds(client):
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.get_json()["username"] == "testuser"


def test_unauthenticated_request_returns_401(tmp_path):
    import finance_tracker as ft
    from unittest.mock import patch
    ft.app.config["TESTING"] = True
    with patch.object(ft, "DATA_DIR", str(tmp_path)):
        with ft.app.test_client() as c:
            r = c.get("/api/accounts")
            assert r.status_code == 401


def test_logout_clears_session(client):
    client.post("/api/logout")
    r = client.get("/api/me")
    assert r.status_code == 401


# ── transaction filtering ─────────────────────────────────────────────────────

def test_transactions_returns_all_when_no_filter(client):
    acct = create_account(client, "Test Checking")["id"]
    create_txn(client, MONTH, date=f"{MONTH}-05", payee="Groceries",
               category="Food", amount=50, entry_type="debit",
               status="estimated", account_id=acct,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    r = client.get(f"/api/months/{MONTH}/transactions")
    txns = r.get_json()
    assert r.status_code == 200
    assert any(t["payee"] == "Groceries" for t in txns)


def test_transactions_filtered_by_account_id(client):
    a1 = create_account(client, "Checking2")["id"]
    a2 = create_account(client, "Savings2")["id"]
    create_txn(client, MONTH, date=f"{MONTH}-05", payee="In Checking",
               category="X", amount=10, entry_type="debit", status="estimated",
               account_id=a1, recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    create_txn(client, MONTH, date=f"{MONTH}-06", payee="In Savings",
               category="X", amount=20, entry_type="credit", status="estimated",
               account_id=a2, recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)

    r = client.get(f"/api/months/{MONTH}/transactions?account_ids={a1}")
    txns = r.get_json()
    payees = [t["payee"] for t in txns]
    assert "In Checking" in payees
    assert "In Savings" not in payees


def test_transactions_collapse_returns_one_row_per_transfer(client):
    a1 = create_account(client, "From")["id"]
    a2 = create_account(client, "To")["id"]
    create_transfer(client, MONTH, date=f"{MONTH}-10",
                    amount=500, from_account=a1, to_account=a2)

    r = client.get(f"/api/months/{MONTH}/transactions?collapse=true")
    txns = r.get_json()
    transfer_txns = [t for t in txns if t.get("transfer_group_id")]
    assert len(transfer_txns) == 1


def test_transactions_no_collapse_returns_both_legs(client):
    a1 = create_account(client, "FromNC")["id"]
    a2 = create_account(client, "ToNC")["id"]
    create_transfer(client, MONTH, date=f"{MONTH}-10",
                    amount=300, from_account=a1, to_account=a2)

    r = client.get(f"/api/months/{MONTH}/transactions")
    txns = r.get_json()
    transfer_txns = [t for t in txns if t.get("transfer_group_id")]
    assert len(transfer_txns) == 2


def test_collapsed_transfer_has_display_payee(client):
    a1 = create_account(client, "Source Acct")["id"]
    a2 = create_account(client, "Dest Acct")["id"]
    create_transfer(client, MONTH, date=f"{MONTH}-15",
                    amount=100, from_account=a1, to_account=a2)

    r = client.get(f"/api/months/{MONTH}/transactions?collapse=true")
    transfer = next(t for t in r.get_json() if t.get("is_transfer_display"))
    assert transfer["display_payee"]  # non-empty


def test_collapsed_with_account_filter_picks_correct_leg(client):
    a1 = create_account(client, "Alpha")["id"]
    a2 = create_account(client, "Beta")["id"]
    create_transfer(client, MONTH, date=f"{MONTH}-20",
                    amount=75, from_account=a1, to_account=a2)

    # Filter to destination account — should return the destination leg
    r = client.get(f"/api/months/{MONTH}/transactions?collapse=true&account_ids={a2}")
    txns = r.get_json()
    transfer = next(t for t in txns if t.get("is_transfer_display"))
    assert transfer["account_id"] == a2


# ── /api/months/<month>/totals ────────────────────────────────────────────────

def test_totals_empty_month(client):
    r = client.get(f"/api/months/2099-02/totals")
    assert r.status_code == 200
    data = r.get_json()
    assert data["income_total"] == 0
    assert data["expense_total"] == 0
    assert data["net_est"] == 0


def test_totals_income_and_expense(client):
    acct = create_account(client, "Main")["id"]
    create_txn(client, MONTH, date=f"{MONTH}-01", payee="Salary",
               category="Income", amount=1000, entry_type="credit",
               status="actual", account_id=acct,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    create_txn(client, MONTH, date=f"{MONTH}-02", payee="Rent",
               category="Housing", amount=600, entry_type="debit",
               status="actual", account_id=acct,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)

    r = client.get(f"/api/months/{MONTH}/totals")
    data = r.get_json()
    assert data["income_total"] == 1000
    assert data["expense_total"] == 600
    assert data["net_est"] == 400


def test_totals_net_by_status(client):
    acct = create_account(client, "StatusAcct")["id"]
    create_txn(client, MONTH, date=f"{MONTH}-01", payee="EstIncome",
               category="X", amount=500, entry_type="credit",
               status="estimated", account_id=acct,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    create_txn(client, MONTH, date=f"{MONTH}-02", payee="ActIncome",
               category="X", amount=300, entry_type="credit",
               status="actual", account_id=acct,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    create_txn(client, MONTH, date=f"{MONTH}-03", payee="RecIncome",
               category="X", amount=200, entry_type="credit",
               status="reconciled", account_id=acct,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)

    r = client.get(f"/api/months/{MONTH}/totals")
    data = r.get_json()
    assert data["net_est"] == 1000   # all three
    assert data["net_act"] == 500    # actual + reconciled
    assert data["net_rec"] == 200    # reconciled only


def test_totals_transfer_separated_in_multi_account_mode(client):
    a1 = create_account(client, "TotFrom")["id"]
    a2 = create_account(client, "TotTo")["id"]
    # Regular income in a1
    create_txn(client, MONTH, date=f"{MONTH}-01", payee="Pay",
               category="Income", amount=800, entry_type="credit",
               status="estimated", account_id=a1,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    # Transfer a1 → a2
    create_transfer(client, MONTH, date=f"{MONTH}-05",
                    amount=200, from_account=a1, to_account=a2)

    r = client.get(f"/api/months/{MONTH}/totals?multi_account=true")
    data = r.get_json()
    assert data["income_total"] == 800    # transfer excluded from income
    assert data["transfer_total"] == 200  # transfer in its own bucket
    assert data["net_est"] == 800         # net excludes internal transfer


def test_totals_transfer_included_in_single_account_mode(client):
    a1 = create_account(client, "Single1")["id"]
    a2 = create_account(client, "Single2")["id"]
    create_txn(client, MONTH, date=f"{MONTH}-01", payee="Pay",
               category="Income", amount=800, entry_type="credit",
               status="estimated", account_id=a1,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    create_transfer(client, MONTH, date=f"{MONTH}-05",
                    amount=200, from_account=a1, to_account=a2)

    # Filter to a1 only (single account scope), multi_account=false
    r = client.get(f"/api/months/{MONTH}/totals?account_ids={a1}&multi_account=false")
    data = r.get_json()
    assert data["expense_total"] == 200   # transfer debit counts as expense
    assert data["transfer_total"] == 0    # not separated
    assert data["net_est"] == 600         # 800 income - 200 transfer debit


def test_totals_account_filter(client):
    a1 = create_account(client, "FilterA")["id"]
    a2 = create_account(client, "FilterB")["id"]
    create_txn(client, MONTH, date=f"{MONTH}-01", payee="InA",
               category="X", amount=400, entry_type="credit",
               status="estimated", account_id=a1,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    create_txn(client, MONTH, date=f"{MONTH}-02", payee="InB",
               category="X", amount=100, entry_type="credit",
               status="estimated", account_id=a2,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)

    r = client.get(f"/api/months/{MONTH}/totals?account_ids={a1}")
    data = r.get_json()
    assert data["income_total"] == 400   # only a1 counted


# ── /api/templates with account_ids ──────────────────────────────────────────

def test_templates_no_filter_returns_all(client):
    a1 = create_account(client, "TmplA")["id"]
    a2 = create_account(client, "TmplB")["id"]
    post_json(client, "/api/templates", {
        "payee": "Rent", "category": "Housing", "entry_type": "debit",
        "amount": 1200, "day_of_month": 1, "is_automatic": 0,
        "notes": "", "sort_order": 0, "account_id": a1,
    })
    post_json(client, "/api/templates", {
        "payee": "Electric", "category": "Utilities", "entry_type": "debit",
        "amount": 80, "day_of_month": 15, "is_automatic": 0,
        "notes": "", "sort_order": 0, "account_id": a2,
    })

    r = client.get("/api/templates")
    templates = r.get_json()
    payees = [t["payee"] for t in templates]
    assert "Rent" in payees
    assert "Electric" in payees


def test_templates_filtered_by_account_id(client):
    a1 = create_account(client, "TmplC")["id"]
    a2 = create_account(client, "TmplD")["id"]
    post_json(client, "/api/templates", {
        "payee": "InC", "category": "X", "entry_type": "debit",
        "amount": 50, "day_of_month": 1, "is_automatic": 0,
        "notes": "", "sort_order": 0, "account_id": a1,
    })
    post_json(client, "/api/templates", {
        "payee": "InD", "category": "X", "entry_type": "debit",
        "amount": 75, "day_of_month": 1, "is_automatic": 0,
        "notes": "", "sort_order": 0, "account_id": a2,
    })

    r = client.get(f"/api/templates?account_ids={a1}")
    templates = r.get_json()
    payees = [t["payee"] for t in templates]
    assert "InC" in payees
    assert "InD" not in payees


def test_templates_transfer_template_visible_to_either_account(client):
    a1 = create_account(client, "XferSrc")["id"]
    a2 = create_account(client, "XferDst")["id"]
    post_json(client, "/api/templates", {
        "payee": "Monthly Transfer", "category": "Transfer", "entry_type": "debit",
        "amount": 500, "day_of_month": 1, "is_automatic": 1,
        "notes": "", "sort_order": 0,
        "account_id": a1, "transfer_account_id": a2,
    })

    # Visible when filtering to source
    r1 = client.get(f"/api/templates?account_ids={a1}")
    assert any(t["payee"] == "Monthly Transfer" for t in r1.get_json())

    # Also visible when filtering to destination
    r2 = client.get(f"/api/templates?account_ids={a2}")
    assert any(t["payee"] == "Monthly Transfer" for t in r2.get_json())
