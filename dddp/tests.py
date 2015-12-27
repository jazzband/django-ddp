"""Django DDP test suite."""
from __future__ import absolute_import, unicode_literals

import doctest
import errno
import os
import socket
import sys
import unittest
import django.test
import ejson
import gevent
import dddp.alea
from dddp.main import DDPLauncher
# pylint: disable=E0611, F0401
from six.moves.urllib_parse import urljoin

os.environ['DJANGO_SETTINGS_MODULE'] = 'dddp.test.test_project.settings'

DOCTEST_MODULES = [
    dddp.alea,
]


def expected_failure_if(condition):
    """Decorator to conditionally wrap func in unittest.expectedFailure."""
    if callable(condition):
        condition = condition()
    if condition:
        # condition is True, expect failure.
        return unittest.expectedFailure
    else:
        # condition is False, expect success.
        return lambda func: func


class WebSocketClient(object):

    """WebSocket client."""

    # WEBSOCKET

    def __init__(self, *args, **kwargs):
        """Create WebSocket connection to URL."""
        import websocket
        self.websocket = websocket.create_connection(*args, **kwargs)
        self.call_seq = 0

    def send(self, **msg):
        """Send message."""
        self.websocket.send(ejson.dumps(msg))

    def recv(self):
        """Receive a message."""
        raw = self.websocket.recv()
        return ejson.loads(raw)

    def close(self):
        """Close the connection."""
        self.websocket.close()

    # CONTEXT MANAGER

    def __enter__(self):
        """Enter context block."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context block, close connection."""
        self.websocket.close()

    # DDP
    def next_id(self):
        """Return next `id` from sequence."""
        self.call_seq += 1
        return self.call_seq

    def connect(self, *versions):
        """Connect with given versions."""
        self.send(msg='connect', version=versions[0], support=versions)

    def ping(self, id_=None):
        """Ping with optional id."""
        if id_:
            self.send(msg='ping', id=id_)
        else:
            self.send(msg='ping')

    def call(self, method, *args):
        """Make a method call."""
        id_ = self.next_id()
        self.send(msg='method', method=method, params=args, id=id_)
        return id_


class SockJSClient(WebSocketClient):

    """SockJS wrapped WebSocketClient."""

    def send(self, **msg):
        """Send a SockJS wrapped msg."""
        self.websocket.send(ejson.dumps([ejson.dumps(msg)]))

    def recv(self):
        """Receive a SockJS wrapped msg."""
        raw = self.websocket.recv()
        if not raw.startswith('a'):
            raise ValueError('Invalid response: %r' % raw)
        wrapped = ejson.loads(raw[1:])
        return [ejson.loads(msg) for msg in wrapped]


class DDPTestServer(object):

    """DDP server with auto start and stop."""

    server_addr = '127.0.0.1'
    server_port_range = range(8000, 8080)
    ssl_certfile_path = None
    ssl_keyfile_path = None

    def __init__(self):
        """Fire up the DDP server."""
        self.server_port = 8000
        kwargs = {}
        if self.ssl_certfile_path:
            kwargs['certfile'] = self.ssl_certfile_path
        if self.ssl_keyfile_path:
            kwargs['keyfile'] = self.ssl_keyfile_path
        self.scheme = 'https' if kwargs else 'http'
        for server_port in self.server_port_range:
            self.server = DDPLauncher(debug=True)
            self.server.add_web_servers(
                [
                    (self.server_addr, server_port),
                ],
                **kwargs
            )
            try:
                self.server.start()
                self.server_port = server_port
                return  # server started
            except socket.error as err:
                if err.errno != errno.EADDRINUSE:
                    raise  # error wasn't "address in use", re-raise.
                continue  # port in use, try next port.
        raise RuntimeError('Failed to start DDP server.')

    def stop(self):
        """Shut down the DDP server."""
        self.server.stop()

    def websocket(self, url, *args, **kwargs):
        """Return a WebSocketClient for the given URL."""
        return WebSocketClient(
            self.url(url).replace('http', 'ws'), *args, **kwargs
        )

    def sockjs(self, url, *args, **kwargs):
        """Return a SockJSClient for the given URL."""
        return SockJSClient(
            self.url(url).replace('http', 'ws'), *args, **kwargs
        )

    def url(self, path):
        """Return full URL for given path."""
        return urljoin(
            '%s://%s:%d' % (self.scheme, self.server_addr, self.server_port),
            path,
        )


class DDPServerTestCase(django.test.TransactionTestCase):

    _server = None

    @property
    def server(self):
        if self._server is None:
            self._server = DDPTestServer()
        return self._server

    def tearDown(self):
        """Stop the DDP server, and reliably close any open DB transactions."""
        if self._server is not None:
            self._server.stop()
        self._server = None
        # OK, let me explain what I think is going on here...
        #   1. Tests run, but cursors aren't closed.
        #   2. Open cursors keeping queries running on DB.
        #   3. Django TestCase.tearDown() tries to `sqlflush`
        #   4. DB complains that queries from (2) are still running.
        # Solution is to use the open DB connection and execute a DB noop query
        # such as `SELECT pg_sleep(0)` to force another round trip to the DB.
        # If you have another idea as to what is going on, submit an issue. :)
        from django.db import connection, close_old_connections
        close_old_connections()
        cur = connection.cursor()
        cur.execute('SELECT pg_sleep(0);')
        cur.fetchall()
        cur.close()
        connection.close()
        gevent.sleep()
        super(DDPServerTestCase, self).tearDown()

    def url(self, path):
        return self.server.url(path)


