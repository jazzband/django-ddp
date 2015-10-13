"""Django DDP app config."""
import warnings

from django.apps import AppConfig
from django.conf import settings, ImproperlyConfigured

from dddp import autodiscover


class DjangoDDPConfig(AppConfig):

    """Django app config for django-ddp."""

    api = None
    name = 'dddp'
    verbose_name = 'Django DDP'

    def ready(self):
        """Initialisation for django-ddp (setup lookups and signal handlers)."""
        if not settings.DATABASES:
            raise ImproperlyConfigured('No databases configured.')
        for (alias, conf) in settings.DATABASES.items():
            engine = conf['ENGINE']
            if engine != 'django.db.backends.postgresql_psycopg2':
                warnings.warn(
                    'Database %r uses unsupported %r engine.' % (
                        alias, engine,
                    ),
                    UserWarning,
                )
        self.api = autodiscover()
        self.api.ready()
