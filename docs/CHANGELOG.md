# Model and application changelog

## 3 November 2026 — Follow-up dates and form wording

- An **open action's follow-up date cannot be in the past** (form check plus a date-picker minimum). Completed actions may carry a past date, and an existing overdue action can still be edited or completed without changing its date.
- Follow-up dates now use the same `20 Aug 2026` format as every other date.
- Plain labels on the household form ("Number of dependents", "Distance to the nearest market (km)", "The household owns land" and so on).
- 283 automated tests (6 added).

## 3 November 2026 — Analyst response coverage and sign-in clarity

- **Response coverage** on the analyst report: high-risk households reached (at least one recorded action), not yet reached, open and overdue follow-ups, overall and by ward. Each household counts once using its latest current-model assessment; an action on an earlier assessment still counts. Counts only.
- **Reports page reordered:** operational analytics first (charts, coverage, risk by group, downloads), then **About the model** (performance card and model-wide SHAP). The table averaging only staff-requested explanations was removed; the model-wide table replaces it. Chart titles say they count assessments.
- **Sign-in page while already signed in** now says which account the browser is using and offers Continue or Sign out, instead of silently opening that account's pages.
- **Expired form page:** a plain explanation (reload, or use a private window for a second account) replaces Django's technical CSRF 403 page.
- 277 automated tests (5 added).

## 3 November 2026 — Menu tidy

- Removed the duplicate **Register Household** menu item. Staff register from the **+ Register Household** button on the Households page, after searching, which supports the duplicate-prevention workflow.

## 3 November 2026 — Diagrams refreshed

- `register-activity`, `register-sequence`, `classes`, `erd` and `account-security-sequence` updated for the shared-address rule, the database check constraints, the `account_created` event and account changes on the Users page, and re-rendered with PlantUML 1.2024.7.

## 3 November 2026 — Consistency fixes

- **Delete household in the interface.** BR-12 allowed only a System Admin to delete, but there was no button anywhere; deletion needed the API. The household page now shows **Delete household** to System Admins, with a confirmation page listing the assessments and interventions that will be removed. The deletion is audited and the admin lands on the audit log filtered to it.
- **Django Admin link removed from the menu**, so the Users page really is the one place accounts are managed. `/admin/` still works for developers.
- The missing-feature message no longer shows Python quotes: `Missing feature: household_size.`
- 271 automated tests (5 added).

## 2 November 2026 (evening) — Lecturer feedback: duplicates, accounts, logs, analytics, SHAP

- **Address is the main duplicate control.** A second household at the same normalised address in the same village is refused unless staff record a reason (`shared_address_reason`, e.g. "backyard room 2"). The rule is in `Household.clean()`, so the web form and the API both apply it; the reason is audited and shown on the household page. Four relatives applying separately from one address create one household. Migration `households.0007` gives existing shared addresses a placeholder reason instead of blocking them.
- **Database check constraints** (`households.0007`): household size at least 1; dependents, and children plus elderly, within household size. Enforced even by bulk updates that skip `clean()`.
- **New accounts get a generated password.** The administrator enters username, name, e-mail and role; the system generates a one-time temporary password, shows it once with the username, stores only its hash and records an `account_created` event (`accounts.0005`). The user must choose their own password at first sign-in.
- **One place for account management.** The Users page now changes roles, deactivates/reactivates and resets passwords, with filters and last sign-in. The duplicate *Manage accounts* section was removed from the system report, which links to Users instead. Deactivation is explained as a block, not a deletion.
- **Audit logs.** Filters by action, user, household and date; page links keep the filters (also fixed on the dashboard and household list, which lost filters when paging); CSV download of the filtered entries; a second tab for sign-in and account events; a note on why the logs are kept.
- **Analyst tools.** Dashboard: every column heading sorts (server-side, whitelisted keys), ward filter, ward and size columns. Reports: category filter; risk by ward and by employment status (latest assessment per household, sortable); a download chooser for columns and rows (every assessment or latest per household). Address and phone are never offered.
- **SHAP clearly labelled.** `python manage.py explain_model` stores a model-wide summary (`global_explanation.json`: baseline and mean |SHAP| over the 2,000 held-out test records), bound to the model file's checksum. The report shows it labelled as describing the simulated-data model as evaluated; the requested-explanations table is labelled as a hand-picked subset. Each explanation shows the baseline, plain-English feature names and percentage points, and adds up to the score.
- **Model behaviour tests:** identical circumstances score the same in Kuruman and Cape Town (ward, village and province are not model inputs); scores are repeatable; baseline + SHAP values = score.
- 266 automated tests (44 added in this update).

## 2 November 2026 — Integrity, privacy and account hardening

