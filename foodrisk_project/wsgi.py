"""
WSGI config for foodrisk_project project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "foodrisk_project.settings")

application = get_wsgi_application()

# The Compose configuration is a local demo. With DEBUG enabled, serve static
# assets through Django so the landing page works behind its Gunicorn process.
# A real deployment with DEBUG disabled must serve STATIC_ROOT via a web
# server/CDN and terminate HTTPS at a trusted proxy.

if settings.DEBUG:
    from django.contrib.staticfiles.handlers import StaticFilesHandler  # noqa: E402

    application = StaticFilesHandler(application)
