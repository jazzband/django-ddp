"""Django DDP notification support."""

import ejson
from django.db import connections

from dddp.msg import obj_change_as_msg


def send_notify(model, obj, msg, using):
    """Dispatch PostgreSQL async NOTIFY."""
    name, payload = obj_change_as_msg(obj, msg)
    cursor = connections[using].cursor()
    cursor.execute(
        'NOTIFY "%s", %%s' % name,
        [
            ejson.dumps(payload),
        ],
    )
