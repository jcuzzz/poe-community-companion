from django.apps import AppConfig


class TrackerConfig(AppConfig):
    name = 'tracker'
    verbose_name = "League tracker"

    def ready(self):
        from . import signals  # noqa: F401  (registers post_save handlers)
