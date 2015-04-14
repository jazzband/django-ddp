# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dddp', '0002_auto_20150408_0321'),
    ]

    operations = [
        migrations.AlterField(
            model_name='objectmapping',
            name='object_id',
            field=models.CharField(max_length=255),
            preserve_default=True,
        ),
    ]
