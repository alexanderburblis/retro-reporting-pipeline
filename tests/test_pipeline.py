import pandas as pd
import pytest

from retro_pipeline import pipeline, report, validate


@pytest.fixture(scope="session")
def run(tmp_path_factory):
    return pipeline.run(tmp_path_factory.mktemp("run"))


@pytest.fixture(scope="session")
def raw(run, tmp_path_factory):
    root = tmp_path_factory.getbasetemp() / "run0" / "data" / "raw"
    return {p.stem: pd.read_csv(p) for p in root.glob("*.csv")}


# --- validation ---------------------------------------------------------------

def test_every_planted_defect_is_caught(run, raw):
    issues = run["clean/validation_issues"]
    key = raw["planted_defects"]
    caught = set(zip(issues["txn_id"], issues["rule_id"]))
    missed = [(t, r) for t, r in zip(key["txn_id"], key["planted_rule"]) if (t, r) not in caught]
    assert missed == []


def test_rows_are_conserved(run, raw):
    n_raw = len(raw["retro_transactions"])
    n_dup = (run["clean/validation_issues"]["rule_id"] == "R01_DUPLICATE").sum()
    assert len(run["clean/retro_transactions_clean"]) + len(run["clean/retro_transactions_quarantine"]) + n_dup == n_raw


def test_clean_and_quarantine_do_not_overlap(run):
    a = set(run["clean/retro_transactions_clean"]["txn_id"])
    b = set(run["clean/retro_transactions_quarantine"]["txn_id"])
    assert a.isdisjoint(b)


def test_clean_data_satisfies_every_rule(run):
    c = run["clean/retro_transactions_clean"]
    assert c["txn_id"].is_unique
    assert not c[validate.REQUIRED].isna().any().any()
    assert not (c["txn_type"].isin(validate.NON_NEGATIVE) & (c["amount"] < 0)).any()
    assert c["currency"].isin(["USD", "EUR", "CHF", "SGD", "GBP"]).all()


def test_reserve_releases_are_not_flagged_as_sign_errors():
    contracts = pd.DataFrame([{"contract_id": "RC-1", "retrocessionaire_id": "EXT01",
                               "inception_date": "2025-01-01", "expiry_date": "2026-12-31"}])
    fx = pd.DataFrame([{"period": "2025-Q2", "currency": "USD", "rate_to_usd": 1.0}])
    tx = pd.DataFrame([{"txn_id": "T1", "contract_id": "RC-1", "entity_id": "RRZ", "side": "CEDED",
                        "period": "2025-Q2", "txn_type": "CEDED_CLAIMS_RESERVE_CHANGE", "amount": -500.0,
                        "currency": "USD", "booking_date": "2025-05-01"}])
    clean, quarantine, issues = validate.validate(tx, contracts, fx)
    assert len(clean) == 1 and issues.empty


# --- reporting and indicators -------------------------------------------------

def test_reporting_dataset_is_fully_converted_and_enriched(run):
    rep = run["reporting/retro_reporting_dataset"]
    assert rep["amount_usd"].notna().all()
    assert rep["counterparty_name"].notna().all()
    assert len(rep) == len(run["clean/retro_transactions_clean"])


def test_ceded_premium_ties_back_to_transactions(run):
    rep = run["reporting/retro_reporting_dataset"]
    res = run["reporting/quarterly_contract_results"]
    src = rep.loc[(rep.side == "CEDED") & (rep.txn_type == "CEDED_PREMIUM"), "amount_usd"].sum()
    assert res["ceded_premium_usd"].sum() == pytest.approx(src, abs=0.05)


def test_net_result_identity(run):
    r = run["reporting/quarterly_contract_results"]
    lhs = r["net_retro_result_usd"]
    rhs = r["claims_paid_usd"] + r["reserve_change_usd"] + r["retro_commission_usd"] - r["ceded_premium_usd"]
    assert (lhs - rhs).abs().max() < 0.01


def test_entity_summary_ties_to_contract_results(run):
    r = run["reporting/quarterly_contract_results"]
    s = run["reporting/entity_summary"]
    assert s["net_retro_result_usd"].sum() == pytest.approx(r["net_retro_result_usd"].sum(), abs=0.05)


def test_intra_group_eliminates_on_clean_data(run):
    assert run["reporting/igr_elimination_check"]["eliminates"].all()


def test_external_concentration_sums_to_one(run):
    e = run["reporting/counterparty_exposure"]
    assert e["share_of_external_limit"].sum() == pytest.approx(1.0, abs=1e-6)
    assert (e["ceded_limit_usd"] > 0).all()


def test_result_ids_are_unique_object_keys(run):
    assert run["reporting/quarterly_contract_results"]["result_id"].is_unique
    assert run["clean/validation_issues"]["issue_id"].is_unique


def test_pipeline_is_deterministic(tmp_path):
    a = pipeline.run(tmp_path / "a")["summary"]
    b = pipeline.run(tmp_path / "b")["summary"]
    assert a == b
