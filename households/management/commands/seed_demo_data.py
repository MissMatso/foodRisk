"""Seed demo users, households, predictions and login activity (Deliverables §11).

    python manage.py seed_demo_data                 # 5 handwritten + 250 generated households
    python manage.py seed_demo_data --count 500     # a bigger demo
    python manage.py seed_demo_data --count 0       # only the 5 handwritten households
    python manage.py seed_demo_data --reset         # wipe demo data first, then reseed

Generated households are sampled ONLY from the held-out test rows of the
simulated dataset (rows the model never trained on), then scored by the real
predictor. Assessment dates are spread over the last ~6 months so the reports
have a trend to show. THIS IS DEMO DATA, not real households.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import AccountEvent, CustomUser
from households.models import AuditLog, Household
from ml_engine.predictor import get_predictor
from ml_engine.train_simulated import load_dataframe, split_data
from predictions.models import Intervention, Prediction
from predictions.services import explain_prediction, save_prediction

DEMO_HOUSEHOLDS = [
    dict(
        name="Dlamini Household",
        address="12 Church St, Galeshewe, Kimberley",
        contact="0731234567",
        ward="ZF Mgcawu",
        village="Galeshewe",
        monthly_income=Decimal("1800.00"),
        household_size=6,
        num_dependents=4,
        employment_status="unemployed",
        has_disabled_member=False,
        has_chronic_illness=True,
        children_under_5=2,
        elderly_members=1,
        distance_to_market_km=35,
        water_access="communal",
        land_ownership=False,
    ),
    dict(
        name="Mokoena Household",
        address="45 Long St, Roodepan, Kimberley",
        contact="0739876543",
        ward="Pixley ka Seme",
        village="Roodepan",
        monthly_income=Decimal("6200.00"),
        household_size=3,
        num_dependents=1,
        employment_status="employed",
        has_disabled_member=False,
        has_chronic_illness=False,
        children_under_5=1,
        elderly_members=0,
        distance_to_market_km=4,
        water_access="piped",
        land_ownership=True,
    ),
    dict(
        name="Van Wyk Household",
        address="7 Jan Smuts Rd, Kimberley",
        contact="0745551122",
        ward="Namaqua",
        village="Kimberley",
        monthly_income=Decimal("3200.00"),
        household_size=5,
        num_dependents=3,
        employment_status="informal",
        has_disabled_member=True,
        has_chronic_illness=False,
        children_under_5=1,
        elderly_members=1,
        distance_to_market_km=18,
        water_access="borehole",
        land_ownership=False,
    ),
    dict(
        name="Seleke Household",
        address="89 Barkly Rd, Kimberley",
        contact="0721239988",
        ward="Hantam",
        village="Calvinia",
        monthly_income=Decimal("2400.00"),
        household_size=4,
        num_dependents=2,
        employment_status="grant_only",
        has_disabled_member=False,
        has_chronic_illness=True,
        children_under_5=2,
        elderly_members=0,
        distance_to_market_km=22,
        water_access="river",
        land_ownership=False,
    ),
    dict(
        name="Botha Household",
        address="3 Du Toitspan Rd, Kimberley",
        contact="0827773344",
        ward="John Taolo Gaetsewe",
        village="Hotazel",
        monthly_income=Decimal("4500.00"),
        household_size=2,
        num_dependents=1,
        employment_status="employed",
        has_disabled_member=False,
        has_chronic_illness=False,
        children_under_5=0,
        elderly_members=1,
        distance_to_market_km=6,
        water_access="piped",
        land_ownership=True,
    ),
]

DEMO_USERS = [
    dict(username="admin_demo", password="DemoPass123!", role="admin", is_staff=True, is_superuser=True),
    dict(username="staff_demo", password="DemoPass123!", role="staff"),
    dict(username="staff_demo2", password="DemoPass123!", role="staff"),
    dict(username="staff_demo3", password="DemoPass123!", role="staff"),
    dict(username="analyst_demo", password="DemoPass123!", role="analyst"),
]

DEMO_STAFF_USERNAMES = ["staff_demo", "staff_demo2", "staff_demo3"]

# Marks seeded login events so --reset removes exactly those.
DEMO_EVENT_TAG = "Demo data"
# 192.0.2.x and 198.51.100.x are reserved for documentation, so never real people.
DEMO_IPS = ["192.0.2.14", "192.0.2.77", "192.0.2.130", "198.51.100.23"]

SURNAMES = [
    "Dlamini", "Molefe", "Khumalo", "Mokoena", "Sithole", "Pretorius", "van Wyk", "Jacobs",
    "Botha", "Mahlangu", "Naidoo", "Tshabalala", "Lekota", "Fortuin", "Mabuza", "Baartman",
]  # fmt: skip
STREETS = ["Church St", "Main Rd", "Jakaranda Ave", "Mandela Dr", "Station Rd", "Karee St"]

# Which actions a case worker would plausibly record for each risk level.
ACTIONS_BY_CATEGORY = {
    "High": ["urgent_referral", "programme_referral"],
    "Medium": ["programme_referral", "information"],
}
# Share of generated assessments that get a stored explanation (explanations are on request).
EXPLAINED_SHARE = 0.1


class Command(BaseCommand):
    help = "Seeds demo users, households, risk predictions, interventions and login activity."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=250, help="Households to generate (default 250).")
        parser.add_argument("--reset", action="store_true", help="Delete previous demo data first.")
        parser.add_argument("--seed", type=int, default=42, help="Random seed, so runs are repeatable.")

    def handle(self, *args, **options):
        if options["reset"]:
            self.reset_demo_data()

        users = self.create_users()
        staff_users = [users[name] for name in DEMO_STAFF_USERNAMES]
        predictor = get_predictor()

        self.create_handwritten_households(predictor, users["staff_demo"])
        if options["count"] > 0:
            self.create_generated_households(predictor, staff_users, options["count"], options["seed"])
        self.create_login_activity(users, random.Random(options["seed"]))

        self.stdout.write(
            self.style.SUCCESS("\nDemo data seeding complete. (Demo data, not real households.)")
        )

    # ------------------------------------------------------------------ users
    def create_users(self):
        users = {}
        for original in DEMO_USERS:
            user_data = original.copy()  # copy, so the module-level list is never changed
            username = user_data.pop("username")
            password = user_data.pop("password")
            user, created = CustomUser.objects.get_or_create(username=username, defaults=user_data)
            if created:
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Created user: {username} / {password}"))
            users[username] = user
        return users

    # ------------------------------------------------------------------ reset
    def reset_demo_data(self):
        demo_staff = CustomUser.objects.filter(username__in=DEMO_STAFF_USERNAMES)
        removed = Household.objects.filter(registered_by__in=demo_staff).delete()[0]
        # Deleting households writes "delete" audit rows, so clear demo audit rows too.
        handwritten_names = [data["name"] for data in DEMO_HOUSEHOLDS]
        AuditLog.objects.filter(
            Q(changed_by__in=demo_staff)
            | Q(household_name__in=handwritten_names)
            | Q(household_name__contains=" #")
        ).delete()
        AccountEvent.objects.filter(detail=DEMO_EVENT_TAG).delete()
        self.stdout.write(f"Reset: removed demo records ({removed} rows including related data).")

    # ------------------------------------------------------- handwritten five
    def create_handwritten_households(self, predictor, staff_user):
        for data in DEMO_HOUSEHOLDS:
            household, created = Household.objects.get_or_create(
                name=data["name"], defaults={**data, "registered_by": staff_user}
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created household: {household.name}"))
            if household.predictions.exists():
                continue  # already assessed on an earlier run
            result = predictor.predict(household)
            if "error" in result:
                self.stdout.write(self.style.WARNING(f"  -> {result['error']}"))
                continue
            save_prediction(household, result, staff_user)
            self.stdout.write(f"  -> Risk: {result['score']}% ({result['category']})")

    # ------------------------------------------------------ generated demo set
    def heldout_rows(self):
        """Rows the model never trained on (the simulated 20% test split)."""
        test = split_data(load_dataframe())["test"]
        return test.to_dict("records")

    def create_generated_households(self, predictor, staff_users, count, seed):
        rng = random.Random(seed)
        already_there = Household.objects.filter(name__contains=" #").count()
        needed = count - already_there
        if needed <= 0:
            self.stdout.write(f"{already_there} generated households already exist; nothing to add.")
            return

        rows = self.heldout_rows()
        rng.shuffle(rows)
        created_total = predictions_total = interventions_total = 0

        with transaction.atomic():
            for row in rows:
                if created_total >= needed:
                    break
                attributes = self.attributes_from_row(row, already_there + created_total + 1, rng)
                if attributes is None:
                    continue  # row does not pass the Household validation rules
                registrar = rng.choice(staff_users)
                predicted, intervened = self.build_household_history(predictor, attributes, registrar, rng)
                created_total += 1
                predictions_total += predicted
                interventions_total += intervened

        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {created_total} households, {predictions_total} predictions, "
                f"{interventions_total} interventions (from held-out test rows)."
            )
        )

    def attributes_from_row(self, row, number, rng):
        """Turn one dataset row into Household field values (or None if invalid)."""
        size = int(row["household_size"])
        children = int(row["children_under_5"])
        elderly = int(row["elderly_members"])
        dependents = children + elderly  # the same definition the training data uses
        if dependents > size:
            return None
        village = row["village"]
        return dict(
            name=f"{rng.choice(SURNAMES)} Household #{number:03d}",
            address=f"{number} {rng.choice(STREETS)}, {village}",  # unique per household
            contact=f"07{rng.randint(10000000, 99999999)}",
            ward=row["ward"],
            village=village,
            monthly_income=Decimal(int(row["monthly_income"])),
            household_size=size,
            num_dependents=dependents,
            employment_status=row["employment_status"],
            has_disabled_member=bool(int(row["has_disabled_member"])),
            has_chronic_illness=bool(int(row["has_chronic_illness"])),
            children_under_5=children,
            elderly_members=elderly,
            distance_to_market_km=int(row["distance_to_market_km"]),
            water_access=row["water_access"],
            land_ownership=bool(int(row["land_ownership"])),
        )

    def build_household_history(self, predictor, attributes, registrar, rng):
        """Create one household with 1-3 back-dated assessments, plus follow-up."""
        now = timezone.now()
        first_day = now - timedelta(days=rng.randint(20, 180))

        household = Household.objects.create(registered_by=registrar, **attributes)
        # created_at is automatic, so back-date it (and its audit row) afterwards.
        Household.objects.filter(pk=household.pk).update(created_at=first_day)
        AuditLog.objects.filter(household=household, action=AuditLog.ACTION_CREATE).update(
            changed_by=registrar, timestamp=first_day
        )

        assessments = rng.choices([1, 2, 3], weights=[5, 3, 2])[0]
        gap = (now - timedelta(days=1) - first_day) / assessments
        predictions_made = interventions_made = 0

        for index in range(assessments):
            when = first_day + gap * index + timedelta(hours=1)
            if index > 0:
                self.change_household_circumstances(household, registrar, when, rng)

            result = predictor.predict(household)
            if "error" in result:
                continue
            prediction = save_prediction(household, result, registrar)
            Prediction.objects.filter(pk=prediction.pk).update(created_at=when)
            predictions_made += 1
            if rng.random() < EXPLAINED_SHARE:
                explain_prediction(prediction)
            interventions_made += self.maybe_create_intervention(prediction, registrar, when, rng)

        return predictions_made, interventions_made

    def change_household_circumstances(self, household, registrar, when, rng):
        """Simulate a later visit where income (and sometimes work) changed."""
        factor = Decimal(str(round(rng.uniform(0.6, 1.4), 2)))
        household.monthly_income = (household.monthly_income * factor).quantize(Decimal("1"))
        if rng.random() < 0.15:
            household.employment_status = rng.choice(["employed", "unemployed", "informal", "grant_only"])
        household.save()
        update_log = (
            AuditLog.objects.filter(household=household, action=AuditLog.ACTION_UPDATE)
            .order_by("-id")
            .first()
        )
        if update_log:
            AuditLog.objects.filter(pk=update_log.pk).update(changed_by=registrar, timestamp=when)

    def maybe_create_intervention(self, prediction, registrar, when, rng):
        actions = ACTIONS_BY_CATEGORY.get(prediction.category)
        chance = 0.7 if prediction.category == "High" else 0.35
        if not actions or rng.random() > chance:
            return 0
        follow_up = (when + timedelta(days=rng.randint(14, 45))).date()
        long_ago = follow_up < timezone.localdate() - timedelta(days=7)
        status = "completed" if long_ago and rng.random() < 0.85 else "open"
        intervention = Intervention.objects.create(
            prediction=prediction,
            action=rng.choice(actions),
            notes="Demo intervention.",
            follow_up_date=follow_up,
            status=status,
            created_by=registrar,
        )
        Intervention.objects.filter(pk=intervention.pk).update(created_at=when + timedelta(days=1))
        return 1

    # --------------------------------------------------------- login activity
    def create_login_activity(self, users, rng):
        """Back-dated logins and failed logins, so the admin report has security data."""
        if AccountEvent.objects.filter(detail=DEMO_EVENT_TAG).exists():
            return  # already seeded on an earlier run
        now = timezone.now()

        def add_event(event_type, username, when, ip, user=None, detail=""):
            event = AccountEvent.objects.create(
                event_type=event_type,
                username=username,
                user=user,
                ip_address=ip,
                detail=(f"{detail} " if detail else "") + DEMO_EVENT_TAG,
            )
            AccountEvent.objects.filter(pk=event.pk).update(timestamp=when)

        for username, user in users.items():
            if username == "staff_demo3":
                # One account that has not signed in for a long time.
                CustomUser.objects.filter(pk=user.pk).update(last_login=now - timedelta(days=75))
                continue
            last_login = None
            for _ in range(rng.randint(6, 10)):
                when = now - timedelta(days=rng.uniform(0.1, 30))
                add_event(AccountEvent.LOGIN_SUCCESS, username, when, rng.choice(DEMO_IPS[:3]), user)
                last_login = max(last_login, when) if last_login else when
            CustomUser.objects.filter(pk=user.pk).update(last_login=last_login)

        # A few ordinary typos over the last week...
        for username in ["analyst_demo", "staff_demo2", "staff_demo"]:
            when = now - timedelta(days=rng.uniform(0.5, 7))
            add_event(AccountEvent.LOGIN_FAILED, username, when, rng.choice(DEMO_IPS[:3]), users[username])
        when = now - timedelta(days=rng.uniform(0.5, 7))
        add_event(AccountEvent.LOGIN_FAILED, "", when, rng.choice(DEMO_IPS[:3]), detail="Unknown username")
        # ...and a burst against one account from one address, to show the warning.
        for minutes in range(6):
            when = now - timedelta(hours=3) + timedelta(minutes=minutes * 4)
            add_event(AccountEvent.LOGIN_FAILED, "admin_demo", when, DEMO_IPS[3], users["admin_demo"])
        self.stdout.write("Created demo login activity.")
