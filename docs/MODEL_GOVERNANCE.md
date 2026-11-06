# Model lifecycle and review policy

Implemented: local version registry, hashes and lineage, separate candidate training, runtime selection, approval records, aggregate drift screening, held-out false-positive/false-negative review files and on-demand explanations. This is a research workflow, not a production monitoring service.

Active release: `simulated_rf_v2` on the restored original simulated CSV. The real-data requirement remains unmet. GHS models are retained as historical alternatives.

## Version and schema control

Run `python manage.py train_model --model-version my_unique_candidate`. An existing directory causes an error; training never overwrites or activates a version. A failed run can leave an incomplete directory, which must not be activated. The selected version is `FOODRISK_MODEL_VERSION` in `.env`/environment; restart the application after a change. Rollback means selecting a retained compatible version and restarting. Never delete a version while historical predictions still need its explanations.

Each `ml_engine/models/registry/<version>/` contains:

- `model.joblib`: fitted preprocessing and Random Forest.
- `manifest.json`: version, feature schema, target, hashes, environment, source lineage, split sizes, parameters, validation, comparison results, drift reference and limitations.
- `data_audit.json`: raw counts, missing codes, exclusions and transformations.
- `split_membership.csv`: source row identifier and assigned split; GHS candidates additionally retain PSU.
- `test_predictions.csv`: dataset labels (simulated for the active release), probabilities and false-positive/false-negative groups for research review.
- `approval.json`, only after an actual review command has been run.

Schema changes require a new schema identifier, corresponding training/inference mapping, compatibility checks, migration if live fields change, tests and updated documentation. Runtime checks version, schema and model checksum before loading. The joblib directory is trusted administrator-controlled storage: hashes detect file changes but are not digital signatures or protection against a malicious publisher. Historical encrypted snapshots are never exposed by the prediction API serializer.

## Review, approval and activation

The student/model maintainer prepares the candidate and review evidence. An active administrator records the named reviewer and evidence hash, for example:

```bash
python manage.py approve_model --model-version my_unique_candidate --reviewer actual_admin_username --scope research --evidence review.md --notes "Research review and limitations accepted"
```

This is an OS-operator command, not independent reviewer authentication; two-person review is a policy requirement, not technically enforced. The reviewer must inspect data lineage, leakage, baselines, missingness, subgroup errors, metric targets and intended use. Operational approval additionally requires external NGO validation and metric gates recorded in the immutable candidate manifest. The supplied candidate has neither operational approval nor external validation. `DEBUG=False` refuses to load it for serving. No approval has been manufactured for this release.

Future operational validation must use consented, representative NGO data with an independently observed, comparable outcome and a pre-agreed threshold/decision policy. Publish a new candidate with that evidence; do not edit an existing candidate manifest to make it appear approved. The application does not approve food-aid eligibility or deny assistance automatically. DEBUG mode is for research and demonstration, not an operational approval bypass.

## Drift checks

A manual command compares recent *mapped model inputs* with the training reference:

```bash
python manage.py check_model_drift --csv recent_mapped_inputs.csv --model-version simulated_rf_v2 --output drift_review_20261020.json
```

The CSV must contain the selected manifest’s feature columns. The active release uses the twelve columns in `DATA_DICTIONARY.md`, including income divided by household size and dependents derived from the two age counts. Use blank values for unknowns; do not include identifiers. Historical GHS candidates retain their own cap and mappings. The report contains aggregate statistics only. An output filename cannot be overwritten. This command is not scheduled automatically and does not export live household data.

At least 100 records are required. Provisional review triggers: total variation >0.20, missing-rate change >0.10, or unseen/out-of-training-range share >0.05. Below 100 rows, report insufficient data. These are screening thresholds, not clinical/social-policy limits or evidence of model deterioration. Different NGO intake populations may trigger alerts because the active reference is simulated. Input drift does not detect concept drift or measure false negatives without observed outcomes.

Suggested responsibility: the NGO data steward runs the screen monthly when enough new assessments exist, and after source/form changes. The model maintainer investigates alerts. The reviewer records whether the cause is capture errors, schema change, genuine population change or sampling variation.

## Error review and retraining

`test_predictions.csv` contains research errors using the candidate’s recorded binary threshold (0.5 for the active simulated model); these are distinct from the UI High band. Review false negatives first for missed needs, and false positives for unnecessary follow-up. Do not label predictions as false positives/negatives based on staff disagreement alone: obtain an independently observed outcome with compatible wording and time window. Record model version, score, outcome source/date, error type, subgroup, finding and proposed change in a controlled review log. Keep names/contact details out of the model registry.

Retraining requires review after confirmed data-source/schema changes, sustained drift on two adequately sized batches, materially worse performance on verified recent labels, or a six-month review. These triggers initiate investigation; they do not automatically train or activate a new model. Use fresh time-separated validation when longitudinal data become available. Compare against the prior model and a simple baseline, assess Northern Cape and relevant subgroup errors, check calibration and decision impact, then obtain approval. Preserve a rollback candidate and changelog.

## Explanation and latency contract

Normal scoring saves score, category, version, artifact hash, schema and an encrypted snapshot, with explanation initially NULL. Staff/admin can POST an explanation request. TreeSHAP imports and initialises lazily, uses the original snapshot/version, and saves contributions on that prediction. Repeat requests return the stored values. Editing a household does not alter old explanations. Existing historical explanations remain readable; legacy records without a snapshot cannot be freshly explained. A failure leaves the score intact. Multiple simultaneous first requests may compute twice; persistence keeps the first result. Explanation computation is synchronous on demand; no Celery queue is implemented.

Food-risk analytics and dashboard scores use only the configured model version. The administrator report counts accounts and system records, with no risk-score aggregation. History and exports retain version labels for all assessments. Aggregate SHAP summaries describe the selected explained subset, not global or population feature importance. SHAP associations are not causes, and exact TreeSHAP is retained rather than replacing it with an unvalidated heuristic.

A five-second check detects slow scoring after computation; it does not interrupt it and starts after model loading. `scripts/benchmark_local.py` measures complete loopback HTTP requests including a cold model load, SQLite persistence, authentication and concurrent clients. Its measured local results are in `benchmark.json`; production sizing and uptime remain open.

## Model-wide explanation summary (November 2026)

`python manage.py explain_model` writes `global_explanation.json` beside the model: the TreeSHAP baseline (the model's average training output, 0.499 for `simulated_rf_v2`) and the mean absolute and mean signed SHAP value per feature over the 2,000 held-out simulated test records. The file stores the model file's checksum and is ignored if it does not match the serving artifact. Rerun the command after training or approving a new version. For `simulated_rf_v2` the ranking is income per person, monthly income, employment status, water access, distance to market, then the household-composition and health flags. Ward, village and province are not inputs. The summary describes the model as evaluated on simulated labels: associations, not causes.
