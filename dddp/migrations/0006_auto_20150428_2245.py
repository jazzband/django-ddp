# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dddp', '0005_auto_20150427_1209'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='connection',
            unique_together=set([]),
        ),
        migrations.RemoveField(
            model_name='connection',
            name='session',
        ),
    ]
