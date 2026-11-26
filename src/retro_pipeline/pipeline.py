"""Run the full pipeline locally: raw -> validated -> reporting -> indicators.

The same functions are called by the Foundry transforms in foundry/transforms-python,
so local and Foundry results come from one codebase.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from retro_pipeline import generate, report, validate

ROOT = Path(__file__).resolve().parents[2]


def run(root: Path = ROOT) -> dict[str, pd.DataFrame]:
    raw_dir, clean_dir, rep_dir = root / "data" / "raw", root / "data" / "clean", root / "data" / "reporting"
    raw = generate.generate(raw_dir)

    clean, quarantine, issues = validate.validate(raw["retro_transactions"], raw["retro_contracts"], raw["fx_rates"])
    rep = report.reporting_dataset(clean, raw["retro_contracts"], raw["counterparties"],
                                   raw["legal_entities"], raw["fx_rates"])
    results = report.quarterly_results(rep)
    out = {
        "clean/retro_transactions_clean": clean,
        "clean/retro_transactions_quarantine": quarantine,
        "clean/validation_issues": issues,
        "reporting/retro_reporting_dataset": rep,
        "reporting/quarterly_contract_results": results,
        "reporting/entity_summary": report.entity_summary(results),
        "reporting/counterparty_exposure": report.counterparty_exposure(
            raw["retro_contracts"], raw["counterparties"], raw["fx_rates"]),
        "reporting/igr_elimination_check": report.igr_elimination(rep),
    }
    for name, df in out.items():
        path = root / "data" / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)

    summary = {
        "raw_transactions": len(raw["retro_transactions"]),
        "clean_transactions": len(clean),
        "quarantined_transactions": len(quarantine),
        "issues_by_rule": issues["rule_id"].value_counts().sort_index().to_dict(),
        "ceded_premium_usd_total": round(float(results["ceded_premium_usd"].sum()), 2),
        "net_retro_result_usd_total": round(float(results["net_retro_result_usd"].sum()), 2),
        "igr_periods_not_eliminating": int((~out["reporting/igr_elimination_check"]["eliminates"]).sum()),
    }
    (root / "data" / "run_summary.json").write_text(json.dumps(summary, indent=2))
    return out | {"summary": summary}


if __name__ == "__main__":
    print(json.dumps(run()["summary"], indent=2))
