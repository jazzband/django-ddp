from __future__ import absolute_import, unicode_literals

from dddp.api import API, Collection, Publication
from django_todos import models


class Task(Collection):
    model = models.Task


class Tasks(Publication):
    queries = [
        models.Task.objects.all(),
    ]

API.register([
    Task,
    Tasks,
])
