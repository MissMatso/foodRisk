from django.urls import path
from . import views

app_name = "predictions"

urlpatterns = [
    path("<int:pk>/explain/", views.ExplainPredictionView.as_view(), name="explain"),
    path("interventions/<int:pk>/edit/", views.InterventionUpdateView.as_view(), name="intervention_edit"),
    path("generate/<int:pk>/", views.GeneratePredictionView.as_view(), name="generate"),
    path("history/<int:pk>/", views.PredictionHistoryView.as_view(), name="history"),
    path("<int:pk>/", views.PredictionDetailView.as_view(), name="detail"),
    path("<int:pk>/intervention/", views.InterventionCreateView.as_view(), name="intervention"),
]
