# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import dddp.models


class Migration(migrations.Migration):

    dependencies = [
        ('sessions', '0001_initial'),
        ('contenttypes', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ObjectMapping',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('meteor_id', dddp.models.AleaIdField(max_length=17)),
                ('object_id', models.PositiveIntegerField()),
                ('content_type', models.ForeignKey(to='contenttypes.ContentType')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('publication', models.CharField(max_length=255)),
                ('params_ejson', models.TextField(default=b'{}')),
                ('session', models.ForeignKey(to='sessions.Session')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.AlterUniqueTogether(
            name='objectmapping',
            unique_together=set([('content_type', 'meteor_id')]),
        ),
        migrations.AlterIndexTogether(
            name='objectmapping',
            index_together=set([('content_type', 'meteor_id'), ('content_type', 'object_id')]),
        ),
    ]
