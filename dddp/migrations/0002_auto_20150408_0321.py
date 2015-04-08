# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from django.conf import settings
import dddp
import dddp.models
from dddp.migrations import TruncateOperation


class Migration(migrations.Migration):

    dependencies = [
        ('sessions', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('dddp', '0001_initial'),
    ]

    operations = [
        TruncateOperation(forwards=['subscription']),
        migrations.CreateModel(
            name='Connection',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('connection_id', dddp.models.AleaIdField(default=dddp.meteor_random_id, max_length=17)),
                ('remote_addr', models.CharField(max_length=255)),
                ('version', models.CharField(max_length=255)),
                ('session', models.ForeignKey(to='sessions.Session')),
            ],
            options={
            },
            bases=(models.Model, object),
        ),
        migrations.CreateModel(
            name='SubscriptionCollection',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=255)),
                ('collection_class', models.CharField(max_length=255)),
                ('subscription', models.ForeignKey(related_name='collections', to='dddp.Subscription')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.AlterUniqueTogether(
            name='connection',
            unique_together=set([('connection_id', 'session')]),
        ),
        migrations.AddField(
            model_name='subscription',
            name='connection',
            field=models.ForeignKey(to='dddp.Connection'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='subscription',
            name='publication_class',
            field=models.CharField(max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='subscription',
            name='sub_id',
            field=models.CharField(max_length=17),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='subscription',
            name='user',
            field=models.ForeignKey(to=settings.AUTH_USER_MODEL),
            preserve_default=False,
        ),
        migrations.AlterUniqueTogether(
            name='subscription',
            unique_together=set([('connection', 'sub_id')]),
        ),
        migrations.RemoveField(
            model_name='subscription',
            name='session',
        ),
        TruncateOperation(backwards=['subscription'])
    ]
