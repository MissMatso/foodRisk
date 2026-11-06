import csv
import io
import json

from django.conf import settings
from django.db.models import Count, F, OuterRef, Subquery
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views import View
from xml.sax.saxutils import escape
from django.views.generic import ListView, TemplateView

from accounts.roles import is_system_admin
from accounts.mixins import AdminRequiredMixin, AnalystRequiredMixin, StaffOrAnalystRequiredMixin
from predictions.services import inputs_changed_since
from households.models import Household
from predictions.models import Prediction
from .analytics import all_breakdowns, response_coverage
from .exports import ExportOptionsForm, describe_options, export_rows
from .model_card import build_model_card
from ml_engine.feature_labels import label as feature_label
from ml_engine.global_explanation import load as load_global_explanation
from .risk_filters import RiskFilterForm, apply_risk_filters, describe_filters, filter_query
from .admin_reports import period_form, build_admin_report, admin_csv, admin_pdf, REPORT_NOTE, safe_csv


def admin_report_redirect(request, name):
    response = redirect(name)
    if request.GET:
        response["Location"] += "?" + request.GET.urlencode()
    return response


def ward_choices():
    return Household.objects.exclude(ward="").values_list("ward", flat=True).distinct().order_by("ward")


def export_request(request):
    """Validated (headings, rows, description) for a download, or an HTTP 400 response.

    The filters (ward, category, dates) and the analyst's choice of columns and
    rows are read from the same GET parameters as the report page.
    """
    filters, options = RiskFilterForm(request.GET), ExportOptionsForm(request.GET)
    if not (filters.is_valid() and options.is_valid()):
        problems = sum(filters.errors.values(), []) + sum(options.errors.values(), [])
        return HttpResponseBadRequest("Invalid filter: " + "; ".join(problems))
    predictions = apply_risk_filters(
        Prediction.objects.select_related("household").order_by("-created_at"), filters.cleaned_data
    )
    headings, rows = export_rows(predictions, options)
    description = f"{describe_filters(filters.cleaned_data)}. {describe_options(options)}"
    return headings, rows, description


