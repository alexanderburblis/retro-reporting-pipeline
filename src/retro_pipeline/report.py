"""Build the reporting dataset and the financial indicators.

Basis: simplified booked (written) amounts converted to USD at the period rate.
This is deliberately NOT an IFRS 17 measurement: there is no contractual service
margin, risk adjustment, discounting or earning pattern. The point is the data
flow a retrocession reporting team relies on before the accounting engine runs:
complete, reconciled, explainable inputs.

Sign convention, from the ceding entity's point of view:
  ceded premium           = cost of retro protection (outflow)
  ceded claims incurred   = paid recoveries + change in recoverable reserves (inflow)
  retro commission        = commission received from the retrocessionaire (inflow)
  net retro result        = claims incurred + commission - ceded premium
"""
from __future__ import annotations

import pandas as pd

ORDER = ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3"]


def reporting_dataset(clean: pd.DataFrame, contracts: pd.DataFrame, cps: pd.DataFrame,
                      entities: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    df = clean.merge(fx, on=["period", "currency"], how="left", validate="many_to_one")
    df["amount_usd"] = (df["amount"] * df["rate_to_usd"]).round(2)
    df = df.merge(contracts[["contract_id", "ceding_entity_id", "retrocessionaire_id", "contract_type",
                             "line_of_business", "limit_amount", "currency"]].rename(
                                 columns={"currency": "contract_currency"}),
                  on="contract_id", how="left", validate="many_to_one")
    df = df.merge(cps[["counterparty_id", "counterparty_name", "counterparty_type", "rating"]],
                  left_on="retrocessionaire_id", right_on="counterparty_id", how="left").drop(
                      columns="counterparty_id")
    df = df.merge(entities[["entity_id", "entity_name"]], on="entity_id", how="left")
    df["is_intra_group"] = df["counterparty_type"].eq("INTRA_GROUP")
    return df


def quarterly_results(rep: pd.DataFrame, side: str = "CEDED") -> pd.DataFrame:
    """One row per contract and period with premium, claims, commission and result in USD."""
    d = rep[rep["side"] == side]
    p = d.pivot_table(index=["contract_id", "period", "ceding_entity_id", "retrocessionaire_id",
                             "counterparty_type", "line_of_business", "contract_type"],
                      columns="txn_type", values="amount_usd", aggfunc="sum", fill_value=0).reset_index()
    for c in ["CEDED_PREMIUM", "CEDED_CLAIMS_PAID", "CEDED_CLAIMS_RESERVE_CHANGE", "RETRO_COMMISSION"]:
        if c not in p:
            p[c] = 0.0
    p["ceded_claims_incurred_usd"] = p["CEDED_CLAIMS_PAID"] + p["CEDED_CLAIMS_RESERVE_CHANGE"]
    p = p.rename(columns={"CEDED_PREMIUM": "ceded_premium_usd", "RETRO_COMMISSION": "retro_commission_usd",
                          "CEDED_CLAIMS_PAID": "claims_paid_usd",
                          "CEDED_CLAIMS_RESERVE_CHANGE": "reserve_change_usd"})
    p["net_retro_result_usd"] = (p["ceded_claims_incurred_usd"] + p["retro_commission_usd"]
                                 - p["ceded_premium_usd"])
    p["retro_loss_ratio"] = (p["ceded_claims_incurred_usd"] / p["ceded_premium_usd"]).where(
        p["ceded_premium_usd"] > 0)
    p.insert(0, "result_id", p["contract_id"] + "|" + p["period"])
    p["period"] = pd.Categorical(p["period"], ORDER, ordered=True)
    return p.sort_values(["period", "contract_id"]).reset_index(drop=True).assign(
        period=lambda x: x["period"].astype(str)).round(4)


def counterparty_exposure(contracts: pd.DataFrame, cps: pd.DataFrame, fx: pd.DataFrame,
                          as_of_period: str = "2026-Q3") -> pd.DataFrame:
    """Ceded limit in force at the period end, by retrocessionaire, with concentration share."""
    c = contracts.copy()
    end = pd.Period(as_of_period, "Q").end_time
    c = c[(pd.to_datetime(c["inception_date"]) <= end) & (pd.to_datetime(c["expiry_date"]) >= end)]
    rate = fx[fx["period"] == as_of_period].set_index("currency")["rate_to_usd"]
    c["limit_usd"] = c["limit_amount"] * c["currency"].map(rate)
    e = c.groupby("retrocessionaire_id", as_index=False).agg(
        contracts_in_force=("contract_id", "count"), ceded_limit_usd=("limit_usd", "sum"))
    e = e.merge(cps, left_on="retrocessionaire_id", right_on="counterparty_id").drop(columns="counterparty_id")
    ext = e["counterparty_type"].eq("EXTERNAL")
    e["share_of_external_limit"] = (e["ceded_limit_usd"] / e.loc[ext, "ceded_limit_usd"].sum()).where(ext)
    e["as_of_period"] = as_of_period
    return e.sort_values("ceded_limit_usd", ascending=False).reset_index(drop=True).round(4)


def igr_elimination(rep: pd.DataFrame) -> pd.DataFrame:
    """Group view: intra-group ceded and assumed amounts must cancel out on consolidation."""
    ig = rep[rep["is_intra_group"]]
    g = ig.pivot_table(index=["period", "txn_type"], columns="side", values="amount_usd",
                       aggfunc="sum", fill_value=0).reset_index()
    g["elimination_difference_usd"] = (g.get("CEDED", 0) - g.get("ASSUMED", 0)).round(2)
    g["eliminates"] = g["elimination_difference_usd"].abs() <= 0.05
    return g.rename(columns={"CEDED": "ceded_usd", "ASSUMED": "assumed_usd"})


def entity_summary(results: pd.DataFrame) -> pd.DataFrame:
    s = results.groupby(["ceding_entity_id", "period", "counterparty_type"], as_index=False)[
        ["ceded_premium_usd", "ceded_claims_incurred_usd", "retro_commission_usd", "net_retro_result_usd"]].sum()
    s["retro_loss_ratio"] = s["ceded_claims_incurred_usd"] / s["ceded_premium_usd"]
    return s.round(4)
