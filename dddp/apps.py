"""Django DDP app config."""

from __future__ import print_function

import uuid
import ejson
from django.apps import AppConfig
from django.core import serializers
from django.db import connections
from django.db.models import signals

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
        data = self.serializer.serialize([obj])[0]
        name = data['model']
        print(name)
        #name = '%s.%s' % (
        #    model._meta.app_label,
        #    model._meta.object_name,
        #)

        # always use UUID as ID
        if isinstance(data['pk'], int):
            #data['pk'] = uuid.uuid3(uuid.NAMESPACE_URL, '%d' % data['pk']).hex
            data['pk'] = '%d' % data['pk']

        payload = {
            'msg': msg,
            'collection': name,
            'id': data['pk'],
        }
        if msg != 'removed':
            payload['fields'] = data['fields']
        cursor = connections[using].cursor()
        print(name)
        cursor.execute(
            'NOTIFY "%s", %%s' % name,
            [
                ejson.dumps(payload),
            ],
        )
