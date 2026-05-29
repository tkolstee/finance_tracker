"""Shared helper functions for finance_tracker tests."""
import json


def post_json(client, url, body):
    return client.post(
        url,
        data=json.dumps(body),
        content_type="application/json",
    )


def create_account(client, name, kind="checking"):
    r = post_json(client, "/api/accounts", {"name": name, "type": kind})
    return r.get_json()


def create_txn(client, month, **kwargs):
    r = post_json(client, f"/api/months/{month}/transactions", kwargs)
    return r.get_json()


def create_transfer(client, month, *, date, amount, from_account, to_account,
                    status="estimated"):
    """Create a transfer pair. Returns the source transaction."""
    body = {
        "date": date,
        "payee": "Transfer",
        "category": "Transfer",
        "amount": amount,
        "entry_type": "debit",
        "status": status,
        "is_adhoc": 0,
        "recurs_monthly": 0,
        "is_automatic": 0,
        "notes": "",
        "sort_order": 0,
        "account_id": from_account,
        "transfer_account_id": to_account,
    }
    r = post_json(client, f"/api/months/{month}/transactions", body)
    return r.get_json()
