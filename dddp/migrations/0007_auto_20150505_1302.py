# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dddp', '0006_auto_20150428_2245'),
    ]

    operations = [
        migrations.RenameField(
            model_name='subscriptioncollection',
            old_name='collection_class',
            new_name='collection_name',
        ),
        migrations.RenameField(
            model_name='subscriptioncollection',
            old_name='name',
            new_name='model_name',
        ),
    ]
