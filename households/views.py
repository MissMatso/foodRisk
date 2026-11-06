import csv
from urllib.parse import urlencode

from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Q
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from accounts.mixins import AdminRequiredMixin, StaffOrAnalystRequiredMixin, StaffRequiredMixin
from accounts.models import AccountEvent
from accounts.roles import sees_personal_details
from dashboard.admin_reports import safe_csv
from .audit_filters import AccountEventFilterForm, HouseholdAuditFilterForm
from predictions.services import inputs_changed_since
from .forms import HouseholdForm
from .identity import contact_key, is_valid_contact
from .locations import known_villages, known_wards
from .models import AuditLog, Household


class HouseholdListView(StaffOrAnalystRequiredMixin, ListView):
    """Staff + Analyst — browse registered households."""

    model = Household
    template_name = "households/household_list.html"
    context_object_name = "households"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset()
        query = self.request.GET.get("q")
        if query:
            match = Q(name__icontains=query)
            # Phone numbers are encrypted, so look them up through the keyed hash instead.
            # Analysts never see contact details, so they must not be able to probe for them either.
            if sees_personal_details(self.request.user) and is_valid_contact(query):
                match |= Q(contact_key=contact_key(query))
            qs = qs.filter(match)
        return qs


class HouseholdDetailView(StaffOrAnalystRequiredMixin, DetailView):
    """Staff + Analyst — view household + prediction history (FR008)."""

    model = Household
    template_name = "households/household_detail.html"
    context_object_name = "household"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["predictions"] = self.object.predictions.all()
        context["audit_logs"] = self.object.audit_logs.all()[:10]
        # Analysts work with scores and trends; they do not need a household's address or phone number.
        context["show_personal_details"] = sees_personal_details(self.request.user)
        latest = self.object.latest_prediction
        context["latest_out_of_date"] = latest is not None and inputs_changed_since(latest, self.object)
        return context


class HouseholdCreateView(StaffRequiredMixin, CreateView):
    """NGO Staff only — Register Household (FR002)."""

    model = Household
    form_class = HouseholdForm
    template_name = "households/household_form.html"
    success_url = reverse_lazy("households:household_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["ward_options"], context["village_options"] = known_wards(), known_villages()
        return context

    def form_valid(self, form):
        form.instance.registered_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, f"Household '{self.object.name}' registered successfully.")
        return response


class HouseholdUpdateView(StaffRequiredMixin, UpdateView):
    """NGO Staff only — edit household details."""

    model = Household
    form_class = HouseholdForm
    template_name = "households/household_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["ward_options"], context["village_options"] = known_wards(), known_villages()
        return context

    def get_success_url(self):
        return reverse_lazy("households:household_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Household '{self.object.name}' updated successfully.")
        return response


class HouseholdDeleteView(AdminRequiredMixin, DeleteView):
    """System Admin only — delete a household and its whole assessment history (BR-12).

    GET shows what will be removed; only the POST from that page deletes. The
    post_delete signal writes the audit entry with the administrator's name, and
    the administrator lands on the audit log filtered to this household.
    """

    model = Household
    template_name = "households/household_confirm_delete.html"
    context_object_name = "household"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        predictions = self.object.predictions.all()
        context["prediction_count"] = predictions.count()
        context["intervention_count"] = sum(p.interventions.count() for p in predictions)
        return context

    def form_valid(self, form):
        name = self.object.name
        response = super().form_valid(form)
        messages.success(
            self.request,
            f"Household '{name}' and its assessment history were deleted. The deletion is in the audit log.",
        )
        return response

    def get_success_url(self):
        query = urlencode({"action": AuditLog.ACTION_DELETE, "household": self.object.name})
        return reverse("households:audit_log") + "?" + query


class _FilteredLogView(AdminRequiredMixin, ListView):
    """A filtered, paginated log page that can also be downloaded as CSV (System Admin only).

    Subclasses set the model, filter form and CSV columns. Invalid filters return
    HTTP 400 with the form errors instead of silently showing everything.
    """

    paginate_by = 50
    filter_form_class = None
    csv_name = "log.csv"

    def get(self, request, *args, **kwargs):
        self.filter_form = self.filter_form_class(request.GET or None)
        if request.GET and not self.filter_form.is_valid():
            self.object_list = self.model.objects.none()
            return self.render_to_response(self.get_context_data(), status=400)
        if kwargs.get("output") == "csv":
            return self.download(self.get_queryset())
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        rows = self.base_queryset()
        if self.filter_form.is_bound:
            rows = self.filter_form.apply(rows)
        return rows

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["filter_query"] = self.request.GET.urlencode()
        return context

    def download(self, rows):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.csv_name}"'
        writer = csv.writer(response)
        writer.writerow(self.csv_header)
        for row in rows:
            writer.writerow([safe_csv(value) for value in self.csv_row(row)])
        return response


class AuditLogListView(_FilteredLogView):
    """Household audit trail — who created, edited or deleted which household, and when.

    Only the NAMES of changed fields are kept, never old or new values, so the
    log is not a second copy of personal information.
    """

    model = AuditLog
    template_name = "households/audit_log_list.html"
    context_object_name = "logs"
    filter_form_class = HouseholdAuditFilterForm
    csv_name = "household_audit_log.csv"
    csv_header = ["When", "Household", "Action", "Changed by", "Fields changed"]

    def base_queryset(self):
        return AuditLog.objects.select_related("changed_by", "household")

    def csv_row(self, log):
        return [
            log.timestamp.strftime("%Y-%m-%d %H:%M"),
            log.household_name,
            log.get_action_display(),
            log.changed_by.username if log.changed_by else "system",
            ", ".join((log.changes or {}).get("fields_changed", [])),
        ]


class AccountEventListView(_FilteredLogView):
    """Account event log — sign-ins, failed sign-ins and every account change by an administrator.

    Network addresses are shown on the page but left out of the download.
    """

    model = AccountEvent
    template_name = "households/account_event_list.html"
    context_object_name = "events"
    filter_form_class = AccountEventFilterForm
    csv_name = "account_events.csv"
    csv_header = ["When", "Event", "Account", "Changed by", "Detail"]

    def base_queryset(self):
        return AccountEvent.objects.select_related("performed_by")

    def csv_row(self, event):
        return [
            event.timestamp.strftime("%Y-%m-%d %H:%M"),
            event.get_event_type_display(),
            event.username or "(no matching account)",
            event.performed_by.username if event.performed_by else "",
            event.detail,
        ]
