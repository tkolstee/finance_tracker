"""CRUD tests for transactions, templates, accounts, and month operations."""
import json
import pytest
from tests.helpers import post_json, create_account, create_txn, create_transfer

MONTH = "2099-04"


def put_json(client, url, body):
    return client.put(url, data=json.dumps(body), content_type="application/json")


def make_txn(client, payee, amount=100, entry_type="debit", status="estimated",
             month=MONTH, acct_id=None):
    if acct_id is None:
        acct_id = create_account(client, f"Acct-{payee}")["id"]
    return create_txn(client, month, date=f"{month}-05", payee=payee, category="X",
                      amount=amount, entry_type=entry_type, status=status,
                      account_id=acct_id, recurs_monthly=0, is_automatic=0,
                      is_adhoc=0, sort_order=0)


def make_template(client, payee, account_id, entry_type="debit", amount=100,
                  transfer_account_id=None):
    body = {"payee": payee, "category": "X", "entry_type": entry_type,
            "amount": amount, "day_of_month": 5, "is_automatic": 0,
            "notes": "", "sort_order": 0, "account_id": account_id}
    if transfer_account_id is not None:
        body["transfer_account_id"] = transfer_account_id
    return post_json(client, "/api/templates", body).get_json()


# ── transaction update ────────────────────────────────────────────────────────

def test_update_txn_amount(client):
    txn = make_txn(client, "Cable")
    r = put_json(client, f"/api/transactions/{txn['id']}", {"amount": 75})
    assert r.status_code == 200
    assert r.get_json()["amount"] == 75


def test_update_txn_status(client):
    txn = make_txn(client, "Power")
    r = put_json(client, f"/api/transactions/{txn['id']}", {"status": "actual"})
    assert r.get_json()["status"] == "actual"


def test_update_txn_not_found(client):
    r = put_json(client, "/api/transactions/99999", {"amount": 1})
    assert r.status_code == 404


def test_update_txn_syncs_transfer_pair(client):
    a1 = create_account(client, "Src-upd")["id"]
    a2 = create_account(client, "Dst-upd")["id"]
    txn = create_transfer(client, MONTH, date=f"{MONTH}-10",
                          amount=200, from_account=a1, to_account=a2)
    src_id = txn["id"]

    put_json(client, f"/api/transactions/{src_id}", {"amount": 350, "status": "actual"})

    all_txns = client.get(f"/api/months/{MONTH}/transactions").get_json()
    transfer_txns = [t for t in all_txns if t.get("transfer_group_id") == txn["transfer_group_id"]]
    assert len(transfer_txns) == 2
    assert all(t["amount"] == 350 for t in transfer_txns)
    assert all(t["status"] == "actual" for t in transfer_txns)


def test_update_txn_convert_plain_to_transfer(client):
    a1 = create_account(client, "PlainSrc")["id"]
    a2 = create_account(client, "PlainDst")["id"]
    txn = make_txn(client, "ToConvert", acct_id=a1)
    assert txn["transfer_group_id"] is None

    r = put_json(client, f"/api/transactions/{txn['id']}", {"transfer_account_id": a2})
    assert r.status_code == 200
    assert r.get_json()["transfer_group_id"] is not None

    all_txns = client.get(f"/api/months/{MONTH}/transactions").get_json()
    tgid = r.get_json()["transfer_group_id"]
    pair = [t for t in all_txns if t.get("transfer_group_id") == tgid]
    assert len(pair) == 2


def test_update_txn_convert_transfer_to_plain(client):
    a1 = create_account(client, "XferSrc2")["id"]
    a2 = create_account(client, "XferDst2")["id"]
    txn = create_transfer(client, MONTH, date=f"{MONTH}-10",
                          amount=100, from_account=a1, to_account=a2)
    src_id = txn["id"]

    r = put_json(client, f"/api/transactions/{src_id}", {"transfer_account_id": None})
    assert r.status_code == 200
    updated = r.get_json()
    assert updated["transfer_group_id"] is None

    # Paired leg should be gone
    all_txns = client.get(f"/api/months/{MONTH}/transactions").get_json()
    remaining = [t for t in all_txns if t["id"] == src_id or t["account_id"] == a2]
    assert all(t["id"] == src_id for t in remaining)


# ── transaction delete ────────────────────────────────────────────────────────

