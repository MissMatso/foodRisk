from django.apps import AppConfig


class HouseholdsConfig(AppConfig):
    name = "households"

    def ready(self):
        from . import audit  # noqa: F401  registers pre_save/post_save/post_delete signals
