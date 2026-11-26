"""Foundry Python transforms for the retrocession reporting pipeline.

Raw CSVs are uploaded to {RAW} as datasets. Each transform below calls the same
pandas functions that run and are tested locally (retro_pipeline.core), so
Foundry builds and local runs produce identical figures.

Written against the Python transforms API (transforms.api): transform_pandas for
single-output steps and transform.using with lightweight inputs/outputs for the
multi-output validation step. Check decorator names against the template of your
Code Repository; Palantir has been moving repositories to the lightweight API.
"""
from transforms.api import Input, Output, transform, transform_pandas

from retro_pipeline.core import report, validate
from retro_pipeline.datasets.paths import CLEAN, ONTOLOGY, RAW, REPORTING


@transform.using(
    clean_out=Output(f"{CLEAN}/retro_transactions_clean"),
    quarantine_out=Output(f"{CLEAN}/retro_transactions_quarantine"),
    issues_out=Output(f"{CLEAN}/validation_issues"),
    transactions=Input(f"{RAW}/retro_transactions"),
    contracts=Input(f"{RAW}/retro_contracts"),
    fx=Input(f"{RAW}/fx_rates"),
)
def validate_transactions(clean_out, quarantine_out, issues_out, transactions, contracts, fx):
    clean, quarantine, issues = validate.validate(transactions.pandas(), contracts.pandas(), fx.pandas())
    clean_out.write_table(clean)
    quarantine_out.write_table(quarantine)
    issues_out.write_table(issues)


@transform_pandas(
    Output(f"{REPORTING}/retro_reporting_dataset"),
    clean=Input(f"{CLEAN}/retro_transactions_clean"),
    contracts=Input(f"{RAW}/retro_contracts"),
    counterparties=Input(f"{RAW}/counterparties"),
    entities=Input(f"{RAW}/legal_entities"),
    fx=Input(f"{RAW}/fx_rates"),
)
def reporting_dataset(clean, contracts, counterparties, entities, fx):
    return report.reporting_dataset(clean, contracts, counterparties, entities, fx)


@transform_pandas(
    Output(f"{ONTOLOGY}/quarterly_contract_results"),
    rep=Input(f"{REPORTING}/retro_reporting_dataset"),
)
def quarterly_contract_results(rep):
    return report.quarterly_results(rep)


@transform_pandas(
    Output(f"{REPORTING}/entity_summary"),
    results=Input(f"{ONTOLOGY}/quarterly_contract_results"),
)
def entity_summary(results):
    return report.entity_summary(results)


@transform_pandas(
    Output(f"{ONTOLOGY}/counterparty_exposure"),
    contracts=Input(f"{RAW}/retro_contracts"),
    counterparties=Input(f"{RAW}/counterparties"),
    fx=Input(f"{RAW}/fx_rates"),
)
def counterparty_exposure(contracts, counterparties, fx):
    return report.counterparty_exposure(contracts, counterparties, fx)


@transform_pandas(
    Output(f"{REPORTING}/igr_elimination_check"),
    rep=Input(f"{REPORTING}/retro_reporting_dataset"),
)
def igr_elimination_check(rep):
    return report.igr_elimination(rep)


# Object-type backing datasets: one row per object, primary key first.

@transform_pandas(
    Output(f"{ONTOLOGY}/retro_contracts"),
    contracts=Input(f"{RAW}/retro_contracts"),
)
def ontology_retro_contracts(contracts):
    return contracts


@transform_pandas(
    Output(f"{ONTOLOGY}/legal_entities"),
    entities=Input(f"{RAW}/legal_entities"),
)
def ontology_legal_entities(entities):
    return entities


@transform_pandas(
    Output(f"{ONTOLOGY}/retrocessionaires"),
    counterparties=Input(f"{RAW}/counterparties"),
)
def ontology_retrocessionaires(counterparties):
    return counterparties


@transform_pandas(
    Output(f"{ONTOLOGY}/validation_issues"),
    issues=Input(f"{CLEAN}/validation_issues"),
    quarantine=Input(f"{CLEAN}/retro_transactions_quarantine"),
)
def ontology_validation_issues(issues, quarantine):
    q = quarantine[["txn_id", "contract_id", "entity_id", "period"]].drop_duplicates("txn_id")
    out = issues.merge(q, on="txn_id", how="left")
    out["resolution_comment"] = None
    return out
