"""One administrator report snapshot shared by HTML, print, CSV and PDF."""

import csv
import io
from datetime import timedelta
from xml.sax.saxutils import escape

from django import forms
from django.conf import settings
from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone

from accounts.models import AccountEvent, CustomUser
from households.models import AuditLog, Household
from predictions.models import Intervention, Prediction

# A known account with this many failed logins in 24 hours is flagged for review.
FAILED_LOGIN_ALERT = 5


class ReportPeriodForm(forms.Form):
    date_from = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    date_to = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))

    def clean(self):
        data = super().clean()
        if data.get("date_from") and data.get("date_to") and data["date_from"] > data["date_to"]:
            raise forms.ValidationError("Start date must be on or before end date.")
        return data


def period_form(params):
    today = timezone.localdate()
    return ReportPeriodForm(
        {
            "date_from": params.get("date_from", (today - timedelta(days=29)).isoformat()),
            "date_to": params.get("date_to", today.isoformat()),
        }
    )


def _counts(queryset, field):
    return dict(queryset.order_by().values(field).annotate(total=Count("pk")).values_list(field, "total"))


def build_admin_report(start, end):
    now = timezone.now()
    today = timezone.localdate(now)
    users = list(CustomUser.objects.order_by("username", "pk"))
    households = Household.objects.filter(created_at__date__range=(start, end))
    predictions = Prediction.objects.filter(created_at__date__range=(start, end))
    interventions = Intervention.objects.filter(created_at__date__range=(start, end))
    audits = AuditLog.objects.filter(timestamp__date__range=(start, end))
    events = AccountEvent.objects.filter(timestamp__date__range=(start, end))
    event_totals = _counts(events, "event_type")
    repeated_failures = list(
        AccountEvent.objects.filter(
            event_type=AccountEvent.LOGIN_FAILED,
            user__isnull=False,
            timestamp__gte=now - timedelta(hours=24),
        )
        .order_by()
        .values("username")
        .annotate(total=Count("pk"))
        .filter(total__gte=FAILED_LOGIN_ALERT)
        .order_by("-total", "username")
    )
    registered = _counts(households, "registered_by_id")
    generated = _counts(predictions, "generated_by_id")
    actions = _counts(interventions, "created_by_id")
    active = sum(u.is_active for u in users)
    dormant = sum(
        u.is_active and (u.last_login is None or u.last_login < now - timedelta(days=90)) for u in users
    )
    roles = [
        {
            "label": label,
            "total": sum(u.role == role for u in users),
            "active": sum(u.role == role and u.is_active for u in users),
            "inactive": sum(u.role == role and not u.is_active for u in users),
        }
        for role, label in CustomUser.ROLE_CHOICES
    ]
    accounts = [
        {
            "pk": u.pk,
            "username": u.username,
            "role_code": u.role,
            "is_superuser": u.is_superuser,
            "role": u.get_role_display(),
            "active": u.is_active,
            "joined": u.date_joined,
            "last_login": u.last_login,
            "households": registered.get(u.pk, 0),
            "predictions": generated.get(u.pk, 0),
            "interventions": actions.get(u.pk, 0),
        }
        for u in users
    ]
    open_actions = Intervention.objects.filter(status="open")
    report = {
        "generated_at": now,
        "date_from": start,
        "date_to": end,
        "total_users": len(users),
        "active_users": active,
        "inactive_users": len(users) - active,
        "new_users": sum(start <= timezone.localdate(u.date_joined) <= end for u in users),
        "never_logged_in": sum(u.last_login is None for u in users),
        "temporary_password_users": sum(u.must_change_password and u.is_active for u in users),
        "dormant_active_users": dormant,
        "django_staff_users": sum(u.is_staff for u in users),
        "superusers": sum(u.is_superuser for u in users),
        "roles": roles,
        "accounts": accounts,
        "household_count": Household.objects.count(),
        "prediction_count": Prediction.objects.count(),
        "intervention_count": Intervention.objects.count(),
        "open_interventions": open_actions.count(),
        "completed_interventions": Intervention.objects.filter(status="completed").count(),
        "overdue_interventions": open_actions.filter(follow_up_date__lt=today).count(),
        "period_households": households.count(),
        "period_predictions": predictions.count(),
        "period_interventions": interventions.count(),
        "audit_count": audits.count(),
        "audit_actions": [
            {"label": label, "total": audits.filter(action=action).count()}
            for action, label in AuditLog.ACTION_CHOICES
        ],
        "login_success_count": event_totals.get(AccountEvent.LOGIN_SUCCESS, 0),
        "login_failed_count": event_totals.get(AccountEvent.LOGIN_FAILED, 0),
        "login_failed_unknown_count": events.filter(
            event_type=AccountEvent.LOGIN_FAILED, user__isnull=True
        ).count(),
        "role_change_count": event_totals.get(AccountEvent.ROLE_CHANGED, 0),
        "deactivation_count": event_totals.get(AccountEvent.ACCOUNT_DEACTIVATED, 0),
        "activation_count": event_totals.get(AccountEvent.ACCOUNT_ACTIVATED, 0),
        "repeated_failures": repeated_failures,
        "failed_login_alert": FAILED_LOGIN_ALERT,
        "recent_events": list(events.select_related("performed_by")[:10]),
        "unattributed_households": registered.get(None, 0),
        "unattributed_predictions": generated.get(None, 0),
        "unattributed_interventions": actions.get(None, 0),
        "model_version": settings.FOODRISK_MODEL_VERSION,
    }
    return report


