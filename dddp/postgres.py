"""Django DDP PostgreSQL Greenlet."""

from __future__ import print_function, absolute_import

import collections
import gevent.monkey
import psycogreen.gevent
gevent.monkey.patch_all()
psycogreen.gevent.patch_psycopg()

import ejson
import gevent
import gevent.queue
import gevent.select
import psycopg2  # green
import psycopg2.extras


class PostgresGreenlet(gevent.Greenlet):

    """Greenlet for multiplexing database operations."""

    def __init__(self, conn):
        """Prepare async connection."""
        # greenify!
        super(PostgresGreenlet, self).__init__()

        # queues for processing incoming sub/unsub requests and processing
        self.subs = gevent.queue.Queue()
        self.unsubs = gevent.queue.Queue()
        self.proc_queue = gevent.queue.Queue()
        self._stop_event = gevent.event.Event()

        # dict of name: subscribers
        self.all_subs = collections.defaultdict(dict)
        self._sub_lock = gevent.lock.RLock()

        # connect to DB in async mode
        conn.allow_thread_sharing = True
        self.connection = conn
        self.conn_params = conn.get_connection_params()
        self.conn_params['async'] = True
        self.conn = conn.get_new_connection(self.conn_params)
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

    def subscribe(self, func, obj, id_, name, params):
        """Register callback `func` to be called after NOTIFY for `name`."""
        self.subs.put((func, obj, id_, name, params))

    def unsubscribe(self, func, obj, id_):
        """Un-register callback `func` to be called after NOTIFY for `name`."""
        self.unsubs.put((func, obj, id_))

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
                    print("Got NOTIFY:", notify.pid, name, notify.payload)
                    try:
                        self._sub_lock.acquire()
                        subs = self.all_subs[name]
                        data = ejson.loads(notify.payload)
                        for (_, id_), (func, params) in subs.items():
                            gevent.spawn(func, id_, name, params, data)
                    finally:
                        self._sub_lock.release()
                break
            elif state == psycopg2.extensions.POLL_WRITE:
                gevent.select.select([], [self.conn.fileno()], [])
            elif state == psycopg2.extensions.POLL_READ:
                gevent.select.select([self.conn.fileno()], [], [])
            else:
                print('POLL_ERR: %s' % state)

    def process_subs(self):
        """Subtask to process `sub` requests from `self.subs` queue."""
        while not self._stop_event.is_set():
            func, obj, id_, name, params = self.subs.get()
            try:
                self._sub_lock.acquire()
                subs = self.all_subs[name]
                if len(subs) == 0:
                    print('LISTEN "%s";' % name)
                    self.poll()
                    self.cur.execute('LISTEN "%s";' % name)
                    self.poll()
                subs[(obj, id_)] = (func, params)
            finally:
                self._sub_lock.release()

    def process_unsubs(self):
        """Subtask to process `unsub` requests from `self.unsubs` queue."""
        while not self._stop_event.is_set():
            func, obj, id_ = self.unsubs.get()
            try:
                self._sub_lock.acquire()
                for name, subs in self.all_subs.items():
                    subs.pop((obj, id_), None)
                    if len(subs) == 0:
                        print('UNLISTEN "%s";' % name)
                        self.cur.execute('UNLISTEN "%s";' % name)
                        self.poll()
                        del self.all_subs[name]
            finally:
                self._sub_lock.release()
            gevent.spawn(func, id_)
