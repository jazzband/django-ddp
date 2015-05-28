"""Django DDP app config."""

from __future__ import print_function

from django.apps import AppConfig
from django.conf import settings, ImproperlyConfigured
from django.db import DatabaseError
from django.db.models import signals

from dddp import autodiscover
from dddp.models import Connection


class DjangoDDPConfig(AppConfig):

    """Django app config for django-ddp."""

    api = None
    name = 'dddp'
    verbose_name = 'Django DDP'
    _in_migration = False

    def ready(self):
        """Initialisation for django-ddp (setup lookups and signal handlers)."""
        if not settings.DATABASES:
            raise ImproperlyConfigured('No databases configured.')
        for (alias, conf) in settings.DATABASES.items():
            if conf['ENGINE'] != 'django.db.backends.postgresql_psycopg2':
                raise ImproperlyConfigured(
                    '%r uses %r: django-ddp only works with PostgreSQL.' % (
                        alias, conf['backend'],
                    )
                )
        self.api = autodiscover()
        self.api.ready()
