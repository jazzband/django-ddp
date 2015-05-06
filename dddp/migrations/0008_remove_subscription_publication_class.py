# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dddp', '0007_auto_20150505_1302'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='subscription',
            name='publication_class',
        ),
    ]
