from dddp.api import API, Collection, Publication
from dddp.test.django_todos import models


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
