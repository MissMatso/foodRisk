# Food Insecurity Risk Prediction System

Django academic prototype that estimates an indicative score from the original simulated household dataset, to support review and follow-up

---

## 1. Tech stack

| Layer | Choice |
|---|---|
| Backend | Django 6.1 (Python 3.12+) |
| API | Django REST Framework — `/api/households/`, `/api/predictions/` |
| Frontend | Django Templates + Bootstrap 5 + Chart.js |
| Database | SQLite (dev) / PostgreSQL (production) |
| ML | scikit-learn (Random Forest + Logistic Regression baseline), pandas, numpy, joblib |
| Explainability | On-demand TreeSHAP, persisted per prediction |
| Encryption at rest | django-encrypted-model-fields (AES via Fernet) on `address`, `contact`, `monthly_income`, `has_disabled_member`, `has_chronic_illness`, and prediction input snapshots |
| Audit trail | Django signals (`households/audit.py`) — logs the actor and changed field names without storing old/new values |
| Secrets | python-decouple (`.env`) |
| PDF/CSV export | reportlab, csv |
| CI | GitHub Actions — lint (flake8/black) → test (with coverage) → Docker build |

## 2. Quick start (under 10 minutes)

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env — see step 3 below for FIELD_ENCRYPTION_KEY

python manage.py migrate
python manage.py seed_demo_data   # demo users, 5 handwritten + 250 generated households with 6 months of history
                                  # options: --count 500 | --count 0 | --reset  (demo data, not real people)
python manage.py runserver
```

Visit http://127.0.0.1:8000/ to see the public landing page. Select **Staff sign in**
to log in, or visit `/dashboard/` after signing in.

### VS Code on Windows (PowerShell terminal)

Open the extracted `foodrisk_project` folder (the folder containing `manage.py`)
in VS Code, then run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
.\.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Paste the first generated value into `FIELD_ENCRYPTION_KEY` and the second
into `SECRET_KEY` in `.env`. Save the file, then run:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo_data
.\.venv\Scripts\python.exe manage.py runserver
```

The trained model is already included. In VS Code, select `.venv\Scripts\python.exe`
with **Python: Select Interpreter**. Do not put real household information in
the demo database.

| Username | Password | Role |
|---|---|---|
| `admin_demo` | `DemoPass123!` | System Admin |
| `staff_demo` | `DemoPass123!` | NGO Staff |
| `analyst_demo` | `DemoPass123!` | Data Analyst |

**Change these passwords (or delete the accounts) before any real deployment.**

### Page map

| Page | URL | Access |
|---|---|---|
| Landing | `/` | Public |
| How it works | `/how-it-works/` | Public |
| Model and limitations | `/model/` | Public |
| Sign in | `/accounts/login/` | Public |
| Risk dashboard | `/dashboard/` | Signed-in staff, analyst, admin |
| Household list and detail | `/households/`, `/households/<id>/` | Signed-in staff, analyst, admin |
| Register or edit a household | `/households/new/`, `/households/<id>/edit/` | Staff and admin |
| System report: accounts, sign-in security, role/status changes, print and exports | `/dashboard/reports/system/` | Admin only |
| Food-risk reports: ward/date filters, filtered exports, model performance | `/dashboard/reports/risk/` | Analyst and admin |
| Users and audit log | `/accounts/users/`, `/households/audit-log/` | Admin |

The Reports navigation chooses the administrator system report or analyst risk report by role. See [ADMIN_REPORT.md](docs/ADMIN_REPORT.md). For existing installations, follow [UPGRADE.md](docs/UPGRADE.md) and set `FOODRISK_MODEL_VERSION=simulated_rf_v2` while preserving your keys and database.

## 3. Configuration (`.env`)

Copy `.env.example` to `.env` and fill in real values. `FIELD_ENCRYPTION_KEY`
must be a valid Fernet key — generate one with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

For production, also set `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`,
`DB_PORT` to point at PostgreSQL — `settings.py` automatically switches
from SQLite to PostgreSQL when `DB_NAME` is set. Set `SECURE_SSL_REDIRECT=True`
and `DEBUG=False` behind HTTPS.

