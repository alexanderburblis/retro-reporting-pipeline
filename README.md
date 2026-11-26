# Retrocession Financial Reporting Pipeline

A small, end-to-end reporting pipeline for intra-group and external retrocession, built on
synthetic data for a fictional reinsurance group (Rhenus Re Group). It takes raw contract and
transaction data, cleans and validates it in Python, builds a reconciled reporting dataset,
calculates premium, claims, commission, result and exposure indicators, and models the
results as business objects for a Palantir Foundry Ontology.

All data is synthetic. No company, contract or counterparty in this repository exists.

## What it does

| Step | Output | Where |
|---|---|---|
| Import | Legal entities, retrocessionaires, contracts, quarterly transactions, FX rates | `src/retro_pipeline/generate.py` |
| Clean and validate | Clean transactions, quarantine, validation issues (7 rules) | `src/retro_pipeline/validate.py` |
| Reporting dataset | Transactions in USD, enriched with contract and counterparty data | `src/retro_pipeline/report.py` |
| Indicators | Quarterly results per contract, entity summary, counterparty exposure, intra-group elimination check | `src/retro_pipeline/report.py` |
| Foundry | Python transforms (same code), Ontology object, link and action types | `foundry/`, `ontology/` |

## Indicators

From the ceding entity's point of view, in USD at the period rate:

- **Ceded premium**: cost of the retro protection
- **Ceded claims incurred**: paid recoveries plus the change in recoverable reserves
- **Retro commission**: commission received from the retrocessionaire
- **Net retro result** = claims incurred + commission − ceded premium
- **Retro loss ratio** = claims incurred / ceded premium
- **Counterparty exposure**: ceded limit in force at quarter end by retrocessionaire, with each
  external retrocessionaire's share of the external total
- **Intra-group elimination**: intra-group ceded and assumed amounts per period and line type must
  cancel out on consolidation

Basis: booked (written) amounts. This is deliberately not an IFRS 17 measurement (no contractual
service margin, risk adjustment, discounting or coverage-unit earning). It models the data
preparation and reconciliation a reporting team needs before the accounting engine runs.

## Results of the current run

| | |
|---|---|
| Raw transactions | 557 |
| Clean / quarantined / duplicates removed | 512 / 40 / 5 |
| Contracts, contract-quarter results | 20, 126 |
| Ceded premium, 2025-Q1 to 2026-Q3 | USD 229.0m (external 188.0m, intra-group 41.0m) |
| Retro loss ratio | 57.8% |
| Largest external concentration | 28.0% of external ceded limit (one retrocessionaire) |
| Intra-group elimination on clean data | all periods eliminate |

Every planted data defect is caught by the validation rules; the test suite checks this against
an answer key written by the generator.

## Run locally

```bash
pip install pandas numpy pytest
PYTHONPATH=src python -m retro_pipeline.pipeline   # writes data/raw, data/clean, data/reporting
python -m pytest                                   # 15 tests
```

## Documentation

- [Data lineage](docs/lineage.md)
- [Validation rules](docs/validation_rules.md)
- [Foundry deployment and Ontology](docs/foundry_deployment.md)

## Status of the Foundry layer

The transforms in `foundry/transforms-python` use the Foundry Python transforms API and call the
same functions as the local pipeline. `tests/test_foundry_wiring.py` runs them locally against a
stand-in for `transforms.api` and checks that they reproduce the local results.
Deployment on a Foundry Developer Tier account is described step by step in
[docs/foundry_deployment.md](docs/foundry_deployment.md).