class SystemAdminReportView(AdminRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        form = period_form(request.GET)
        if not form.is_valid():
            return render(request, "dashboard/admin_report.html", {"period_form": form}, status=400)
        report = build_admin_report(form.cleaned_data["date_from"], form.cleaned_data["date_to"])
        output = kwargs.get("output")
        if output == "csv":
            return admin_csv(report)
        if output == "pdf":
            return admin_pdf(report)
        return render(
            request,
            "dashboard/admin_report.html",
            {
                "period_form": form,
                "report": report,
                "report_note": REPORT_NOTE,
            },
        )


class RiskDashboardView(StaffOrAnalystRequiredMixin, ListView):
    """Risk dashboard — FR009. Households with their latest score, highest risk first by default.

    Filters: category, employment status, ward and assessment date. Every column
    heading is a sort button (?sort=name, ?sort=-score, ...). Only the sort keys
    in SORTS are accepted, so the address cannot be used to order by anything else.
    """

    template_name = "dashboard/risk_dashboard.html"
    context_object_name = "households"
    paginate_by = 25
    SORTS = {
        "score": "latest_score",
        "name": "name",
        "ward": "ward",
        "employment": "employment_status",
        "size": "household_size",
        "date": "latest_date",
    }
    TEXT_SORTS = {"name", "ward", "employment"}
    COLUMNS = [
        ("name", "Household"),
        ("ward", "Ward"),
        ("employment", "Employment"),
        ("size", "Size"),
        ("score", "Latest score"),
        (None, "Category"),
        ("date", "Last assessed"),
        (None, ""),
    ]
    DEFAULT_SORT = "-score"

    def sort_key(self):
        requested = self.request.GET.get("sort", self.DEFAULT_SORT)
        return requested if requested.lstrip("-") in self.SORTS else self.DEFAULT_SORT

    def get_queryset(self):
        latest = Prediction.objects.filter(
            household=OuterRef("pk"), model_version=settings.FOODRISK_MODEL_VERSION
        ).order_by("-created_at")
        qs = Household.objects.annotate(
            latest_score=Subquery(latest.values("score")[:1]),
            latest_category=Subquery(latest.values("category")[:1]),
            latest_date=Subquery(latest.values("created_at")[:1]),
        )

        category = self.request.GET.get("category")
        employment = self.request.GET.get("employment_status")
        ward = self.request.GET.get("ward")
        date_from = self.request.GET.get("date_from")
        date_to = self.request.GET.get("date_to")

        if category:
            qs = qs.filter(latest_category=category)
        if employment:
            qs = qs.filter(employment_status=employment)
        if ward:
            qs = qs.filter(ward=ward)
        if date_from:
            qs = qs.filter(latest_date__date__gte=date_from)
        if date_to:
            qs = qs.filter(latest_date__date__lte=date_to)

        key = self.sort_key()
        column = F(self.SORTS[key.lstrip("-")])
        # Households never scored go last whichever way the list is sorted; name breaks ties.
        order = column.desc(nulls_last=True) if key.startswith("-") else column.asc(nulls_last=True)
        return qs.order_by(order, "name", "pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["model_version"] = settings.FOODRISK_MODEL_VERSION
        context["category_choices"] = Prediction.CATEGORY_CHOICES
        context["employment_choices"] = Household.EMPLOYMENT_CHOICES
        context["selected_category"] = self.request.GET.get("category", "")
        context["selected_employment"] = self.request.GET.get("employment_status", "")
        context["date_from"] = self.request.GET.get("date_from", "")
        context["date_to"] = self.request.GET.get("date_to", "")
        context["wards"] = ward_choices()
        context["selected_ward"] = self.request.GET.get("ward", "")
        sort = self.sort_key()
        context["sort"] = sort
        # One entry per table column, in display order. Sortable ones carry the sort their heading applies
        # and their current direction. First click: A-Z for text columns, highest first for numbers.
        context["columns"] = []
        for key, heading in self.COLUMNS:
            column = {"label": heading, "key": key}
            if key:
                first = key if key in self.TEXT_SORTS else "-" + key
                column["direction"] = (
                    "descending" if sort == "-" + key else "ascending" if sort == key else ""
                )
                flipped = key if sort == "-" + key else "-" + key
                column["next"] = flipped if column["direction"] else first
            context["columns"].append(column)
        self.mark_out_of_date(context["households"])
        return context

    @staticmethod
    def mark_out_of_date(households):
        """Flag rows whose household data changed after the score shown was calculated."""
        households = list(households)
        latest = {}
        for prediction in Prediction.objects.filter(
            household__in=households, model_version=settings.FOODRISK_MODEL_VERSION
        ).order_by("created_at"):
            latest[prediction.household_id] = prediction  # the newest wins
        for household in households:
            prediction = latest.get(household.pk)
            household.out_of_date = prediction is not None and inputs_changed_since(prediction, household)


class ReportsView(AnalystRequiredMixin, TemplateView):
    """Reports module — Data Analyst only.

    Operational analytics first (assessment charts, response coverage, risk by
    ward and employment, downloads), then "About the model": the recorded
    performance card and the model-wide SHAP summary.
    """

    template_name = "dashboard/reports.html"

    def get(self, request, *args, **kwargs):
        if is_system_admin(request.user) and request.resolver_match.url_name == "reports":
            return admin_report_redirect(request, "dashboard:admin_report")
        self.filter_form = RiskFilterForm(request.GET)
        if not self.filter_form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "filter_form": self.filter_form,
                    "model_version": settings.FOODRISK_MODEL_VERSION,
                    "wards": ward_choices(),
                },
                status=400,
            )
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["model_version"] = settings.FOODRISK_MODEL_VERSION
        filters = self.filter_form.cleaned_data
        context["filter_form"] = self.filter_form
        context["wards"] = ward_choices()
        context["filter_query"] = filter_query(filters)
        context["export_form"] = ExportOptionsForm()
        context["model_card"] = build_model_card()
        current = apply_risk_filters(
            Prediction.objects.filter(model_version=settings.FOODRISK_MODEL_VERSION), filters
        )
        context["breakdowns"] = all_breakdowns(current)
        context["breakdown_tables"] = [
            ("Ward", context["breakdowns"]["ward"]),
            ("Employment status", context["breakdowns"]["employment"]),
        ]
        context["filter_description"] = describe_filters(filters)
        category_counts = current.values("category").annotate(total=Count("id")).order_by("category")
        context["category_counts"] = json.dumps(list(category_counts))

        # Trend: count of predictions per category per month (simple, DB-agnostic).
        predictions = current.order_by("created_at")
        trend = {}
        for p in predictions:
            key = p.created_at.strftime("%Y-%m")
            trend.setdefault(key, {"Low": 0, "Medium": 0, "High": 0})
            trend[key][p.category] += 1
        context["trend_labels"] = json.dumps(list(trend.keys()))
        context["trend_low"] = json.dumps([v["Low"] for v in trend.values()])
        context["trend_medium"] = json.dumps([v["Medium"] for v in trend.values()])
        context["trend_high"] = json.dumps([v["High"] for v in trend.values()])

        context["prediction_count"] = predictions.count()
        context["coverage"] = response_coverage(current)
        summary = load_global_explanation(settings.FOODRISK_MODEL_VERSION)
        if summary:
            context["global_explanation"] = {
                "records": summary["records"],
                "baseline_percent": round(summary["baseline_probability"] * 100, 1),
                "rows": [
                    {
                        "label": feature_label(name),
                        "points": round(value * 100, 1),
                        "signed_points": round(summary["mean_shap"][name] * 100, 1),
                        "share": round(100 * value / sum(summary["mean_absolute_shap"].values()), 1),
                    }
                    for name, value in summary["mean_absolute_shap"].items()
                ],
            }
        return context


