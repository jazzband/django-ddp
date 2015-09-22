"""Django DDP logging helpers."""
from __future__ import absolute_import, print_function

import datetime
import logging

from dddp import THREAD_LOCAL as this, meteor_random_id, ADDED


class DDPHandler(logging.Handler):

    """Logging handler that streams log events via DDP to the current client."""

    def emit(self, record):
        """Emit a formatted log record via DDP."""
        if getattr(this, 'subs', {}).get('Logs', False):
            this.send({
                'msg': ADDED,
                'collection': 'logs',
                'id': meteor_random_id('/collection/logs'),
                'fields': {
                    'created': datetime.datetime.fromtimestamp(record.created),
                    'name': record.name,
                    'levelno': record.levelno,
                    'levelname': record.levelname,
                    # 'pathname': record.pathname,
                    # 'lineno': record.lineno,
                    'msg': record.msg,
                    'args': record.args,
                    # 'exc_info': record.exc_info,
                    # 'funcName': record.funcName,
                },
            })
