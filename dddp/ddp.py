from django.contrib import auth
from dddp import THREAD_LOCAL
from dddp.api import API, Publication
from dddp.logging import LOGS_NAME


class ClientVersions(Publication):
    """Publication for `meteor_autoupdate_clientVersions`."""

    name = 'meteor_autoupdate_clientVersions'

    queries = []


class Logs(Publication):

    name = LOGS_NAME
    users = auth.get_user_model()

    def get_queries(self):
        user_pk = getattr(THREAD_LOCAL, 'user_id', False)
        if user_pk:
            if self.users.objects.filter(
                pk=user_pk,
                is_active=True,
                is_superuser=True,
            ).exists():
                return []
        raise ValueError('User not permitted.')


API.register([ClientVersions, Logs])
