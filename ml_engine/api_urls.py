from rest_framework.routers import DefaultRouter
from .api_views import HouseholdViewSet, PredictionViewSet

router = DefaultRouter()
router.register("households", HouseholdViewSet, basename="api-households")
router.register("predictions", PredictionViewSet, basename="api-predictions")

urlpatterns = router.urls