def date_text(value):
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if value else "Never"


def report_sections(report):
    """Identical values/definitions for both downloads."""
    return [
        (
            "Current account totals",
            ["Metric", "Count"],
            [
                [label, report[key]]
                for label, key in [
                    ("Total users", "total_users"),
                    ("Active accounts", "active_users"),
                    ("Deactivated accounts", "inactive_users"),
                    ("Never logged in", "never_logged_in"),
                    ("Still on an administrator-issued password", "temporary_password_users"),
                    ("Active with no login in 90 days or ever", "dormant_active_users"),
                    ("Django staff flag", "django_staff_users"),
                    ("Superuser flag", "superusers"),
                ]
            ],
        ),
        (
            "Users by application role",
            ["Role", "Total", "Active", "Deactivated"],
            [[r["label"], r["total"], r["active"], r["inactive"]] for r in report["roles"]],
        ),
        (
            "Current system records",
            ["Metric", "Count"],
            [
                [label, report[key]]
                for label, key in [
                    ("Households", "household_count"),
                    ("Saved assessments all model versions", "prediction_count"),
                    ("Interventions", "intervention_count"),
                    ("Open interventions", "open_interventions"),
                    ("Completed interventions", "completed_interventions"),
                    ("Overdue open follow-ups", "overdue_interventions"),
                ]
            ],
        ),
        (
            "Activity in selected period",
            ["Metric", "Count"],
            [
                [label, report[key]]
                for label, key in [
                    ("New user registrations", "new_users"),
                    ("Household records created", "period_households"),
                    ("Assessments generated", "period_predictions"),
                    ("Interventions recorded", "period_interventions"),
                    ("Household audit events", "audit_count"),
                ]
            ]
            + [["Audit: " + r["label"], r["total"]] for r in report["audit_actions"]],
        ),
        (
            "Sign-in and account changes in selected period",
            ["Metric", "Count"],
            [
                [label, report[key]]
                for label, key in [
                    ("Successful logins", "login_success_count"),
                    ("Failed logins", "login_failed_count"),
                    ("Failed logins for names matching no account", "login_failed_unknown_count"),
                    ("Role changes", "role_change_count"),
                    ("Accounts deactivated", "deactivation_count"),
                    ("Accounts activated", "activation_count"),
                ]
            ],
        ),
        (
            f"Accounts with {report['failed_login_alert']}+ failed logins in the last 24 hours",
            ["Username", "Failed logins"],
            [[row["username"], row["total"]] for row in report["repeated_failures"]],
        ),
        (
            "Account roster and activity in selected period",
            [
                "Username",
                "Role",
                "Status",
                "Joined",
                "Last login",
                "Households",
                "Assessments",
                "Interventions",
            ],
            [
                [
                    u["username"],
                    u["role"],
                    "Active" if u["active"] else "Deactivated",
                    date_text(u["joined"]),
                    date_text(u["last_login"]),
                    u["households"],
                    u["predictions"],
                    u["interventions"],
                ]
                for u in report["accounts"]
            ],
        ),
        (
            "Period activity without a linked user",
            ["Households", "Assessments", "Interventions"],
            [
                [
                    report["unattributed_households"],
                    report["unattributed_predictions"],
                    report["unattributed_interventions"],
                ]
            ],
        ),
    ]


