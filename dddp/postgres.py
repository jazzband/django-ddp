"""Django DDP PostgreSQL Greenlet."""

from __future__ import absolute_import

import ejson
import gevent
import gevent.queue
import gevent.select
import os
import psycopg2  # green
import psycopg2.extensions
import socket


class PostgresGreenlet(gevent.Greenlet):

    """Greenlet for multiplexing database operations."""

    def __init__(self, conn):
        """Prepare async connection."""
        super(PostgresGreenlet, self).__init__()
        import logging
        self.logger = logging.getLogger('dddp.postgres')

        # queues for processing incoming sub/unsub requests and processing
        self.connections = {}
        self.chunks = {}
        self._stop_event = gevent.event.Event()

        # connect to DB in async mode
        conn.allow_thread_sharing = True
        self.connection = conn
        self.select_greenlet = None

    def _run(self):  # pylint: disable=method-hidden
        """Spawn sub tasks, wait for stop signal."""
        conn_params = self.connection.get_connection_params()
        # See http://initd.org/psycopg/docs/module.html#psycopg2.connect and
        # http://www.postgresql.org/docs/current/static/libpq-connect.html
        # section 31.1.2 (Parameter Key Words) for details on available params.
        conn_params.update(
            async=True,
            application_name='{} pid={} django-ddp'.format(
                socket.gethostname(),  # hostname
                os.getpid(),  # PID
            )[:64],  # 64 characters for default PostgreSQL build config
        )
        conn = None
        while conn is None:
            try:
                conn = psycopg2.connect(**conn_params)
            except psycopg2.OperationalError as err:
                # Some variants of the psycopg2 driver for Django add extra
                # params that aren't meant to be passed directly to
                # `psycopg2.connect()` -- issue a warning and try again.
                msg = ('%s' % err).strip()
                msg_prefix = 'invalid connection option "'
                if not msg.startswith(msg_prefix):
                    # *waves hand* this is not the errror you are looking for.
                    raise
                key = msg[len(msg_prefix):-1]
                self.logger.warning(
                    'Ignoring unknown settings.DATABASES[%r] option: %s=%r',
                    self.connection.alias,
                    key, conn_params.pop(key),
                )
        self.poll(conn)  # wait for conneciton to start

        import logging
        logging.getLogger('dddp').info('=> Started PostgresGreenlet.')

        cur = conn.cursor()
        cur.execute('LISTEN "ddp";')
        while not self._stop_event.is_set():
            try:
                self.select_greenlet = gevent.spawn(
                    gevent.select.select,
                    [conn], [], [], timeout=None,
                )
                self.select_greenlet.join()
            except gevent.GreenletExit:
                self._stop_event.set()
            finally:
                self.select_greenlet = None
            self.poll(conn)
        self.poll(conn)
        cur.close()
        self.poll(conn)
        conn.close()

    def stop(self):
        """Stop subtasks and let run() finish."""
        self._stop_event.set()
        if self.select_greenlet is not None:
            self.select_greenlet.kill()

    def poll(self, conn):
        """Poll DB socket and process async tasks."""
        while 1:
            state = conn.poll()
            if state == psycopg2.extensions.POLL_OK:
                while conn.notifies:
                    notify = conn.notifies.pop()
                    self.logger.info(
                        "Got NOTIFY (pid=%d, payload=%r)",
                        notify.pid, notify.payload,
                    )

                    # read the header and check seq/fin.
                    hdr, chunk = notify.payload.split('|', 1)
                    # print('RECEIVE: %s' % hdr)
                    header = ejson.loads(hdr)
                    uuid = header['uuid']
                    size, chunks = self.chunks.setdefault(uuid, [0, {}])
                    if header['fin']:
                        size = self.chunks[uuid][0] = header['seq']

                    # stash the chunk
                    chunks[header['seq']] = chunk

                    if len(chunks) != size:
                        # haven't got all the chunks yet
                        continue  # process next NOTIFY in loop

                    # got the last chunk -> process it.
                    data = ''.join(
                        chunk for _, chunk in sorted(chunks.items())
                    )
                    del self.chunks[uuid]  # don't forget to cleanup!
                    data = ejson.loads(data)
                    sender = data.pop('_sender', None)
                    tx_id = data.pop('_tx_id', None)
                    for connection_id in data.pop('_connection_ids'):
                        try:
                            websocket = self.connections[connection_id]
                        except KeyError:
                            continue  # connection not in this process
                        if connection_id == sender:
                            websocket.send(data, tx_id=tx_id)
                        else:
                            websocket.send(data)
                break
            elif state == psycopg2.extensions.POLL_WRITE:
                gevent.select.select([], [conn.fileno()], [])
            elif state == psycopg2.extensions.POLL_READ:
                gevent.select.select([conn.fileno()], [], [])
            else:
                self.logger.warn('POLL_ERR: %s', state)