class ExportCSVView(AnalystRequiredMixin, View):
    """Export prediction data as CSV (Data Analyst only), with the columns and rows the analyst chose."""

    def get(self, request, *args, **kwargs):
        if is_system_admin(request.user) and request.resolver_match.url_name == "export_csv":
            return admin_report_redirect(request, "dashboard:admin_export_csv")
        result = export_request(request)
        if isinstance(result, HttpResponse):
            return result
        headings, rows, _description = result
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="predictions_report.csv"'
        writer = csv.writer(response)
        writer.writerow(headings)
        for row in rows:
            # safe_csv: a name such as =HYPERLINK(...) must not run as a formula when opened in Excel
            writer.writerow([safe_csv(value) for value in row])
        return response


class ExportPDFView(AnalystRequiredMixin, View):
    """Export prediction data as PDF (Data Analyst only), using reportlab."""

    def get(self, request, *args, **kwargs):
        if is_system_admin(request.user) and request.resolver_match.url_name == "export_pdf":
            return admin_report_redirect(request, "dashboard:admin_export_pdf")
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

        result = export_request(request)
        if isinstance(result, HttpResponse):
            return result
        headings, rows, description = result

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4) if len(headings) > 6 else A4)
        styles = getSampleStyleSheet()
        elements = [
            Paragraph("Food Insecurity Risk — Prediction Report", styles["Title"]),
            # escape(): a ward name containing & or < must not break the PDF markup
            Paragraph(escape(f"{description} ({len(rows)} rows)"), styles["Normal"]),
        ]
        cells = [headings] + [
            [value.strftime("%Y-%m-%d %H:%M") if hasattr(value, "strftime") else str(value) for value in row]
            for row in rows
        ]
        table = Table(cells, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f6b4f")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                ]
            )
        )
        elements.append(table)
        doc.build(elements)

        buffer.seek(0)
        response = HttpResponse(buffer, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="predictions_report.pdf"'
        return response