class HttpTestCase(DDPServerTestCase):

    """Test that server launches and handles HTTP requests."""

    # gevent-websocket doesn't work with Python 3 yet
    @expected_failure_if(sys.version_info.major == 3)
    def test_get(self):
        """Perform HTTP GET."""
        import requests
        resp = requests.get(self.url('/'))
        self.assertEqual(resp.status_code, 200)


class WebSocketTestCase(DDPServerTestCase):

    """Test that server launches and handles WebSocket connections."""

    # gevent-websocket doesn't work with Python 3 yet
    @expected_failure_if(sys.version_info.major == 3)
    def test_sockjs_connect_ping(self):
        """SockJS connect."""
        sockjs = self.server.sockjs('/sockjs/1/a/websocket')

        resp = sockjs.websocket.recv()
        self.assertEqual(resp, 'o')

        msgs = sockjs.recv()
        self.assertEqual(
            msgs, [
                {'server_id': '0'},
            ],
        )

        sockjs.connect('1', 'pre2', 'pre1')
        msgs = sockjs.recv()
        self.assertEqual(
            msgs, [
                {'msg': 'connected', 'session': msgs[0].get('session', None)},
            ],
        )

        # first without `id`
        sockjs.ping()
        msgs = sockjs.recv()
        self.assertEqual(msgs, [{'msg': 'pong'}])

        # then with `id`
        id_ = sockjs.next_id()
        sockjs.ping(id_)
        msgs = sockjs.recv()
        self.assertEqual(msgs, [{'msg': 'pong', 'id': id_}])

        sockjs.close()

    # gevent-websocket doesn't work with Python 3 yet
    @expected_failure_if(sys.version_info.major == 3)
    def test_call_missing_arguments(self):
        """Connect and login without any arguments."""
        sockjs = self.server.sockjs('/sockjs/1/a/websocket')

        resp = sockjs.websocket.recv()
        self.assertEqual(resp, 'o')

        msgs = sockjs.recv()
        self.assertEqual(
            msgs, [
                {'server_id': '0'},
            ],
        )

        sockjs.connect('1', 'pre2', 'pre1')
        msgs = sockjs.recv()
        self.assertEqual(
            msgs, [
                {'msg': 'connected', 'session': msgs[0].get('session', None)},
            ],
        )

        id_ = sockjs.call('login')  # expects `credentials` argument
        msgs = sockjs.recv()
        self.assertEqual(
            msgs, [
                {
                    'msg': 'result',
                    'error': {
                        'error': 500,
                        'reason':
                            'login() takes exactly 2 arguments (1 given)',
                    },
                    'id': id_,
                },
            ],
        )

        sockjs.close()

    # gevent-websocket doesn't work with Python 3 yet
    @expected_failure_if(sys.version_info.major == 3)
    def test_call_extra_arguments(self):
        """Connect and login with extra arguments."""
        with self.server.sockjs('/sockjs/1/a/websocket') as sockjs:

            resp = sockjs.websocket.recv()
            self.assertEqual(resp, 'o')

            msgs = sockjs.recv()
            self.assertEqual(
                msgs, [
                    {'server_id': '0'},
                ],
            )

            sockjs.connect('1', 'pre2', 'pre1')
            msgs = sockjs.recv()
            self.assertEqual(
                msgs, [
                    {
                        'msg': 'connected',
                        'session': msgs[0].get('session', None),
                    },
                ],
            )

            id_ = sockjs.call('login', 1, 2)  # takes single argument
            msgs = sockjs.recv()
            self.assertEqual(
                msgs, [
                    {
                        'msg': 'result',
                        'error': {
                            'error': 500,
                            'reason':
                                'login() takes exactly 2 arguments (3 given)',
                        },
                        'id': id_,
                    },
                ],
            )


def load_tests(loader, tests, pattern):
    """Specify which test cases to run."""
    del pattern
    suite = unittest.TestSuite()
    # add all TestCase classes from this (current) module
    for attr in globals().values():
        if attr is DDPServerTestCase:
            continue  # not meant to be executed, is has no tests.
        try:
            if not issubclass(attr, unittest.TestCase):
                continue  # not subclass of TestCase
        except TypeError:
            continue  # not a class
        tests = loader.loadTestsFromTestCase(attr)
        suite.addTests(tests)
    # add doctests defined in DOCTEST_MODULES
    for doctest_module in DOCTEST_MODULES:
        suite.addTest(doctest.DocTestSuite(doctest_module))
    return suite
