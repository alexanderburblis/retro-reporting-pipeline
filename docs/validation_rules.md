# Validation rules

All rules are blocking except R01, where the duplicate copy is removed and the original kept.
A blocked record goes to `retro_transactions_quarantine` and gets one row per failed rule in
`validation_issues`, with status `OPEN`. In Foundry, the reporting team resolves each issue
through the `resolve-validation-issue` action, which records a status and a comment on the object.

| Rule | Check | Why it matters | Found in current run |
|---|---|---|---|
| R01_DUPLICATE | Exact duplicate row | Double-counted premium or recoveries | 5 |
| R02_ORPHAN_CONTRACT | contract_id missing from the contract master | Amount cannot be attributed to a treaty or counterparty | 5 |
| R03_SIGN | Negative premium, paid claims or commission | Sign errors flip the result; reserve changes may legitimately be negative and are exempt | 2 |
| R04_CURRENCY | Unknown currency or no FX rate for the period | Amount cannot be converted to the reporting currency | 5 |
| R05_OUT_OF_PERIOD | Booking date outside the contract's coverage | Booking on the wrong treaty or wrong period | 5 |
| R06_REQUIRED_FIELD | Mandatory field empty | Incomplete record | 5 |
| R07_IGR_MISMATCH | Intra-group ceded ≠ assumed for the same contract, quarter and line type (tolerance 0.01) | Group consolidation would not eliminate | 18 |

R07 runs after the row-level rules. It flags both sides of a mismatched pair, and also the
surviving side when its counterpart was quarantined by another rule, because a one-sided
intra-group booking would equally break the elimination.

## How the rules are tested

`generate.py` plants defects on purpose and writes an answer key (`data/raw/planted_defects.csv`).
`test_every_planted_defect_is_caught` fails if any planted defect is not reported under the rule
it was planted for.