For an existing SQLite database, migration `0003` encrypts contact values
and removes historical audit field values. After a successful migration and
backup review, run SQLite `VACUUM` to reclaim pages containing old plaintext;
replace any old backups that retained those values. Keep the encryption key:
losing it makes encrypted household fields unreadable.

## 4. Project structure

```
foodrisk_project/
├── accounts/        # CustomUser (3 roles), RBAC mixins, login/register
├── households/       # Household CRUD + validation (FR002-FR004)
├── predictions/      # Prediction model, generate + history views (FR007-FR008)
├── dashboard/         # Risk dashboard, reports, CSV/PDF export (FR009)
├── ml_engine/           # train_model.py, predictor.py, DRF API, saved .joblib
├── templates/            # Bootstrap 5 templates
├── static/                # CSS
└── requirements.txt
```

The landing page lives at `templates/landing.html`, with its own stylesheet
at `static/css/landing.css`. Its artwork and sample dashboard preview are
stored in `static/img/`.

## 5. Restored original dataset and training

The active release uses the **original simulated 10,000-row CSV**, restored unchanged, with model `simulated_rf_v2`. This is a demonstration dataset with generated labels and no missing cells; it is not real NGO data and does not satisfy a real-data training requirement. No artificial missing values were introduced.

The twelve features and transformations are in [DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md). The target is simulated High versus Low-or-Medium. Train/validation/test sizes are 6,000/2,000/2,000, with training-only preprocessing and fixed binary threshold 0.5. The model is already included.

```bash
# Optional new simulated candidate; never overwrites or activates an existing model.
python manage.py train_model --model-version my_candidate_v1
# Explicit historical alternative, if needed:
python manage.py train_model --dataset ghs2024 --model-version my_ghs_candidate
```

| Metric | Original target | Simulated holdout result |
|---|---|---|
| F1 | >= 0.85 | 0.9414 |
| Precision | >= 0.80 | 0.9151 |
| Recall | >= 0.85 | 0.9693 |
| ROC AUC | >= 0.90 | 0.9873 |

Numeric targets are met **on generated labels only**, which is not evidence of real household accuracy. Scores are uncalibrated. Display bands are <=33 Low, <=66 Medium, otherwise High; these differ from the binary evaluation threshold. GHS data and models remain available for historical explanations and research reproduction. `DEBUG=False` still requires external validation and operational approval.

## 6. Prediction fallback behavior

- Missing required feature → `"Missing feature: <name>. Please update household data."`
- Model inference failure (including a detected scoring duration >5s) → `"Prediction unavailable."`

Model failures are logged without input snapshots. Missing required fields return a form-update message; unknown income is allowed and imputed. The elapsed-time guard is not a pre-emptive timeout.

## 7. Roles & access control

| Role | Can do |
|---|---|
| System Admin | Manage users (create, change role, activate/deactivate, reset password), system reports/print/exports, sign-in security events, household audit log, and the only role that may delete a household |
| NGO Staff | Register/edit households (and confirm a possible duplicate), generate scores/request explanations, record interventions, view dashboard/history |
| Data Analyst | View dashboard, reports, filtered CSV/PDF export, prediction history (read-only). Household address and contact number are not shown to analysts |

Enforced via `accounts/mixins.py` (`LoginRequiredMixin` + `UserPassesTestMixin`).
Unauthenticated users are redirected to login; authenticated users of the
wrong role get HTTP 403. The System Admin menu shows System report, Users and Audit Log, and an admin lands on the
system report after signing in; the case pages (Dashboard, Households and the registration form) are
hidden from admins, but their permissions are unchanged. Django's own admin site (`/admin/`) is
a developer tool and is not in the menu: accounts are managed on the Users page. A System Admin
deletes a household from its page (**Delete household**, reached from the Audit Log), after a
confirmation screen listing what will be removed.

## 7a. Audit trail

Every household create, edit, and delete is logged to `AuditLog` — who did
it, when, and (for edits) which field names changed, without old/new values. This closes the
"no audit trail" gap identified in Phase 1 and matches the `AuditLog`
entity in the Phase 2 ERD (`User`, `Household`, `Prediction`, `AuditLog`).

- Implemented as Django signals (`households/audit.py`), so it fires the
  same way regardless of whether the edit came from the web UI, the DRF
  API, or the Django admin.
- `AuditMiddleware` attributes each change to the logged-in user; direct
  script/shell edits log with `changed_by = None` ("system").
