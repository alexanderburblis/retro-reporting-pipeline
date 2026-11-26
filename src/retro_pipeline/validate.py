"""Clean and validate raw retrocession transactions.

Each rule returns the txn_ids it fails. Blocking rules send a record to quarantine,
so it never reaches the reporting dataset. The intra-group rule (R07) is a
reconciliation: it compares the ceding and the assuming entity's bookings for the
same contract and period, after all row-level rules have run.
"""
from __future__ import annotations

import pandas as pd

NON_NEGATIVE = {"CEDED_PREMIUM", "CEDED_CLAIMS_PAID", "RETRO_COMMISSION"}
REQUIRED = ["txn_id", "contract_id", "entity_id", "side", "period", "txn_type", "amount", "currency", "booking_date"]
IGR_TOLERANCE = 0.01  # absolute difference in transaction currency

RULES = {
    "R01_DUPLICATE": "Exact duplicate of another record (same txn_id and content)",
    "R02_ORPHAN_CONTRACT": "contract_id not found in the contract master",
    "R03_SIGN": "Negative amount on a line type that must be zero or positive",
    "R04_CURRENCY": "Currency unknown or no FX rate for the period",
    "R05_OUT_OF_PERIOD": "Booking date outside the contract's coverage period",
    "R06_REQUIRED_FIELD": "A mandatory field is empty",
    "R07_IGR_MISMATCH": "Intra-group ceded and assumed bookings do not agree",
}


def _clean(tx: pd.DataFrame) -> pd.DataFrame:
    tx = tx.copy()
    for col in ["txn_id", "contract_id", "entity_id", "side", "period", "txn_type", "currency"]:
        tx[col] = tx[col].astype("string").str.strip().str.upper()
    tx["amount"] = pd.to_numeric(tx["amount"], errors="coerce")
    tx["booking_date"] = pd.to_datetime(tx["booking_date"], errors="coerce")
    return tx


def validate(tx_raw: pd.DataFrame, contracts: pd.DataFrame, fx: pd.DataFrame
             ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (clean_transactions, quarantine, issues)."""
    tx = _clean(tx_raw)
    contracts = contracts.copy()
    contracts["inception_date"] = pd.to_datetime(contracts["inception_date"])
    contracts["expiry_date"] = pd.to_datetime(contracts["expiry_date"])
    issues: list[tuple[str, str]] = []

    dup_mask = tx.duplicated(keep="first")
    issues += [(i, "R01_DUPLICATE") for i in tx.loc[dup_mask, "txn_id"]]
    tx = tx.loc[~dup_mask].copy()  # keep the first copy; the duplicate is logged and dropped

    missing = tx[REQUIRED].isna().any(axis=1)
    issues += [(i, "R06_REQUIRED_FIELD") for i in tx.loc[missing, "txn_id"]]

    orphan = ~tx["contract_id"].isin(contracts["contract_id"])
    issues += [(i, "R02_ORPHAN_CONTRACT") for i in tx.loc[orphan, "txn_id"]]

    sign = tx["txn_type"].isin(NON_NEGATIVE) & (tx["amount"] < 0)
    issues += [(i, "R03_SIGN") for i in tx.loc[sign, "txn_id"]]

    fx_keys = set(zip(fx["period"], fx["currency"]))
    bad_ccy = [(p, c) not in fx_keys for p, c in zip(tx["period"], tx["currency"])]
    issues += [(i, "R04_CURRENCY") for i in tx.loc[bad_ccy, "txn_id"]]

    m = tx.merge(contracts[["contract_id", "inception_date", "expiry_date"]], on="contract_id", how="left")
    oop = m["inception_date"].notna() & ((m["booking_date"] < m["inception_date"]) |
                                         (m["booking_date"] > m["expiry_date"]))
    issues += [(i, "R05_OUT_OF_PERIOD") for i in m.loc[oop, "txn_id"]]

    failed = {i for i, _ in issues if _ != "R01_DUPLICATE"}
    passed = tx[~tx["txn_id"].isin(failed)].copy()

    # R07: reconcile intra-group ceded vs assumed, per contract, period and line type.
    ig_contracts = contracts.loc[contracts["retrocessionaire_id"].str.startswith("IG-"), "contract_id"]
    ig = passed[passed["contract_id"].isin(ig_contracts)]
    keys = ["contract_id", "period", "txn_type"]
    piv = ig.pivot_table(index=keys, columns="side", values="amount", aggfunc="sum").reindex(
        columns=["CEDED", "ASSUMED"])
    diff = (piv["CEDED"].fillna(0) - piv["ASSUMED"].fillna(0)).abs()
    broken = piv.index[(diff > IGR_TOLERANCE) | piv.isna().any(axis=1)]
    if len(broken):
        bk = pd.DataFrame(list(broken), columns=keys)
        hit = ig.merge(bk, on=keys)
        issues += [(i, "R07_IGR_MISMATCH") for i in hit["txn_id"]]

    issue_df = pd.DataFrame(issues, columns=["txn_id", "rule_id"]).drop_duplicates()
    issue_df["rule_description"] = issue_df["rule_id"].map(RULES)
    issue_df["severity"] = "BLOCKING"
    issue_df["status"] = "OPEN"
    issue_df.insert(0, "issue_id", [f"ISS-{n:05d}" for n in range(1, len(issue_df) + 1)])

    blocked = set(issue_df.loc[issue_df.rule_id != "R01_DUPLICATE", "txn_id"])
    clean = tx[~tx["txn_id"].isin(blocked)].reset_index(drop=True)
    quarantine = tx[tx["txn_id"].isin(blocked)].reset_index(drop=True)
    return clean, quarantine, issue_df.reset_index(drop=True)
