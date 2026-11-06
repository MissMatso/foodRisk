from django.contrib import admin
from .models import Intervention, Prediction

admin.site.register(Intervention)


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("household", "score", "category", "model_version", "created_at")
    list_filter = ("category", "model_version")
