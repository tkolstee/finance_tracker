"""Unit tests for collapse_transfer_rows() — the core server-side collapse logic."""
import pytest
from finance_tracker import collapse_transfer_rows


def _txn(id, account_id, transfer_group_id=None, transfer_role="normal",
         transfer_account_id=None, entry_type="debit", amount=100,
         transfer_account_name=None, payee="Payee"):
    return {
        "id": id,
        "account_id": account_id,
        "transfer_group_id": transfer_group_id,
        "transfer_role": transfer_role,
        "transfer_account_id": transfer_account_id,
        "entry_type": entry_type,
        "amount": amount,
        "transfer_account_name": transfer_account_name,
        "payee": payee,
    }


# ── non-transfer rows ─────────────────────────────────────────────────────────

def test_non_transfer_rows_pass_through():
    rows = [_txn(1, 1), _txn(2, 2)]
    result = collapse_transfer_rows(rows)
    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[1]["id"] == 2


def test_empty_list():
    assert collapse_transfer_rows([]) == []


# ── transfer pair collapse ────────────────────────────────────────────────────

def _transfer_pair(gid="grp1", src_account=1, dst_account=2, amount=200):
    source = _txn(10, src_account, transfer_group_id=gid, transfer_role="source",
                  transfer_account_id=dst_account, entry_type="debit", amount=amount,
                  transfer_account_name="Savings")
    dest   = _txn(11, dst_account, transfer_group_id=gid, transfer_role="destination",
                  transfer_account_id=src_account, entry_type="credit", amount=amount,
                  transfer_account_name="Checking")
    return source, dest


def test_transfer_pair_collapsed_to_one_row():
    source, dest = _transfer_pair()
    result = collapse_transfer_rows([source, dest])
    assert len(result) == 1


def test_transfer_chooses_source_when_no_account_filter():
    source, dest = _transfer_pair()
    result = collapse_transfer_rows([source, dest])
    assert result[0]["id"] == source["id"]


def test_transfer_sets_display_payee():
    source, dest = _transfer_pair(src_account=1, dst_account=2)
    source["transfer_account_name"] = "Savings Account"
    result = collapse_transfer_rows([source, dest])
    assert result[0]["display_payee"] == "Savings Account"


def test_transfer_sets_is_transfer_display():
    source, dest = _transfer_pair()
    result = collapse_transfer_rows([source, dest])
    assert result[0]["is_transfer_display"] is True


def test_non_transfer_rows_not_marked_is_transfer_display():
    rows = [_txn(1, 1)]
    result = collapse_transfer_rows(rows)
    assert "is_transfer_display" not in result[0]


# ── account_ids selects the visible leg ───────────────────────────────────────

def test_account_filter_picks_matching_leg():
    source, dest = _transfer_pair(src_account=1, dst_account=2)
    # Only account 2 selected — should return the destination leg
    result = collapse_transfer_rows([source, dest], account_ids=[2])
    assert result[0]["id"] == dest["id"]


def test_account_filter_picks_source_when_source_account_selected():
    source, dest = _transfer_pair(src_account=1, dst_account=2)
    result = collapse_transfer_rows([source, dest], account_ids=[1])
    assert result[0]["id"] == source["id"]


def test_account_filter_both_selected_still_one_row():
    source, dest = _transfer_pair(src_account=1, dst_account=2)
    result = collapse_transfer_rows([source, dest], account_ids=[1, 2])
    assert len(result) == 1


def test_account_filter_none_means_no_filter():
    source, dest = _transfer_pair()
    result = collapse_transfer_rows([source, dest], account_ids=None)
    assert len(result) == 1
    assert result[0]["id"] == source["id"]


# ── mixed rows ────────────────────────────────────────────────────────────────

def test_mixed_transfer_and_plain_rows():
    plain   = _txn(1, 1)
    source, dest = _transfer_pair(gid="g1")
    result = collapse_transfer_rows([plain, source, dest])
    assert len(result) == 2
    ids = {r["id"] for r in result}
    assert 1 in ids
    assert source["id"] in ids
    assert dest["id"] not in ids


def test_multiple_transfer_groups():
    s1, d1 = _transfer_pair(gid="g1", src_account=1, dst_account=2)
    s2, d2 = _transfer_pair(gid="g2", src_account=3, dst_account=4)
    result = collapse_transfer_rows([s1, d1, s2, d2])
    assert len(result) == 2


# ── edge cases ────────────────────────────────────────────────────────────────

def test_orphan_transfer_leg_included():
    """A transfer row without its pair should still appear in results."""
    source = _txn(10, 1, transfer_group_id="orphan", transfer_role="source",
                  transfer_account_id=2)
    result = collapse_transfer_rows([source])
    assert len(result) == 1
    assert result[0]["id"] == 10


def test_display_payee_falls_back_to_payee_field():
    """When transfer_account_name is None, fall back to the payee field."""
    source, dest = _transfer_pair()
    source["transfer_account_name"] = None
    source["payee"] = "My Savings"
    result = collapse_transfer_rows([source, dest])
    assert result[0]["display_payee"] == "My Savings"
