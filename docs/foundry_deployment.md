# Foundry deployment and Ontology

Target: a Palantir Foundry Developer Tier account (free). The steps below follow the order of the
build: data in, transforms, Ontology, application.

## 1. Project and raw data

1. Create a project, for example `Retro Reporting Pipeline`, with folders `raw`, `clean`,
   `reporting` and `ontology`.
2. Run the generator locally (`PYTHONPATH=src python -m retro_pipeline.generate`) and upload the
   five CSVs from `data/raw` (all except `planted_defects.csv`) into `raw` as datasets, keeping the
   file names as dataset names.
3. Set the column types on upload: dates as `date`, amounts and rates as `double`.

## 2. Python transforms

1. Create a Python Code Repository in the project.
2. Copy `foundry/transforms-python/src/retro_pipeline` into the repository's `src` folder.
3. In `datasets/paths.py`, set `ROOT` to the project path.
4. Add `pandas` as a dependency in the repository's libraries panel if it is not there.
5. Commit, let the checks run, then build `ontology/quarterly_contract_results` and
   `ontology/validation_issues`; Foundry builds the upstream datasets in order.
6. Compare the outputs with the local run: the figures should match `data/run_summary.json`.

If the repository template uses a different decorator style, keep the function bodies and adjust
only the decorators; the logic lives in `retro_pipeline.core`.

## 3. Ontology

Create the object types, link types and action type defined in `ontology/ontology.yaml` in
Ontology Manager:

| Object type | Backing dataset | Primary key |
|---|---|---|
| LegalEntity | ontology/legal_entities | entity_id |
| Retrocessionaire | ontology/retrocessionaires | counterparty_id |
| RetroContract | ontology/retro_contracts | contract_id |
| QuarterlyContractResult | ontology/quarterly_contract_results | result_id |
| CounterpartyExposure | ontology/counterparty_exposure | retrocessionaire_id |
| ValidationIssue | ontology/validation_issues | issue_id |

Links: contract → ceding entity, contract → retrocessionaire, result → contract,
issue → contract, exposure → retrocessionaire.

Action: `resolve-validation-issue` on ValidationIssue with parameters `status`
(OPEN, RESOLVED, ACCEPTED_AS_IS) and a required `resolution_comment`.

## 4. Application (optional)

A Workshop module with three tabs:
- **Quarterly results**: QuarterlyContractResult filtered by period and entity, with premium,
  claims, commission and net result.
- **Exposure**: CounterpartyExposure with rating and share of the external limit.
- **Data quality**: open ValidationIssue objects with the resolve action, so quarantined records
  are cleared and commented before the close.

## 5. Evidence for the portfolio

After deployment, add screenshots of the lineage graph, the Ontology object types and the
Workshop module to `docs/screenshots/` and update the status section of the README.
