# System administration report

The administrator's Reports navigation and legacy `/dashboard/reports/` route now open `/dashboard/reports/system/`. Analysts continue to receive food-risk analytics; staff retain the existing denial for aggregate reports. The admin can deliberately open food-risk analytics through a separate link.

All system report endpoints require an authenticated active administrator or superuser. Direct URL access is checked for the HTML, PDF and CSV paths. Deactivated accounts cannot authenticate.

## Contents and definitions

- Current users: total, enabled, deactivated and application role counts; Django staff and superuser flags are separate counts.
- Account review: never logged in, and enabled accounts whose last login is older than 90 days or absent. These counts do not trigger automatic deactivation.
- New registrations within the inclusive date range, defaulting to the last 30 calendar days.
- Current household, assessment and intervention totals across all model versions; open/completed interventions and overdue open follow-ups.
- Period activity: household creations, assessment generations, intervention creations and household audit events by action.
- Current account roster with username, role, status, joined date, latest login and each user's period activity counts. No passwords, email addresses, household names or contact information are exported.
- Period records without a linked user are counted separately. Deleted source records are not reconstructed.
- Sign-in and account changes in the period: successful logins, failed logins (and how many were for a name matching no account), role changes, accounts deactivated and activated. These come from the account event log (`AccountEvent`), which records events only from the day it was installed; earlier logins are not reconstructed. Household `AuditLog` still covers household changes only.
- Repeated failed logins: a known account with 5 or more failed logins in the last 24 hours triggers a warning on the page and a row in the downloads. This is a prompt to review the account, not proof of an attack, and nothing is locked automatically.

## Managing accounts from the report

The page (not the downloads) has a **Manage accounts** table. An administrator can change another account's application role or activate/deactivate it, then returns to the same report. The same rules as the user list apply: you cannot change your own account, only a superuser can change a superuser, and the role must be one of the three defined roles. Each change is written to the account event log with who made it and, for roles, the old and new role. The return address is only honoured if it is a page on this site.

The **Recent sign-in and account events** table shows up to ten events in the period, including the network address. Addresses and free-text details are on screen only; PDF and CSV contain counts, never addresses.

## Privacy of the event log

No password is ever stored. A failed login keeps the typed username only when it matches an existing account; a name that matches no account is stored blank (people sometimes type a password into the username box) and counted as "no matching account". The address recorded is the connecting address, because forwarding headers can be faked.

Current totals are measured when generated; only activity and new registrations use the selected dates. Active means enabled, not online. Last login is a single most recent timestamp. Overdue means open with follow_up_date before the current local date. Date filters reject malformed input and a start date after the end date with HTTP 400. Dates/times use Africa/Johannesburg.

## Print and downloads

The page provides Print report, Download PDF and Export CSV. PDF/CSV links carry the selected dates. Browser printing hides navigation and controls. Downloads share the same aggregation function and definitions as the page. Each request recomputes current totals, so genuine changes between requests may change results. PDF uses wrapping cells and repeated headers; CSV protects text beginning with spreadsheet formula characters.

| Path | Purpose |
|---|---|
| /dashboard/reports/system/ | Administrator page and browser print |
| /dashboard/reports/system/export/pdf/ | System report PDF |
| /dashboard/reports/system/export/csv/ | System report CSV |
| /dashboard/reports/risk/ | Separate food-risk analytics |
| /dashboard/reports/risk/export/pdf/ | Explicit prediction PDF |
| /dashboard/reports/risk/export/csv/ | Explicit prediction CSV |

Legacy `/dashboard/reports/export/pdf/` and `/csv/` choose the system report for administrators and prediction exports for analysts. Counts are derived from CustomUser, Household, Prediction, Intervention and AuditLog records plus the AccountEvent log. Role and status changes use `/accounts/users/<id>/role/` and `/accounts/users/<id>/status/` (POST, administrator only, CSRF protected).

## Analyst report filters, exports and model card

The analyst page at `/dashboard/reports/risk/` accepts a ward and an inclusive date range. Charts, the average-explanation table and both downloads use the same validated filter; malformed dates or a start after the end return HTTP 400. Download buttons carry the chosen filter and are labelled "(filtered)". Charts cover the configured model only, while downloads still include every model version with a version column (now also a Ward column).

The **Model performance** card reads the active model's recorded manifest; it recomputes nothing. It shows accuracy (derived from the confusion matrix), precision, recall, F1 and ROC AUC against the targets the manifest records, a confusion matrix, and a comparison with a majority-class baseline and logistic regression. It states the dataset type, that the model is not externally validated, and the manifest's limitation text. For the simulated model this measures agreement with generated labels only.

## Temporary passwords

An account whose password was chosen by someone else (created by an administrator, reset with **Reset password**, or changed for it in Django Admin) is flagged until its owner chooses their own password. The current totals include **Still on an administrator-issued password** (active accounts only), on the page, the PDF and the CSV. **Reset password** shows a random 12-character temporary password once, on the response page only; it is never stored readably, never written to the event log, and the account is signed out everywhere. The event log records who reset which account and when.
