# Historical GHS 2024 model reference

This describes retained GHS candidates, not the active simulated-data release.

# Real-data preparation and feature contract

Revision: 14 October 2026. Schema: `ghs2024-food-access-v1`.

## Source and attribution

Statistics South Africa. General Household Survey 2024 [dataset]. Version 1. Pretoria: Statistics SA [producer], 2025. Cape Town: DataFirst [distributor], 2025. DOI: https://doi.org/10.25828/rx6h-3r34.

Source: https://www.datafirst.uct.ac.za/dataportal/index.php/catalog/1027 (CC-BY public-use data). The supplied household and person DTA files are preserved unchanged under `ml_engine/data/ghs2024/`, alongside the source metadata and questionnaire. They are edited, anonymised survey releases, not unprocessed field collection files. Raw file SHA-256 hashes, code hashes and package versions are in each model manifest. Do not attempt to identify respondents.

## Observed data quality

| Check | Result before target exclusion |
|---|---:|
| Household rows / unique household IDs | 20,940 / 20,940 |
| Person rows | 70,440 |
| Northern Cape households | 855 |
| Income coded unspecified (9999999) | 433 |
| Food-shortage outcome unspecified (9) | 29 |
| Retained known-outcome households | 20,911 |
| Positive / negative outcomes | 3,832 / 17,079 |
| Known incomes above the model cap | 3,084 |

Blank cells are not the only form of missing information. The official numerical codes above become missing values. No artificial blanks, random noise, invented outcomes or synthetic records are added to training. No imputation is applied to the outcome. The roster join validates household IDs, person IDs and household counts. All released ages used in this revision are valid; under-five and 60+ counts consequently have no missing values.

## Exact mapping

| Model field | Source / transformation | Live form |
|---|---|---|
| monthly_income | `totmhinc`; 9999999 -> missing; cap at R20,000 | Nullable encrypted income; same cap in feature construction |
| income_per_capita | Capped income / `hholdsz` | Derived from same capped income and size |
| household_size | `hholdsz`, checked against person roster | Household size >= 1 |
| children_under_5 | Count `age < 5` grouped by `uqnr` | Children aged 0–4 |
| elderly_members | Count `age >= 60` grouped by `uqnr` | Members aged 60 or older |
| province | `prov`, string codes 1–9 | Province choice; old pilot records default to Northern Cape (3) |
| water_access | `wat_drinkwat`, mapping below | Matched water-source choice |
| reported_food_shortage (target only) | FSD8 `fsd_ranout`: 1 -> positive; 2 -> negative; 9 -> excluded | Never supplied to the predictor |

Income policy: the metadata (printed page 106) describes restricted measurement above R20,000, although the release contains values above that amount. Preserve those raw values and apply an explicit modelling cap at R20,000 on both training and inference. This conservative choice needs a sensitivity study before operational use; it is not a claim that large incomes are errors.

Water mapping: 1/2 -> piped; 3/9 -> borehole; 5/6 -> communal; 10/11 -> river; other valid source codes 1–16 -> other. Invalid/unspecified codes become missing. The legacy live `none` choice becomes missing rather than an invented survey category. Categorical unknowns are handled by the saved preprocessing pipeline.

`chld5yr_hh` is not used: it includes children aged five, which would not match the under-five form field. Dependents, employment, health flags, land ownership and distance to market remain case-management fields. They are not predictors in this revision. No other food-security response is used as a feature. Identifiers, PSU and survey weights are used for splitting/evaluation only.

## Outcome meaning and evaluation

The label records a household's reported experience of running out of food for lack of money/resources in the previous 12 months. It is a binary proxy outcome, not a future forecast, causal finding or standard food-insecurity severity index. The national survey includes 855 Northern Cape households, so the model is trained nationally and reports a separate Northern Cape test subset.

PSU groups are split into approximately 60% training, 20% validation and 20% test (seeds 42 and 43). Numeric median imputation with missing indicators and scaling, and categorical mode imputation plus one-hot encoding, are fitted on training data only. The persisted pipeline performs identical transformations at inference. Threshold selection uses validation F1; the final test is not used to tune it.

The training loss and main metrics are unweighted. Household-weighted test metrics are included as a sensitivity analysis. They are not survey-design confidence intervals or population prevalence estimates. No temporal test or independent NGO validation exists yet. The old fabricated dataset and artifact are no longer part of the active training path.
