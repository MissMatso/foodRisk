from accounts.roles import is_system_admin
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from households.models import Household
from predictions.models import Prediction
from predictions.services import save_prediction, explain_prediction
from .predictor import get_predictor
from .serializers import HouseholdSerializer, PredictionSerializer


class IsStaffOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and (user.is_superuser or user.role in ("staff", "admin"))


class IsSystemAdmin(permissions.BasePermission):
    """Deleting a household also deletes its whole assessment history, so only a System Admin may do it."""

    message = "Only a System Admin can delete a household."

    def has_permission(self, request, view):
        return is_system_admin(request.user)


class HouseholdViewSet(viewsets.ModelViewSet):
    """/api/households/ — bonus DRF endpoint (Optional Enhancement)."""

    queryset = Household.objects.all()
    serializer_class = HouseholdSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action == "destroy":
            return [IsSystemAdmin()]
        if self.action in ("create", "update", "partial_update", "predict"):
            return [IsStaffOrAdmin()]
        return super().get_permissions()

    def perform_create(self, serializer):
        serializer.save(registered_by=self.request.user)

    @action(detail=True, methods=["post"])
    def predict(self, request, pk=None):
        """POST /api/households/{id}/predict/ — generate + store a prediction."""
        household = self.get_object()
        result = get_predictor().predict(household)
        if "error" in result:
            return Response(result, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        prediction = save_prediction(household, result, request.user)
        return Response(PredictionSerializer(prediction).data, status=status.HTTP_201_CREATED)


class PredictionViewSet(viewsets.ReadOnlyModelViewSet):
    """/api/predictions/ — read-only history."""

    queryset = Prediction.objects.all()
    serializer_class = PredictionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        return [IsStaffOrAdmin()] if self.action == "explain" else super().get_permissions()

    @action(detail=True, methods=["post"])
    def explain(self, request, pk=None):
        prediction = self.get_object()
        try:
            explain_prediction(prediction)
        except Exception:
            return Response({"error": "Explanation unavailable. The saved score is unchanged."}, status=422)
        return Response(PredictionSerializer(prediction).data)

    def get_queryset(self):
        qs = super().get_queryset()
        household_id = self.request.query_params.get("household")
        if household_id:
            qs = qs.filter(household_id=household_id)
        return qs
