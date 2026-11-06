from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import TemplateView


def health_check(request):
    """Simple health-check endpoint (NFR007)."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("", TemplateView.as_view(template_name="landing.html"), name="home"),
    path("how-it-works/", TemplateView.as_view(template_name="how_it_works.html"), name="how_it_works"),
    path("model/", TemplateView.as_view(template_name="model_guide.html"), name="model_guide"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("households/", include("households.urls")),
    path("predictions/", include("predictions.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("api/", include("ml_engine.api_urls")),
    path("health/", health_check, name="health_check"),
]
