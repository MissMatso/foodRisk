# Active simulated dataset and feature contract

Revision: 20 October 2026. Active model: `simulated_rf_v2`. Schema: `simulated-household-v1`.

## Source and limitations

The original `ml_engine/data/nc-food-insecurity-training.csv` was recovered from the user-supplied `foodrisk_project (1)(1).zip` and restored byte for byte. SHA-256: `69ca747f2c58e90fb3c1939b58136b80da64c4ba43e8cb22994afc3b8967d888`.

It contains 10,000 simulated rows and 16 columns, with no blank values. Label counts are 4,726 high, 1,542 medium and 3,732 low. These are generated labels, not verified household outcomes. No missing cells or noise have been invented to make the data look real. The original archive's wording describing a real pilot is not accepted as evidence of real collection. A generator and verified collection protocol are not supplied.

The target is `risk_label == high` (1) versus low or medium (0), consistent with the documented pre-GHS High-versus-other policy. `risk_score`, `risk_label`, identifiers and location text never enter the predictor. The raw CSV's rounded `per_capita_income` is replaced in memory by income / size. CSV bytes remain unchanged.

## Twelve predictors

| Field | Transformation shared by training and inference |
|---|---|
| monthly_income | Numeric income; no GHS cap. Unknown live income remains missing until the saved median imputer. |
| income_per_capita | Income / household_size; missing when income is unknown. |
| household_size | Positive household count. |
| num_dependents | Children under five + elderly members, matching the original CSV derivation. The broader form total remains case context. |
| children_under_5 | Recorded under-five count. |
| elderly_members | Recorded elderly count; the form uses age 60+. Synthetic age definitions have no survey validation. |
| distance_to_market_km | Recorded numeric distance. |
| has_disabled_member | Boolean as 0/1. |
| has_chronic_illness | Boolean as 0/1. |
| land_ownership | Boolean as 0/1. |
| employment_status | employed, unemployed, informal or grant_only. |
| water_access | piped, communal, borehole, river or none. The later live `other` choice becomes missing and is mode-imputed. |

Province is retained for case administration and historical GHS compatibility. It is not used by the active model. The saved numeric median/scaling and categorical mode/one-hot pipelines are fitted on training rows only. Imputation supports unknown live entries; it does not imply missing training data were observed.

## Evaluation and history

Use stratified row splits of 6,000 train / 2,000 validation / 2,000 test (seeds 42 and 43), a predeclared 100-tree forest (depth 12, minimum leaf 3, balanced classes) and fixed binary threshold 0.5. This is a newly trained, versioned candidate on the old CSV, not a claim that the old serialized model is bit-identical. Evaluate dummy and logistic baselines without test-set selection. Generated-label performance cannot establish real-world accuracy or satisfy the lecturer's real-data requirement.

Display bands remain rounded score <=33 Low, <=66 Medium, otherwise High. They are not trained severity classes or calibrated probabilities. `risk_label`, raw `risk_score` and the model probability are different quantities.

The GHS source files, training path and historical candidates remain available for reproducibility and original-input explanations. Their seven-feature contract and different outcome are documented in `GHS_DATA_REFERENCE.md`; select `--dataset ghs2024` explicitly to train that alternative. Historical scores are never relabelled or overwritten.
