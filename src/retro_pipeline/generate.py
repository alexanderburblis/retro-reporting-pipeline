"""Generate a synthetic retrocession dataset for a fictional reinsurance group.

Everything here is invented: Rhenus Re Group and its entities, counterparties and
contracts do not exist. A fixed seed makes every run identical, so tests and
published figures are reproducible.

The generator also plants known data defects (duplicates, sign errors, orphan
records, unknown currencies, out-of-period bookings and intra-group mismatches)
so that the validation layer has something real to catch.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261126
PERIODS = ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3"]

ENTITIES = pd.DataFrame(
    [
        ("RRZ", "Rhenus Re Ltd", "CH", "USD"),
        ("RRE", "Rhenus Re Europe SA", "LU", "EUR"),
        ("RRA", "Rhenus Re America Inc", "US", "USD"),
        ("RRS", "Rhenus Re Asia Pte Ltd", "SG", "SGD"),
        ("RRC", "Rhenus Corporate Solutions Ltd", "CH", "CHF"),
    ],
    columns=["entity_id", "entity_name", "country", "functional_currency"],
)

EXTERNAL = [
    ("EXT01", "Aurora Retro Ltd", "BM", "A+"),
    ("EXT02", "Northgate Re", "GB", "A"),
    ("EXT03", "Kestrel Capital Re", "BM", "A-"),
    ("EXT04", "Lindqvist Re AB", "SE", "AA-"),
    ("EXT05", "Pacific Shield Re", "SG", "A"),
    ("EXT06", "Meridian ILS Fund", "KY", "NR (collateralised)"),
]

FX_BASE = {"USD": 1.0, "EUR": 1.08, "CHF": 1.12, "SGD": 0.74, "GBP": 1.27}

LINES = ["Property Cat", "Casualty", "Specialty", "Life & Health"]
TYPES = ["Quota Share", "Excess of Loss", "Stop Loss"]


def _counterparties() -> pd.DataFrame:
    rows = [(f"IG-{e}", n, "INTRA_GROUP", e, c, "AA-") for e, n, c, _ in ENTITIES.itertuples(index=False)]
    rows += [(cp, n, "EXTERNAL", None, c, r) for cp, n, c, r in EXTERNAL]
    return pd.DataFrame(rows, columns=["counterparty_id", "counterparty_name", "counterparty_type",
                                       "group_entity_id", "country", "rating"])


def _fx(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for ccy, base in FX_BASE.items():
        level = base
        for p in PERIODS:
            level = level * (1 + rng.normal(0, 0.012)) if ccy != "USD" else 1.0
            rows.append((p, ccy, round(level, 5)))
    return pd.DataFrame(rows, columns=["period", "currency", "rate_to_usd"])


def _contracts(rng: np.random.Generator, cps: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n = 0
    for e in ENTITIES.itertuples(index=False):
        # Each entity cedes to 2-3 external retrocessionaires and, unless it is the parent,
        # retrocedes part of its book intra-group to the parent RRZ.
        targets = list(rng.choice(cps.loc[cps.counterparty_type == "EXTERNAL", "counterparty_id"], 3, replace=False))
        if e.entity_id != "RRZ":
            targets.append("IG-RRZ")
        else:
            targets.append("IG-RRC")  # parent retrocedes a specialty slice to the corporate-solutions carrier
        for cp in targets:
            n += 1
            ctype = "Quota Share" if cp.startswith("IG-") else rng.choice(TYPES)
            start_q = int(rng.integers(0, 3))
            inception = pd.Period(PERIODS[start_q], "Q").start_time
            limit = float(rng.choice([25, 50, 75, 100, 150, 250])) * 1e6
            rows.append({
                "contract_id": f"RC-{n:04d}",
                "ceding_entity_id": e.entity_id,
                "retrocessionaire_id": cp,
                "contract_type": ctype,
                "line_of_business": rng.choice(LINES),
                "inception_date": inception.date(),
                "expiry_date": (inception + pd.DateOffset(years=2) - pd.Timedelta(days=1)).date(),
                "currency": e.functional_currency,
                "cession_rate": round(float(rng.uniform(0.15, 0.4)), 3) if ctype == "Quota Share" else None,
                "limit_amount": limit,
                "attachment_amount": 0.0 if ctype == "Quota Share" else limit * float(rng.choice([0.5, 1, 2])),
                "commission_rate": round(float(rng.uniform(0.18, 0.32)), 3) if ctype == "Quota Share" else 0.0,
            })
    return pd.DataFrame(rows)


def _transactions(rng: np.random.Generator, contracts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    t = 0
    for c in contracts.itertuples(index=False):
        start = pd.Period(pd.Timestamp(c.inception_date), "Q")
        for p in PERIODS:
            q = pd.Period(p, "Q")
            if q < start:
                continue
            base_premium = c.limit_amount * float(rng.uniform(0.010, 0.025))
            loss_ratio = float(rng.gamma(2.0, 0.28))  # mean ~56%, heavy right tail
            claims_incurred = base_premium * loss_ratio
            paid_share = float(rng.uniform(0.3, 0.7))
            book = q.start_time + pd.Timedelta(days=int(rng.integers(5, 80)))
            lines = [
                ("CEDED_PREMIUM", base_premium),
                ("CEDED_CLAIMS_PAID", claims_incurred * paid_share),
                ("CEDED_CLAIMS_RESERVE_CHANGE", claims_incurred * (1 - paid_share)),
                ("RETRO_COMMISSION", base_premium * c.commission_rate),
            ]
            for ttype, amt in lines:
                if amt == 0:
                    continue
                t += 1
                rows.append({"txn_id": f"T{t:06d}", "contract_id": c.contract_id, "entity_id": c.ceding_entity_id,
                             "side": "CEDED", "period": p, "txn_type": ttype, "amount": round(amt, 2),
                             "currency": c.currency, "booking_date": book.date()})
                # Intra-group: the receiving entity books the mirror "assumed" entry in the same currency.
                if c.retrocessionaire_id.startswith("IG-"):
                    t += 1
                    rows.append({"txn_id": f"T{t:06d}", "contract_id": c.contract_id,
                                 "entity_id": c.retrocessionaire_id[3:], "side": "ASSUMED", "period": p,
                                 "txn_type": ttype, "amount": round(amt, 2), "currency": c.currency,
                                 "booking_date": book.date()})
    return pd.DataFrame(rows)


def _plant_defects(rng: np.random.Generator, tx: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Insert known defects and return (transactions, answer_key)."""
    key = []
    tx = tx.copy()
    idx = rng.choice(tx.index, 40, replace=False)
    groups = np.array_split(idx, 8)

    dup = tx.loc[groups[0]].copy()                       # exact duplicate rows
    key += [(r, "R01_DUPLICATE") for r in dup.txn_id]
    # Sign error: only on line types that can never be negative (reserve changes legitimately can).
    sign_rows = [i for i in groups[1] if tx.at[i, "txn_type"] != "CEDED_CLAIMS_RESERVE_CHANGE"]
    tx.loc[sign_rows, "amount"] *= -1
    key += [(r, "R03_SIGN") for r in tx.loc[sign_rows, "txn_id"]]
    tx.loc[groups[2], "contract_id"] = "RC-9999"          # orphan contract
    key += [(r, "R02_ORPHAN_CONTRACT") for r in tx.loc[groups[2], "txn_id"]]
    tx.loc[groups[3], "currency"] = "XXX"                 # unknown currency
    key += [(r, "R04_CURRENCY") for r in tx.loc[groups[3], "txn_id"]]
    tx.loc[groups[4], "booking_date"] = pd.Timestamp("2024-06-30").date()  # before any inception
    key += [(r, "R05_OUT_OF_PERIOD") for r in tx.loc[groups[4], "txn_id"]]
    tx.loc[groups[5], "amount"] = np.nan                  # missing amount
    key += [(r, "R06_REQUIRED_FIELD") for r in tx.loc[groups[5], "txn_id"]]
    # Intra-group mismatch: change the assumed side only, so ceded != assumed.
    ig = tx[(tx.side == "ASSUMED") & ~tx.index.isin(idx)].sample(4, random_state=SEED).index
    tx.loc[ig, "amount"] = (tx.loc[ig, "amount"] * 1.07).round(2)
    key += [(r, "R07_IGR_MISMATCH") for r in tx.loc[ig, "txn_id"]]

    tx = pd.concat([tx, dup], ignore_index=True).sample(frac=1, random_state=SEED).reset_index(drop=True)
    return tx, pd.DataFrame(key, columns=["txn_id", "planted_rule"])


def generate(out_dir: Path) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(SEED)
    cps = _counterparties()
    fx = _fx(rng)
    contracts = _contracts(rng, cps)
    tx, key = _plant_defects(rng, _transactions(rng, contracts))
    tables = {"legal_entities": ENTITIES, "counterparties": cps, "fx_rates": fx,
              "retro_contracts": contracts, "retro_transactions": tx, "planted_defects": key}
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)
    return tables


if __name__ == "__main__":
    t = generate(Path(__file__).resolve().parents[2] / "data" / "raw")
    print({k: len(v) for k, v in t.items()})