def test_delete_txn(client):
    txn = make_txn(client, "ToDelete")
    tid = txn["id"]
    r = client.delete(f"/api/transactions/{tid}")
    assert r.status_code == 200
    assert r.get_json()["deleted"] == tid

    txns = client.get(f"/api/months/{MONTH}/transactions").get_json()
    assert not any(t["id"] == tid for t in txns)


def test_delete_txn_removes_both_transfer_legs(client):
    a1 = create_account(client, "DelSrc")["id"]
    a2 = create_account(client, "DelDst")["id"]
    txn = create_transfer(client, MONTH, date=f"{MONTH}-10",
                          amount=100, from_account=a1, to_account=a2)
    tgid = txn["transfer_group_id"]

    client.delete(f"/api/transactions/{txn['id']}")

    txns = client.get(f"/api/months/{MONTH}/transactions").get_json()
    assert not any(t.get("transfer_group_id") == tgid for t in txns)


def test_delete_nonexistent_txn_returns_ok(client):
    r = client.delete("/api/transactions/99999")
    assert r.status_code == 200


# ── list all transactions ─────────────────────────────────────────────────────

def test_list_all_txns_across_months(client):
    a = create_account(client, "AllAcct")["id"]
    create_txn(client, "2099-04", date="2099-04-01", payee="Apr", category="X",
               amount=10, entry_type="debit", status="estimated", account_id=a,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    create_txn(client, "2099-05", date="2099-05-01", payee="May", category="X",
               amount=20, entry_type="debit", status="estimated", account_id=a,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)

    r = client.get("/api/transactions/all")
    assert r.status_code == 200
    payees = [t["payee"] for t in r.get_json()]
    assert "Apr" in payees
    assert "May" in payees


def test_list_all_txns_account_filter(client):
    a1 = create_account(client, "AllA1")["id"]
    a2 = create_account(client, "AllA2")["id"]
    create_txn(client, "2099-04", date="2099-04-01", payee="InA1", category="X",
               amount=10, entry_type="debit", status="estimated", account_id=a1,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    create_txn(client, "2099-04", date="2099-04-02", payee="InA2", category="X",
               amount=20, entry_type="debit", status="estimated", account_id=a2,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)

    r = client.get(f"/api/transactions/all?account_ids={a1}")
    payees = [t["payee"] for t in r.get_json()]
    assert "InA1" in payees
    assert "InA2" not in payees


# ── template CRUD ─────────────────────────────────────────────────────────────

def test_update_template(client):
    acct = create_account(client, "TmplUpd")["id"]
    tmpl = make_template(client, "Netflix", acct)
    r = put_json(client, f"/api/templates/{tmpl['id']}", {"amount": 19.99})
    assert r.status_code == 200
    assert r.get_json()["amount"] == 19.99


def test_update_template_no_fields_returns_400(client):
    acct = create_account(client, "TmplNoField")["id"]
    tmpl = make_template(client, "Noop", acct)
    r = put_json(client, f"/api/templates/{tmpl['id']}", {})
    assert r.status_code == 400


def test_delete_template(client):
    acct = create_account(client, "TmplDel")["id"]
    tmpl = make_template(client, "ToDelete", acct)
    tid = tmpl["id"]

    r = client.delete(f"/api/templates/{tid}")
    assert r.status_code == 200
    assert r.get_json()["deleted"] == tid

    templates = client.get("/api/templates").get_json()
    assert not any(t["id"] == tid for t in templates)


# ── push transaction to template ──────────────────────────────────────────────

def test_push_to_template_creates_new_template(client):
    acct = create_account(client, "PushSrc")["id"]
    txn = make_txn(client, "Spotify", amount=12, acct_id=acct)

    r = post_json(client, f"/api/transactions/{txn['id']}/to-template", {})
    assert r.status_code == 200
    tmpl = r.get_json()
    assert tmpl["payee"] == "Spotify"
    assert tmpl["amount"] == 12


def test_push_to_template_updates_existing(client):
    acct = create_account(client, "PushUpd")["id"]
    existing = make_template(client, "Hulu", acct, amount=5)
    txn = make_txn(client, "Hulu", amount=18, acct_id=acct)

    r = post_json(client, f"/api/transactions/{txn['id']}/to-template", {})
    assert r.get_json()["id"] == existing["id"]
    assert r.get_json()["amount"] == 18


def test_push_to_template_not_found(client):
    r = post_json(client, "/api/transactions/99999/to-template", {})
    assert r.status_code == 404


# ── month operations ──────────────────────────────────────────────────────────

def test_months_list_reflects_created_transactions(client):
    a = create_account(client, "MthList")["id"]
    create_txn(client, "2099-06", date="2099-06-01", payee="X", category="X",
               amount=1, entry_type="debit", status="estimated", account_id=a,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    r = client.get("/api/months/list")
    assert r.status_code == 200
    data = r.get_json()
    assert "2099-06" in data
    assert data["2099-06"] == 1


def test_get_month_is_first_when_no_transactions(client):
    r = client.get("/api/months/2099-07")
    assert r.status_code == 200
    assert r.get_json()["is_first_month"] is True


def test_get_month_not_first_after_earlier_month(client):
    a = create_account(client, "GetMth")["id"]
    create_txn(client, "2099-01", date="2099-01-01", payee="First", category="X",
               amount=1, entry_type="debit", status="estimated", account_id=a,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    r = client.get("/api/months/2099-02")
    assert r.get_json()["is_first_month"] is False


def test_update_month_bf(client):
    r = put_json(client, f"/api/months/{MONTH}/bf",
                 {"bf_estimated": 1000, "bf_actual": 900, "bf_reconciled": 800})
    assert r.status_code == 200
    data = r.get_json()
    assert data["bf_estimated"] == 1000
    assert data["bf_actual"] == 900


# ── month balances ────────────────────────────────────────────────────────────

def test_month_balances_empty(client):
    r = client.get("/api/months/2099-08/balances")
    assert r.status_code == 200
    data = r.get_json()
    assert data["estimated"] == 0
    assert data["actual"] == 0


def test_month_balances_reflect_transactions(client):
    a = create_account(client, "BalAcct")["id"]
    create_txn(client, MONTH, date=f"{MONTH}-01", payee="Pay",
               category="Income", amount=500, entry_type="credit",
               status="actual", account_id=a,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    r = client.get(f"/api/months/{MONTH}/balances")
    data = r.get_json()
    assert data["actual"] == 500


def test_month_balances_bf_flows_into_balance(client):
    put_json(client, f"/api/months/2099-09/bf", {"bf_estimated": 500})
    r = client.get("/api/months/2099-09/balances")
    assert r.get_json()["estimated"] == 500


# ── global balances ───────────────────────────────────────────────────────────

def test_global_balances_returns_keys(client):
    r = client.get("/api/balances/global")
    assert r.status_code == 200
    data = r.get_json()
    assert "estimated" in data
    assert "actual" in data
    assert "reconciled" in data


def test_global_balances_account_filter(client):
    a1 = create_account(client, "GlobA1")["id"]
    a2 = create_account(client, "GlobA2")["id"]
    # Past date so it counts toward global balance
    create_txn(client, "2020-01", date="2020-01-15", payee="OldCredit",
               category="X", amount=1000, entry_type="credit",
               status="actual", account_id=a1,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    create_txn(client, "2020-01", date="2020-01-15", payee="OtherCredit",
               category="X", amount=500, entry_type="credit",
               status="actual", account_id=a2,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    r = client.get(f"/api/balances/global?account_ids={a1}")
    data = r.get_json()
    assert data["actual"] == 1000


# ── daily balances ────────────────────────────────────────────────────────────

def test_daily_balances_returns_one_entry_per_day(client):
    r = client.get(f"/api/months/{MONTH}/daily-balances")
    assert r.status_code == 200
    data = r.get_json()
    # April has 30 days
    assert len(data) == 30
    assert data[0]["date"] == f"{MONTH}-01"
    assert data[-1]["date"] == f"{MONTH}-30"


def test_daily_balances_accumulates_transactions(client):
    a = create_account(client, "DailyAcct")["id"]
    create_txn(client, MONTH, date=f"{MONTH}-10", payee="Credit",
               category="X", amount=200, entry_type="credit",
               status="estimated", account_id=a,
               recurs_monthly=0, is_automatic=0, is_adhoc=0, sort_order=0)
    r = client.get(f"/api/months/{MONTH}/daily-balances")
    data = r.get_json()
    day10 = next(d for d in data if d["date"] == f"{MONTH}-10")
    day11 = next(d for d in data if d["date"] == f"{MONTH}-11")
    assert day10["estimated"] == 200
    assert day11["estimated"] == 200  # balance carries forward


# ── month init ────────────────────────────────────────────────────────────────

def test_init_month_creates_transactions_from_templates(client):
    acct = create_account(client, "InitAcct")["id"]
    make_template(client, "Mortgage", acct, amount=1500)

    r = post_json(client, f"/api/months/{MONTH}/init", {"mode": "replace_all"})
    assert r.status_code == 200
    assert r.get_json()["count"] >= 1

    txns = client.get(f"/api/months/{MONTH}/transactions").get_json()
    assert any(t["payee"] == "Mortgage" for t in txns)


def test_init_month_replace_all_clears_existing_non_adhoc(client):
    acct = create_account(client, "InitRepl")["id"]
    make_template(client, "Gym", acct, amount=50)
    # First init
    post_json(client, f"/api/months/{MONTH}/init", {"mode": "replace_all"})
    # Second init should not double up
    post_json(client, f"/api/months/{MONTH}/init", {"mode": "replace_all"})

    txns = client.get(f"/api/months/{MONTH}/transactions").get_json()
    gym_txns = [t for t in txns if t["payee"] == "Gym"]
    assert len(gym_txns) == 1


# ── sync templates ────────────────────────────────────────────────────────────

def test_sync_templates_updates_matching_template(client):
    acct = create_account(client, "SyncAcct")["id"]
    make_template(client, "Electric", acct, amount=80)
    # Must be recurs_monthly=1 to be picked up by sync
    create_txn(client, MONTH, date=f"{MONTH}-05", payee="Electric", category="X",
               amount=95, entry_type="debit", status="estimated", account_id=acct,
               recurs_monthly=1, is_automatic=0, is_adhoc=0, sort_order=0)

    r = post_json(client, f"/api/months/{MONTH}/sync-templates", {})
    assert r.status_code == 200
    assert r.get_json()["synced"] >= 1

    updated = client.get("/api/templates").get_json()
    elec = next(t for t in updated if t["payee"] == "Electric")
    assert elec["amount"] == 95


def test_sync_templates_creates_new_template_for_recurring_txn(client):
    acct = create_account(client, "SyncNew")["id"]
    create_txn(client, MONTH, date=f"{MONTH}-05", payee="NewRecurring", category="X",
               amount=42, entry_type="debit", status="estimated", account_id=acct,
               recurs_monthly=1, is_automatic=0, is_adhoc=0, sort_order=0)

    r = post_json(client, f"/api/months/{MONTH}/sync-templates", {})
    assert r.get_json()["synced"] >= 1

    templates = client.get("/api/templates").get_json()
    assert any(t["payee"] == "NewRecurring" for t in templates)


def test_sync_templates_ignores_non_recurring(client):
    acct = create_account(client, "SyncNonRec")["id"]
    make_txn(client, "OneOff", amount=42, acct_id=acct)  # recurs_monthly=0

    r = post_json(client, f"/api/months/{MONTH}/sync-templates", {})
    assert r.get_json()["synced"] == 0


# ── account CRUD ──────────────────────────────────────────────────────────────

def test_list_accounts(client):
    r = client.get("/api/accounts")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)
    assert len(r.get_json()) >= 1  # default "Checking" account always exists


def test_update_account_name(client):
    acct = create_account(client, "OldName")["id"]
    r = put_json(client, f"/api/accounts/{acct}", {"name": "NewName"})
    assert r.status_code == 200
    assert r.get_json()["name"] == "NewName"


def test_update_account_no_fields_returns_400(client):
    acct = create_account(client, "NoFieldAcct")["id"]
    r = put_json(client, f"/api/accounts/{acct}", {})
    assert r.status_code == 400


def test_delete_account(client):
    acct = create_account(client, "DeleteMe")["id"]
    r = client.delete(f"/api/accounts/{acct}")
    assert r.status_code == 200
    assert r.get_json()["deleted"] == acct


def test_delete_default_account_rejected(client):
    # The default account (id=1, "Checking") cannot be deleted
    accounts = client.get("/api/accounts").get_json()
    default_id = accounts[0]["id"]
    r = client.delete(f"/api/accounts/{default_id}")
    assert r.status_code == 400


def test_delete_account_in_use_rejected(client):
    acct = create_account(client, "InUse")["id"]
    make_txn(client, "UsesAcct", acct_id=acct)
    r = client.delete(f"/api/accounts/{acct}")
    assert r.status_code == 400


# ── app meta ──────────────────────────────────────────────────────────────────

def test_app_meta_returns_version_and_username(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    data = r.get_json()
    assert "app_version" in data
    assert data["username"] == "testuser"
