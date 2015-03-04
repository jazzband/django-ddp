"""Django DDP app config."""

from __future__ import print_function

from django.apps import AppConfig
from django.core import serializers
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


class DjangoDDPConfig(AppConfig):

    """Django app config for django-ddp."""

    name = 'dddp'
    verbose_name = 'Django DDP'
    serializer = serializers.get_serializer('python')()

    def ready(self):
        """Initialisation for django-ddp (setup signal handlers)."""
        signals.post_save.connect(on_save)
        signals.post_delete.connect(on_delete)
