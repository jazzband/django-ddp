# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import dddp.models


class Migration(migrations.Migration):

    dependencies = [
        ('dddp', '0008_remove_subscription_publication_class'),
    ]

    operations = [
        migrations.AlterField(
            model_name='connection',
            name='connection_id',
            field=dddp.models.AleaIdField(max_length=17, verbose_name=b'Alea ID'),
        ),
    ]
