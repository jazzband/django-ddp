"""Django DDP PostgreSQL Greenlet."""

from __future__ import absolute_import

import collections

import ejson
import gevent
import gevent.queue
import gevent.select
import psycopg2  # green
import psycopg2.extensions
from geventwebsocket.logging import create_logger


class PostgresGreenlet(gevent.Greenlet):

    """Greenlet for multiplexing database operations."""

    def __init__(self, conn, debug=False):
        """Prepare async connection."""
        super(PostgresGreenlet, self).__init__()
        self.logger = create_logger(__name__, debug=debug)

        # queues for processing incoming sub/unsub requests and processing
        self.subs = gevent.queue.Queue()
        self.unsubs = gevent.queue.Queue()
        self.proc_queue = gevent.queue.Queue()
        self._stop_event = gevent.event.Event()

        # dict of name: subscribers
        # eg: {'bookstore.book': {'tpozNWMPphaJ2n8bj': <function at ...>}}
        self.all_subs = collections.defaultdict(dict)
        self._sub_lock = gevent.lock.RLock()

        # connect to DB in async mode
        conn.allow_thread_sharing = True
        self.connection = conn
        self.conn_params = conn.get_connection_params()
        self.conn_params.update(
            async=True,
        )
        self.conn = psycopg2.connect(**self.conn_params)
        self.poll()  # wait for conneciton to start
        self.cur = self.conn.cursor()

    def _run(self):  # pylint: disable=method-hidden
        """Spawn sub tasks, wait for stop signal."""
        gevent.spawn(self.process_conn)
        gevent.spawn(self.process_subs)
        gevent.spawn(self.process_unsubs)
        self._stop_event.wait()

    def stop(self):
        """Stop subtasks and let run() finish."""
        self._stop_event.set()

    def subscribe(self, func, id_, names):
        """Register callback `func` to be called after NOTIFY for `names`."""
        self.subs.put((func, id_, names))

    def unsubscribe(self, func, id_):
        """Un-register callback `func` to be called after NOTIFY for `id`."""
        self.unsubs.put((func, id_))

    def process_conn(self):
        """Subtask to process NOTIFY async events from DB connection."""
        while not self._stop_event.is_set():
            # TODO: change timeout so self._stop_event is periodically checked?
            gevent.select.select([self.conn], [], [], timeout=None)
            self.poll()

    def poll(self):
        """Poll DB socket and process async tasks."""
        while 1:
            state = self.conn.poll()
            if state == psycopg2.extensions.POLL_OK:
                while self.conn.notifies:
                    notify = self.conn.notifies.pop()
                    name = notify.channel
                    self.logger.info(
                        "Got NOTIFY (pid=%d, name=%r, payload=%r)",
                        notify.pid, name, notify.payload,
                    )
                    try:
                        self._sub_lock.acquire()
                        self.logger.info(self.all_subs)
                        subs = self.all_subs[name]
                        data = ejson.loads(notify.payload)
                        sub_ids = data.pop('_sub_ids')
                        self.logger.info('Subscribers: %r', sub_ids)
                        self.logger.info(subs)
                        for id_, func in subs.items():
                            if id_ not in sub_ids:
                                continue  # not for this subscription
                            gevent.spawn(func, id_, name, data)
                    finally:
                        self._sub_lock.release()
                break
            elif state == psycopg2.extensions.POLL_WRITE:
                gevent.select.select([], [self.conn.fileno()], [])
            elif state == psycopg2.extensions.POLL_READ:
                gevent.select.select([self.conn.fileno()], [], [])
            else:
                self.logger.warn('POLL_ERR: %s', state)

    def process_subs(self):
        """Subtask to process `sub` requests from `self.subs` queue."""
        while not self._stop_event.is_set():
            func, id_, names = self.subs.get()
            try:
                self._sub_lock.acquire()
                for name in names:
                    subs = self.all_subs[name]
                    if len(subs) == 0:
                        self.logger.debug('LISTEN "%s";', name)
                        self.poll()
                        self.cur.execute('LISTEN "%s";' % name)
                        self.poll()
                    subs[id_] = func
            finally:
                self._sub_lock.release()

    def process_unsubs(self):
        """Subtask to process `unsub` requests from `self.unsubs` queue."""
        while not self._stop_event.is_set():
            func, id_ = self.unsubs.get()
            try:
                self._sub_lock.acquire()
                for name in list(self.all_subs):
                    subs = self.all_subs[name]
                    subs.pop(id_, None)
                    if len(subs) == 0:
                        self.logger.info('UNLISTEN "%s";', name)
                        self.cur.execute('UNLISTEN "%s";' % name)
                        self.poll()
                        del self.all_subs[name]
            finally:
                self._sub_lock.release()
            gevent.spawn(func, id_)
