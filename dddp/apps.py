"""Django DDP app config."""

from __future__ import print_function

from django.apps import AppConfig
from django.core import serializers
from django.conf import settings, ImproperlyConfigured
from django.db.models import signals

from dddp.notify import send_notify


def on_save(sender, **kwargs):
    """Post-save signal handler."""
    send_notify(
        model=sender,
        obj=kwargs['instance'],
        msg=kwargs['created'] and 'added' or 'changed',
        using=kwargs['using'],
    )


def on_delete(sender, **kwargs):
    """Post-delete signal handler."""
    send_notify(
        model=sender,
        obj=kwargs['instance'],
        msg='removed',
        using=kwargs['using'],
    )


def on_m2m_changed(sender, **kwargs):
    """M2M-changed signal handler."""
    # See https://docs.djangoproject.com/en/1.7/ref/signals/#m2m-changed
    if kwargs['action'] in (
        'post_add',
        'post_remove',
        'post_clear',
    ):
        if kwargs['reverse'] == False:
            objs = [kwargs['instance']]
            model = objs[0].__class__
        else:
            model = kwargs['model']
            objs = model.objects.filter(pk__in=kwargs['pk_set'])

        for obj in objs:
            send_notify(
                model=model,
                obj=obj,
                msg='changed',
                using=kwargs['using'],
            )


class DjangoDDPConfig(AppConfig):

    """Django app config for django-ddp."""

    name = 'dddp'
    verbose_name = 'Django DDP'
    serializer = serializers.get_serializer('python')()

    def ready(self):
        """Initialisation for django-ddp (setup signal handlers)."""
        if not settings.DATABASES:
            raise ImproperlyConfigured('No databases configured.')
        for (alias, conf) in settings.DATABASES.items():
            if conf['ENGINE'] != 'django.db.backends.postgresql_psycopg2':
                raise ImproperlyConfigured(
                    '%r uses %r: django-ddp only works with PostgreSQL.' % (
                        alias, conf['backend'],
                    )
                )
        signals.post_save.connect(on_save)
        signals.post_delete.connect(on_delete)
        signals.m2m_changed.connect(on_m2m_changed)