REPORT_NOTE = (
    "Account and system totals are current at generation time; the selected dates apply only to "
    "activity and new registrations. Active means the account is enabled, not currently online. "
    "Last login is the latest successful login. Sign-in and account-change counts come from the "
    "account event log, which records events only from the date it was installed; a failed login "
    "for a name that matches no account is counted but never named. Household audit events cover "
    "household changes only. Counts use retained records; deleted records may no longer be "
    "counted. Overdue means an open follow-up with a date before today. Repeated failed logins "
    "are a prompt to review an account, not proof of an attack. Model scores are not included in "
    "this administrative report."
)


def safe_csv(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def admin_csv(report):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="system_admin_report.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["FoodRisk System Administration Report"])
    writer.writerow(["Generated", date_text(report["generated_at"]), settings.TIME_ZONE])
    writer.writerow(["Activity period inclusive", report["date_from"], report["date_to"]])
    writer.writerow(["Configured model", report["model_version"]])
    for title, headers, rows in report_sections(report):
        writer.writerow([])
        writer.writerow([title])
        writer.writerow(headers)
        writer.writerows([[safe_csv(v) for v in row] for row in rows])
    writer.writerow([])
    writer.writerow([REPORT_NOTE])
    return response


def admin_pdf(report):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fonts = settings.BASE_DIR / "static" / "vendor"
    if "FoodRisk" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("FoodRisk", str(fonts / "font-0.ttf")))
        pdfmetrics.registerFont(TTFont("FoodRisk-Bold", str(fonts / "font-3.ttf")))
        pdfmetrics.registerFontFamily("FoodRisk", normal="FoodRisk", bold="FoodRisk-Bold")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=36
    )
    styles = getSampleStyleSheet()
    for name in ("Normal", "Title", "Heading2"):
        styles[name].fontName = "FoodRisk" if name == "Normal" else "FoodRisk-Bold"
    cell = ParagraphStyle("ReportCell", fontName="FoodRisk", fontSize=8, leading=11)
    header = ParagraphStyle("ReportHeader", parent=cell, textColor=colors.white, fontName="FoodRisk-Bold")
    elements = [
        Paragraph("FoodRisk System Administration Report", styles["Title"]),
        Paragraph(
            f"Generated {date_text(report['generated_at'])} ({settings.TIME_ZONE}). "
            f"Activity period {report['date_from']} to {report['date_to']} inclusive.",
            styles["Normal"],
        ),
        Paragraph("Configured model: " + escape(report["model_version"]), styles["Normal"]),
        Spacer(1, 12),
    ]
    for title, headers, rows in report_sections(report):
        data = [[Paragraph(escape(str(v)), header) for v in headers]]
        data += [[Paragraph(escape(str(v)), cell) for v in row] for row in rows]
        if not rows:
            data.append([Paragraph("No records", cell)] + [""] * (len(headers) - 1))
        widths = [150, 88, 70, 105, 105, 75, 80, 109] if len(headers) == 8 else None
        if widths:
            widths = [w * doc.width / sum(widths) for w in widths]
        else:
            widths = [doc.width / len(headers)] * len(headers)
        table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173347")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F4")]),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9D9D9")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        heading = Paragraph(title, styles["Heading2"])
        heading.keepWithNext = True
        elements.extend([heading, table, Spacer(1, 10)])
    elements.append(
        KeepTogether(
            [
                Paragraph("How to read this report", styles["Heading2"]),
                Paragraph(REPORT_NOTE, styles["Normal"]),
            ]
        )
    )

    def footer(canvas, document):
        canvas.setFont("FoodRisk", 8)
        canvas.drawString(30, 18, "FoodRisk | System administration | " + settings.TIME_ZONE)
        canvas.drawRightString(landscape(A4)[0] - 30, 18, f"Page {document.page}")

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="system_admin_report.pdf"'
    return response
