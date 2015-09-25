"""Django DDP logging helpers."""
from __future__ import absolute_import, print_function

import datetime
import logging
import traceback

from dddp import THREAD_LOCAL as this, meteor_random_id, ADDED


LOGS_NAME = 'dddp.logs'


def stacklines_or_none(exc_info):
    """Return list of stack text lines or None."""
    if exc_info is None:
        return None
    return traceback.format_exception(*exc_info)


class DDPHandler(logging.Handler):

    """Logging handler that streams log events via DDP to the current client."""

    formatter = logging.BASIC_FORMAT

    def emit(self, record):
        """Emit a formatted log record via DDP."""
        if getattr(this, 'subs', {}).get(LOGS_NAME, False):
            self.format(record)
            this.send({
                'msg': ADDED,
                'collection': LOGS_NAME,
                'id': meteor_random_id('/collection/%s' % LOGS_NAME),
                'fields': {
                    attr: {
                        # typecasting methods for specific attributes
                        'args': lambda args: [repr(arg) for arg in args],
                        'created': datetime.datetime.fromtimestamp,
                        'exc_info': stacklines_or_none,
                    }.get(
                        attr,
                        lambda val: val  # default typecasting method
                    )(getattr(record, attr, None))
                    for attr in (
                        'args',
                        'asctime',
                        'created',
                        'exc_info',
                        'filename',
                        'funcName',
                        'levelname',
                        'levelno',
                        'lineno',
                        'module',
                        'msecs',
                        'message',
                        'name',
                        'pathname',
                        'process',
                        'processName',
                        'relativeCreated',
                        'thread',
                        'threadName',
                    )
                },
            })