- System Admin only: **Audit Log** in the nav, or `/households/audit-log/`,
  filterable by action (created/updated/deleted). Each household's detail
  page also shows its 10 most recent changes.

## 7b. Sign-in security and account changes

Logins, failed logins, logouts, role changes and account activation/deactivation are recorded in `AccountEvent` (`accounts/signals.py`, `accounts/events.py`). It is separate from the household `AuditLog`.

- The System Admin report shows counts for the selected dates, a warning when one account has 5 or more failed logins in 24 hours, and recent account events; account changes are made on the Users page.
- No password is stored. A failed login for a name that matches no account is counted but its text is not stored. Network addresses are shown on screen only and are not in downloads.
- There is no automatic lockout, and events exist only from installation onward.
- For the local demo the research model is served only when `DEBUG=True` (the default in `.env.example`); with `DEBUG=False` the registry requires an approved, externally validated model.

## 7c. Data integrity

- **Duplicate households.** An identical household (same normalised name, ward, village and contact number) is refused by the model, the web form, the API and the database. Address and contact are encrypted, so the database enforces a keyed hash, `Household.identity_key` (`households/identity.py`); this also stops two simultaneous saves. Existing data: `python manage.py check_duplicate_households` lists possible duplicates by record number and name only.
- **One family under different names.** A new household that shares a phone number or an address (in the same village), or has the same name in the same village, shows a warning naming the match and its reason (never the number or address) and needs the user to confirm it is different. This uses two further keyed hashes, `contact_key` and `address_key`, and applies to the web form, not the API.
- **Input checks.** A contact must be a South African number; income is at most R500 000, household size at most 30 and distance at most 500 km.
- **Consistent places.** Ward and village are stored with the spelling already in use ("hantam " becomes "Hantam"); the form suggests existing places.
- **Out-of-date scores.** If a model input changes after a score was calculated (not just a name or phone number), the household page and the dashboard show an "Out of date" badge until a new score is generated.
- **One score per click.** A second score for unchanged data within 30 seconds is not stored.
- **Deleting a household** deletes its assessment history, so only a System Admin may do it, and it is audited.
- **Exports.** Analyst and administrator CSV values that start with `=`, `+`, `-` or `@` are neutralised so a household name cannot run as a spreadsheet formula.

## 7d. Passwords and sessions

- Any signed-in user can change their own password (menu: *Change password*); Django's password rules apply and the change is recorded without the password.
- A password chosen by someone else is temporary. Accounts created by an administrator (the system generates the temporary password and shows it once with the username; the administrator never types one), and accounts whose password an administrator resets (Users page, **Reset password**), must choose their own password at the next sign-in. Until then only the change-password pages and sign-out work and the API answers 403. The new password must differ from the temporary one. A reset shows a random temporary password once, never stores it, and signs the account out everywhere.
- Sessions end after 60 minutes of inactivity (`SESSION_IDLE_MINUTES` in `.env`).
- The demonstration accounts are not flagged, so a demonstration is not interrupted.

## 7e. Duplicates, logs and analyst tools (November 2026)

- **One household per address.** A second household at the same address in the same village is refused unless staff give a reason (a backyard room, a separate flat). Applies to the web form and the API.
- **Logs:** System Admin → **Audit Log** has two tabs (household changes; sign-ins and account changes), filters, paging that keeps the filters, and CSV downloads.
- **Analysts:** sort the dashboard by any column; see response coverage (high-risk households with and without a recorded action, open and overdue follow-ups) and risk by ward and by employment; choose the columns and rows of a download.
- **Two accounts at once:** a browser shares one sign-in across its tabs. Use a private window for the second account; the sign-in page says which account is signed in, and an expired form shows a plain "page expired" screen.
- **Model-wide SHAP:** after changing or retraining the model run `python manage.py explain_model` (about one minute) so the report's feature table matches the serving model. A summary computed for a different model file is never shown.

## 8. Running tests

```bash
python manage.py test
```

Covers: household validation (FR003), prediction fallback behavior (exact
error strings), role-based access control across all three roles, and the
audit trail (create/update/delete logging, correct attribution, and that
a no-op save does *not* create a spurious log entry).

For a coverage report:

```bash
pip install coverage
coverage run manage.py test && coverage report
```

