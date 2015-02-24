"""Django DDP app config."""

from __future__ import print_function

import uuid
import ejson
from django.apps import AppConfig
from django.core import serializers
from django.db import connections
from django.db.models import signals

from dddp.msg import obj_change_as_msg


class DjangoDDPConfig(AppConfig):
    name = 'dddp'
    verbose_name = 'Django DDP'
    serializer = serializers.get_serializer('python')()

    def ready(self):
        for (signal, handler) in [
            (signals.post_save, self.on_save),
            (signals.post_delete, self.on_delete),
        ]:
            signal.connect(handler)

    def on_save(self, sender, **kwargs):
        self.send_notify(
            model=sender,
            obj=kwargs['instance'],
            msg=kwargs['created'] and 'added' or 'changed',
            using=kwargs['using'],
        )

    def on_delete(self, sender, **kwargs):
        self.send_notify(
            model=sender,
            obj=kwargs['instance'],
            msg='removed',
            using=kwargs['using'],
        )

    def send_notify(self, model, obj, msg, using):
        name, payload = obj_change_as_msg(obj, msg)
        cursor = connections[using].cursor()
        cursor.execute(
            'NOTIFY "%s", %%s' % name,
            [
                ejson.dumps(payload),
            ],
        )
