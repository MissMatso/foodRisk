# FoodRisk implementation documentation

Revision: 2 November 2026. The diagrams describe this packaged build. Editable PlantUML and matching PNG files are in `diagrams/`. Render with Java: `java -jar plantuml.jar -tpng docs/diagrams/*.puml`. Smetana is used for graph layouts; Graphviz is not required.

## Diagram traceability

| Diagram | Source of truth | Interpretation |
|---|---|---|
| Context | urls.py, predictor.py, registry.py | One Django application and a local versioned model; no automatic aid allocation |
| Use cases | accounts/mixins.py, views, api_views.py | Staff/admin writes and explanation requests; analysts inspect, filter and export results and see model performance; admins manage accounts and review sign-in security |
| Registration activity/sequence | households/forms.py, models.py, audit.py, views.py | Household and audit writes are atomic; registration does not predict |
| Prediction activity/sequence | predictions/views.py, services.py, ml_engine/predictor.py | Score first, no SHAP; save encrypted inputs/hash/schema; errors save no result |
| Explanation sequence | predictions/services.py, ml_engine/predictor.py, registry.py | Original inputs/version; cached explanations; failures preserve score |
| Classes | Domain models, forms, serializer, predictor | Selected members; seven domain foreign-key associations plus two on AccountEvent; shared persistence service |
| ERD | accounts/models.py, households/models.py, predictions/models.py | Five domain entities and seven foreign keys, plus AccountEvent with two foreign keys (nine in total); province, nullable income and snapshot fields |
| Architecture | App settings, predictor, registry, services, training/monitoring commands | Single application with file-based registry; no model-registry database table or queue; auth signals write AccountEvent; the model card reads manifests read-only |
| Deployment | settings.py, wsgi.py, README.md | Local SQLite; PostgreSQL configured; external production deployment unverified |
| Intervention activity/sequence/state | predictions/forms.py, models.py, views.py | Staff action and optional date; open/completed; editable and reopenable |

| Administrator report sequence | dashboard/admin_reports.py, dashboard/views.py | Admin check before aggregation; validated dates; common HTML/PDF/CSV values; reads the account event log |
| Registration duplicate checks (register activity/sequence) | households/identity.py, forms.py, models.py | Hard rule refuses an identical household; a second household at the same address in the same village needs a recorded reason (form and API); same name or phone number needs confirmation; database key stops simultaneous duplicates. Renders include the shared-address reason |
| Temporary password sequence | accounts/middleware.py, views.py, forms.py | Account creation and reset both generate a temporary password shown once; flagged users reach only the change-password pages; the new password must differ |
| Account security sequence | accounts/signals.py, events.py, views.py | Login, failed login and logout events; admin role/status change with self, superuser and same-site return checks; no password or unknown-name text stored |

Household deletion cascades predictions, and prediction deletion cascades interventions. Nullable attribution and household-audit links use SET_NULL. Model files have no database foreign key; retain versions required by saved prediction snapshots.

## Roles

| Action | Staff | Analyst | Admin |
|---|---|---|---|
| Browse households, current-version dashboard, history/detail | Yes | Yes | Yes |
| Create/edit households, score and request explanation | Yes | No | Yes |
| Record/update interventions | Yes | No | Yes |
| Delete household (household page or API), with confirmation | No | No | Yes |
| See a household's address and contact number | Yes | No | Yes |
| Change own password | Yes | Yes | Yes |
| Reset another account's password | No | No | Yes |
| Menu shows Dashboard and Households (staff register from the Households page) | Yes | Yes | Hidden (permission unchanged) |
| Food-risk analytics, response coverage, sortable dashboard, chosen-column exports | No | Yes | Yes, separate link |
| System administration report, print and exports | No | No | Yes |
| User management (Users page only): create, role, deactivate/reactivate, reset | No | No | Yes |
| Audit logs (household changes and account events), filters and CSV | No | No | Yes |

Superusers bypass application role checks. Django admin additionally uses `is_staff` and model permissions. The application staff role does not confer Django administration rights. API reads require a session; all session writes require CSRF. Deactivated accounts cannot authenticate. Current-version aggregates avoid mixing old synthetic and GHS outcome scores; history and exports retain model labels.

## Evidence and limits

See `VERIFICATION.md`, `benchmark.json`, `DATA_DICTIONARY.md`, `MODEL_GOVERNANCE.md` and `CHANGELOG.md`. The source metadata/questionnaire, real survey files and versioned model manifests are bundled. The original simulated CSV and a new simulated candidate are active. GHS artifacts remain available for historical explanations. Old screenshots remain retired. Earlier records remain in an existing user's database; migrations do not delete their history.

The simulated model meets numeric targets on generated labels only; real-data and external validation requirements remain unmet. The local concurrency benchmark is not production evidence. The five-second scoring guard detects elapsed time after work completes and excludes loading. Bulk database updates bypass validation/audit signals. Household identity/location and audit name snapshots remain readable; operational privacy, key handling, external NGO validation, cross-browser usability and deployment controls remain open.

See `ADMIN_REPORT.md` for report definitions and `UPGRADE.md` for existing installations.

## Presentation

`DEMO_SCRIPT.md` is the step-by-step script for the final demonstration: set-up checklist, the main workflow, a requirement-by-requirement check table, ready failure cases and answers to likely questions. It contains one bracketed prompt the presenter must complete in their own words (why the real-data attempt was set aside).