## 9. API (bonus)

- `GET/POST /api/households/` — list/create households (staff/admin write access)
- `POST /api/households/{id}/predict/` — staff/admin only; run inference and store a prediction
- `POST /api/predictions/{id}/explain/` — staff/admin only; explain original inputs, preserve score on failure
- `GET /api/predictions/?household={id}` — read-only prediction history

Session-authenticated (log in via `/accounts/login/` first, or add a token
auth backend for a future mobile client).

## 10. Docker (bonus)

```bash
docker compose up --build
```

Runs a **local demo** with Django (Gunicorn) + PostgreSQL. See
`docker-compose.yml` and `Dockerfile`. Set demo secrets in `.env` first;
the compose file reads from it. Static-file serving must be configured for Gunicorn. A production deployment needs HTTPS termination and a
static file server/CDN, with `DEBUG=False` and unique secrets. The
container workflow has not been exercised in this workspace.

## 10a. CI (`.github/workflows/ci.yml`)

Runs on every push/PR to `main`/`develop`:

1. **lint** — `flake8` + `black --check`
2. **test** — installs `requirements.txt`, runs migrations, verifies the bundled model through tests, then
   `coverage run manage.py test` + `coverage report`. Also runs
   `manage.py check --deploy` informationally (non-blocking — flags
   dev-mode settings like `DEBUG=True` without failing the build over
   them).
3. **docker-build** — builds the image from `Dockerfile`, catching
   Dockerfile/dependency breakage before it reaches a real deploy.

`setup.cfg` and `pyproject.toml` hold the flake8/black/coverage config.

## 11. Known limitations and operation

- The active model uses simulated data. High synthetic holdout metrics do not establish real-world performance; real-data training and external NGO validation remain outstanding.
- Scores are uncalibrated; Low/Medium/High are indicative display bands. Staff must verify needs and apply organisational criteria before assistance decisions.
- Names, wards, villages and audit name snapshots remain readable. Key management, retention, backups and deployment need operational controls. Keep encryption keys safe; changing a key without migration makes existing encrypted fields unreadable.
- Explanations are optional, synchronous POST actions and cached per prediction. No background queue, automatic retraining, scheduled monitoring or automatic aid allocation is implemented.
- Existing pilot records receive Northern Cape as their province during migration. Verify this assumption for any household outside the original pilot. Old and new model scores must not be compared as the same outcome.
- There is no automatic account lockout. The account event log starts at installation, and repeated failed logins only raise a warning for an administrator to review.
- Passwords are checked for length, commonness, similarity to the username and all-numeric only; there is no account lockout, multi-factor sign-in or e-mail reset. Phone search is exact-match only (the number is encrypted, so partial matches are not possible).
- Duplicate and family-overlap checks work on normalised text and encrypted-then-hashed values: a mistyped number or a differently worded address is not matched, and the shared phone/name warning is on the web form only. The shared-address rule (a reason is required) applies to the web form and the API. Software can flag likely duplicates; staff verification still decides.
- There is no email-based password reset or password expiry, no household consent field, no API pagination or throttling, default error pages, and the audit log covers household records and account events only (not assessments or interventions). Two people editing one household at once: the last save wins.
- The local benchmark uses 1,000 fictitious households, four concurrent clients and one Gunicorn worker with four threads. It does not establish production performance, uptime or cross-browser support.

## October 2026 interface and documentation update

All public, sign-in and application pages share green/mint styling and Barlow typography. Bootstrap, Chart.js and fonts are bundled in `static/vendor` so these pages do not rely on CDN availability. The landing page has one sign-in action in its header.

Editable PlantUML diagrams, renders, a code-to-diagram traceability matrix and verification evidence are in `docs/`. See `docs/README.md` for the exact role matrix and workflow/error behaviour. The suite contains 283 passing tests. See docs/VERIFICATION.md for current evidence. New regression coverage checks API validation, partial updates, atomic audit writes, model-loading fallback and POST-only logout.

## Local concurrent benchmark (Linux/macOS)

```bash
python scripts/benchmark_local.py --output docs/benchmark_new.json
```

The script uses a temporary database and secrets, not your working records. On Windows, run it in WSL or a suitable test host; normal VS Code setup uses Django runserver as above.
#   f o o d R i s k 
 
 
