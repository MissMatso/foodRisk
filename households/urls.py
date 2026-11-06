from django.urls import path
from . import views

app_name = "households"

urlpatterns = [
    path("", views.HouseholdListView.as_view(), name="household_list"),
    path("new/", views.HouseholdCreateView.as_view(), name="household_create"),
    path("audit-log/", views.AuditLogListView.as_view(), name="audit_log"),
    path("audit-log/export/csv/", views.AuditLogListView.as_view(), {"output": "csv"}, name="audit_log_csv"),
    path("audit-log/accounts/", views.AccountEventListView.as_view(), name="account_events"),
    path(
        "audit-log/accounts/export/csv/",
        views.AccountEventListView.as_view(),
        {"output": "csv"},
        name="account_events_csv",
    ),
    path("<int:pk>/", views.HouseholdDetailView.as_view(), name="household_detail"),
    path("<int:pk>/edit/", views.HouseholdUpdateView.as_view(), name="household_update"),
    path("<int:pk>/delete/", views.HouseholdDeleteView.as_view(), name="household_delete"),
]
