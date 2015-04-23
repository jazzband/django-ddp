# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dddp', '0003_auto_20150413_1328'),
    ]

    operations = [
        migrations.AddField(
            model_name='connection',
            name='server_addr',
            field=models.CharField(default='', max_length=255),
            preserve_default=False,
        ),
    ]
