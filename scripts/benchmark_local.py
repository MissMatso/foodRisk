"""Reproducible loopback HTTP benchmark with 1,000 fictitious household records.
Run on Linux/macOS: python scripts/benchmark_local.py --output docs/benchmark.json
Uses a temporary SQLite database and random secrets; leaves the real database untouched.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def summary(rows):
    times = sorted(r[0] for r in rows)
    return {
        "requests": len(rows),
        "errors": [r[1] for r in rows if r[1] not in (200, 201)],
        "median_seconds": statistics.median(times),
        "p95_seconds": times[int(0.95 * (len(times) - 1))],
        "max_seconds": max(times),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    from cryptography.fernet import Fernet

    with tempfile.TemporaryDirectory(prefix="foodrisk-benchmark-") as temp:
        os.environ.update(
            DJANGO_SETTINGS_MODULE="foodrisk_project.settings",
            DEBUG="True",
            DB_NAME="",
            SECURE_SSL_REDIRECT="False",
            FOODRISK_SQLITE_PATH=str(Path(temp) / "benchmark.sqlite3"),
            SECRET_KEY=secrets.token_hex(40),
            FIELD_ENCRYPTION_KEY=Fernet.generate_key().decode(),
            ALLOWED_HOSTS="127.0.0.1,localhost",
        )
        import django

        django.setup()
        from django.core.management import call_command
        from django.middleware.csrf import _get_new_csrf_string
        from django.test import Client
        from accounts.models import CustomUser
        from households.models import Household
        from ml_engine.train_simulated import load_dataframe

        call_command("migrate", verbosity=0)
        user = CustomUser.objects.create_user(username="benchmark", role="staff")
        df = load_dataframe()
        records = []
        for i, (_, row) in enumerate(df.iloc[:1000].iterrows()):
            records.append(
                Household(
                    name=f"Fictitious benchmark household {i}",
                    address="Fictitious address",
                    contact="0000000000",
                    monthly_income=None if row.monthly_income != row.monthly_income else row.monthly_income,
                    province="3",
                    household_size=int(row.household_size),
                    num_dependents=int(row.children_under_5 + row.elderly_members),
                    children_under_5=int(row.children_under_5),
                    elderly_members=int(row.elderly_members),
                    employment_status=row.employment_status,
                    has_disabled_member=bool(row.has_disabled_member),
                    has_chronic_illness=bool(row.has_chronic_illness),
                    land_ownership=bool(row.land_ownership),
                    distance_to_market_km=int(row.distance_to_market_km),
                    water_access=row.water_access,
                )
            )
        # Bulk setup is isolated benchmark fixture creation, never a supported user write path.
        Household.objects.bulk_create(records)
        client = Client()
        client.force_login(user)
        csrf = _get_new_csrf_string()
        cookies = f"sessionid={client.cookies['sessionid'].value}; csrftoken={csrf}"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        log = open(Path(temp) / "server.log", "w")
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "gunicorn",
                "foodrisk_project.wsgi:application",
                "--bind",
                f"127.0.0.1:{port}",
                "--workers",
                "1",
                "--threads",
                "4",
                "--timeout",
                "120",
            ],
            cwd=ROOT,
            env=os.environ.copy(),
            stdout=log,
            stderr=log,
        )
        try:
            for _ in range(100):
                try:
                    with urlopen(base + "/", timeout=1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Benchmark server failed to start")

            def request(path, method="POST"):
                start = time.perf_counter()
                req = Request(
                    base + path,
                    data=b"" if method == "POST" else None,
                    method=method,
                    headers={"Cookie": cookies, "X-CSRFToken": csrf, "Content-Type": "application/json"},
                )
                try:
                    with urlopen(req, timeout=60) as response:
                        status = response.status
                        body = response.read()
                except HTTPError as exc:
                    status, body = exc.code, exc.read()
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeError):
                    payload = {}
                return time.perf_counter() - start, status, payload

            cold = request("/api/households/1/predict/")
            with ThreadPoolExecutor(max_workers=4) as pool:
                warm = list(pool.map(lambda i: request(f"/api/households/{i + 2}/predict/"), range(80)))
                dashboard = list(pool.map(lambda _: request("/dashboard/", "GET"), range(20)))
            prediction_ids = [r[2]["id"] for r in warm if r[1] == 201]
            first_explanation = request(f"/api/predictions/{prediction_ids[0]}/explain/")
            with ThreadPoolExecutor(max_workers=4) as pool:
                explanations = list(
                    pool.map(lambda pk: request(f"/api/predictions/{pk}/explain/"), prediction_ids[1:21])
                )
                cached = list(
                    pool.map(lambda _: request(f"/api/predictions/{prediction_ids[0]}/explain/"), range(20))
                )
            report = {
                "model_version": __import__(
                    "django.conf", fromlist=["settings"]
                ).settings.FOODRISK_MODEL_VERSION,
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "scope": (
                    "Loopback HTTP; temporary SQLite; 1 Gunicorn worker, 4 threads, 4 "
                    "concurrent clients; 1,000 fictitious records with original simulated feature "
                    "distributions; DEBUG=True. Not production capacity or network evidence."
                ),
                "cold_score": summary([cold]),
                "warm_score": summary(warm),
                "dashboard": summary(dashboard),
                "cold_explanation": summary([first_explanation]),
                "warm_explanation": summary(explanations),
                "cached_explanation": summary(cached),
            }
            Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
        finally:
            server.terminate()
            server.wait(timeout=15)
            log.close()


if __name__ == "__main__":
    main()