- Duplicate prevention: identical households (normalised name, ward, village, contact) are refused by the model, form, API and database through a keyed hash, `identity_key` (migration `households.0005`). `check_duplicate_households` lists existing duplicates.
- Family-overlap warning: a shared phone number, a shared address in the same village, or the same name in the same village needs confirmation (`contact_key`, `address_key`, migration `households.0006`, which also merges spelling variants of wards and villages).
- Input limits (South African phone number, income, household size, distance), consistent ward and village spelling with suggestions, and an "Out of date" flag when a household's model inputs change after scoring.
- Household deletion is System Admin only; the analyst CSV is formula-safe; a repeat score within 30 seconds for unchanged data is not stored.
- Analysts no longer see a household's address or contact number (page and API).
- Passwords: self-service change, forced change for administrator-issued passwords (`must_change_password`, migrations `accounts.0003` and `0004`), administrator reset showing a temporary password once, 60-minute inactivity timeout.
- System Admin menu shows oversight pages only and lands on the system report.
- Fixed a defect present in the original project: every valid API update (PATCH/PUT) of a household was refused.
- Upgraded `cryptography` to 50.0.0 and `djangorestframework` to 3.18.2; `pip-audit` reports no known vulnerabilities.
- Household search also finds a household by exact phone number (any format) through the keyed `contact_key`; analysts cannot use it. Scores built on a blank (estimated) income now carry a notice on the prediction and household pages.
- 222 automated tests at that point (119 added). Diagrams refreshed.

## 21 October 2026 — Account security and analyst tools

- Added `AccountEvent` (migration `accounts.0002`): successful logins, failed logins, logouts, role changes and account activation/deactivation. Failed logins for unknown names are counted but their text is not stored; no passwords are stored; addresses appear on screen only.
- System administration report: sign-in and account-change counts, a repeated-failed-login warning (5 in 24 hours), a Manage accounts table (change role, activate/deactivate, return to the report) and a recent-events table. Downloads include the counts but no addresses.
- Role changes (`/accounts/users/<id>/role/`) and status changes are administrator-only POSTs with the existing self and superuser protections, and only same-site return addresses are followed.
- Analyst report: ward and date filters (invalid input rejected with HTTP 400), filtered CSV/PDF exports with a new Ward column, and a Model performance card read from the active model manifest.
- `seed_demo_data` now generates 250 demo households (option `--count`, `--reset`) from the held-out test rows only, with back-dated assessments, interventions, audit entries, some stored explanations and demo login activity. Demo data, not real households.
- Added 37 tests (103 in total). Updated ERD, use cases, classes, architecture and administrator sequence diagrams, and added an account security sequence diagram.
- Added `docs/DEMO_SCRIPT.md`, a demonstration script mapping each requirement to a demo step and a failure case.
- Still not implemented: automatic lockout, login history before installation, and the lecturer's real-data requirement.

## 20 October 2026 — Original data and administrator reports

- Restored the original 10,000-row simulated CSV unchanged; selected `simulated_rf_v2`, a new candidate on that dataset. Candidate v1 was an integration build before formatting; v2 records final training-source hashes.
- Preserved GHS artifacts and original-snapshot explanation support across both schemas.
- Added administrator-only account/system reports, date filters, browser print and PDF/CSV downloads. Existing report URLs route administrators to their system report; analysts retain food-risk reports.
- Added role, date, aggregation, export safety, original data and cross-schema regression tests. Updated data labels, setup/upgrade guidance, UML and the project report.
- Simulated metrics are explicitly separated from real-world validation; the lecturer’s real-data requirement remains unmet.

## 14 October 2026 — GHS real-data revision

- Replaced the active synthetic-data training path with unchanged GHS 2024 household/person public-use files and a documented binary past-food-shortage target.
- Introduced schema `ghs2024-food-access-v1`: seven defensible features, real coded missingness, roster-derived ages, train-only imputation and PSU group splits.
- Added immutable candidate manifests, source/code/artifact hashes, baseline and subgroup evaluation, approval recording and manual drift screening. Candidate training and runtime activation are separate.
- `ghs2024_rf_v1` and `ghs2024_rf_v2` were integration candidates. `ghs2024_rf_v3` is the packaged revision after formatting and final code review, with the same fixed modelling policy. Metrics are not tuned to the test set.
- Added province and nullable income, encrypted assessment snapshots, separate staff/admin explanation POST actions and caching on each prediction.
- Restricted dashboard/report aggregates to the configured model version. Historical predictions keep their original meaning and model labels.
- Updated UML, source documentation, report and tests. Real-data results do not meet the original accuracy targets; external NGO validation remains outstanding.

## Earlier release

`random_forest_v1` learned fabricated High/Low-or-Medium labels. Its metrics and scores are not comparable with the GHS proxy. Old stored explanations remain readable, but the old artifact/dataset are not shipped as active dependencies. Keep an independently archived previous release if historical research reproduction is required.
