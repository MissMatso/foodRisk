from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("reports/system/", views.SystemAdminReportView.as_view(), name="admin_report"),
    path(
        "reports/system/export/csv/",
        views.SystemAdminReportView.as_view(),
        {"output": "csv"},
        name="admin_export_csv",
    ),
    path(
        "reports/system/export/pdf/",
        views.SystemAdminReportView.as_view(),
        {"output": "pdf"},
        name="admin_export_pdf",
    ),
    path("reports/risk/", views.ReportsView.as_view(), name="risk_reports"),
    path("reports/risk/export/csv/", views.ExportCSVView.as_view(), name="risk_export_csv"),
    path("reports/risk/export/pdf/", views.ExportPDFView.as_view(), name="risk_export_pdf"),
    path("", views.RiskDashboardView.as_view(), name="risk_dashboard"),
    path("reports/", views.ReportsView.as_view(), name="reports"),
    path("reports/export/csv/", views.ExportCSVView.as_view(), name="export_csv"),
    path("reports/export/pdf/", views.ExportPDFView.as_view(), name="export_pdf"),
]
