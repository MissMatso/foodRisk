# Updating an existing installation

1. Stop the server and back up your existing project, `.env` and database.
2. Extract the new project into a separate folder. Install `requirements.txt` in its virtual environment.
3. Keep your existing `.env` keys and existing database together. Do not generate a replacement encryption key for existing encrypted records. The release ZIP intentionally contains neither `.env` nor a database.
4. Set `FOODRISK_MODEL_VERSION=simulated_rf_v2` in your existing `.env`; keep `DEBUG=True` for the local demonstration. A previously configured GHS version otherwise remains selected.
5. Run `python manage.py migrate`, then `python manage.py runserver`. The model is bundled; training is optional. Skip `seed_demo_data` for an existing working database unless you want demonstration accounts/records.
6. Sign in as a system administrator and choose System report. Analysts use Risk reports.

No data reset is required. Previous assessments retain their version and score. The dashboard shows the configured version only, so a household with only older assessments needs a new staff-requested assessment before a score appears there. Historical GHS explanations still use their seven original features; active simulated explanations use twelve. All retained model artifacts must remain available for historical explanations.

For a fresh installation use the Windows/VS Code setup in README.md. The administrator demonstration account is admin_demo / DemoPass123!; it is for local demonstrations only.
