from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView
from django.views.generic.edit import CreateView, UpdateView

from accounts.mixins import StaffOrAnalystRequiredMixin, StaffRequiredMixin
from households.models import Household
from ml_engine.feature_labels import ranked
from ml_engine.global_explanation import load as load_global_explanation
from ml_engine.predictor import get_predictor
from .forms import InterventionForm
from .models import Intervention, Prediction
from .services import explain_prediction, recent_assessment, save_prediction
import logging

logger = logging.getLogger(__name__)


class GeneratePredictionView(StaffRequiredMixin, View):
    """Generate risk for an already registered household — FR005.

    NGO Staff only. Runs inference for one household and stores the
    result after successful inference.
    """

    def post(self, request, pk):
        household = get_object_or_404(Household, pk=pk)
        if recent_assessment(household):
            # A double click or page refresh: do not store the same score twice.
            messages.info(
                request, "A score was just generated for this household, so no duplicate was created."
            )
            return redirect(reverse("households:household_detail", kwargs={"pk": household.pk}))
        predictor = get_predictor()
        result = predictor.predict(household)

        if "error" in result:
            messages.error(request, result["error"])
        else:
            save_prediction(household, result, request.user)
            messages.success(
                request, f"Assessment score generated: {result['score']}% ({result['category']} risk)."
            )
        return redirect(reverse("households:household_detail", kwargs={"pk": household.pk}))


class PredictionHistoryView(StaffOrAnalystRequiredMixin, ListView):
    """View Prediction — full history for one household (FR008)."""

    model = Prediction
    template_name = "predictions/prediction_history.html"
    context_object_name = "predictions"

    def get_queryset(self):
        self.household = get_object_or_404(Household, pk=self.kwargs["pk"])
        return Prediction.objects.filter(household=self.household)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["household"] = self.household
        return context


class PredictionDetailView(StaffOrAnalystRequiredMixin, DetailView):
    """One assessment, with its SHAP explanation shown as a walk from the baseline to the score."""

    model = Prediction
    template_name = "predictions/prediction_detail.html"
    context_object_name = "prediction"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prediction = self.object
        if prediction.explanation:
            context["contributions"] = ranked(prediction.explanation)
            summary = load_global_explanation(prediction.model_version)
            if summary:
                # SHAP is additive: baseline + every contribution = this household's score.
                baseline = summary["baseline_probability"]
                context["baseline_percent"] = round(baseline * 100, 1)
                context["explained_percent"] = round(
                    (baseline + sum(prediction.explanation.values())) * 100, 1
                )
        return context


class InterventionCreateView(StaffRequiredMixin, CreateView):
    model = Intervention
    form_class = InterventionForm
    template_name = "predictions/intervention_form.html"

    @property
    def prediction(self):
        return get_object_or_404(Prediction, pk=self.kwargs["pk"])

    def form_valid(self, form):
        form.instance.prediction = self.prediction
        form.instance.created_by = self.request.user
        messages.success(self.request, "Intervention and follow-up were recorded.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("predictions:detail", kwargs={"pk": self.prediction.pk})


class InterventionUpdateView(StaffRequiredMixin, UpdateView):
    model = Intervention
    form_class = InterventionForm
    template_name = "predictions/intervention_form.html"

    @property
    def prediction(self):
        return self.object.prediction

    def get_success_url(self):
        return reverse("predictions:detail", kwargs={"pk": self.object.prediction_id})

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Intervention updated.")
        return response


class ExplainPredictionView(StaffRequiredMixin, View):
    def post(self, request, pk):
        prediction = get_object_or_404(Prediction, pk=pk)
        try:
            explain_prediction(prediction)
            messages.success(request, "Explanation ready for the original assessment inputs.")
        except ValueError as exc:
            messages.error(request, str(exc))
        except Exception:
            logger.exception("Explanation unavailable")
            messages.error(request, "Explanation unavailable. The saved score is unchanged.")
        return redirect("predictions:detail", pk=pk)
