"""Django DDP PostgreSQL Greenlet."""

from __future__ import absolute_import

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
        self.connections = {}
        self._stop_event = gevent.event.Event()

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
        self._stop_event.wait()

    def stop(self):
        """Stop subtasks and let run() finish."""
        self._stop_event.set()

    def process_conn(self):
        """Subtask to process NOTIFY async events from DB connection."""
        self.cur.execute('LISTEN "ddp";')
        while not self._stop_event.is_set():
            gevent.select.select([self.conn], [], [], timeout=None)
            self.poll()

    def poll(self):
        """Poll DB socket and process async tasks."""
        while 1:
            state = self.conn.poll()
            if state == psycopg2.extensions.POLL_OK:
                while self.conn.notifies:
                    notify = self.conn.notifies.pop()
                    self.logger.info(
                        "Got NOTIFY (pid=%d, payload=%r)",
                        notify.pid, notify.payload,
                    )
                    data = ejson.loads(notify.payload)
                    sender = data.pop('_sender', None)
                    tx_id = data.pop('_tx_id', None)
                    for connection_id in data.pop('_connection_ids'):
                        try:
                            ws = self.connections[connection_id]
                        except KeyError:
                            continue  # connection not in this process
                        if connection_id == sender:
                            ws.send(data, tx_id=tx_id)
                        else:
                            ws.send(data)
                break
            elif state == psycopg2.extensions.POLL_WRITE:
                gevent.select.select([], [self.conn.fileno()], [])
            elif state == psycopg2.extensions.POLL_READ:
                gevent.select.select([self.conn.fileno()], [], [])
            else:
                self.logger.warn('POLL_ERR: %s', state)
