"""Django DDP WebSocket service."""

from __future__ import print_function, absolute_import

from django.db import connection, close_old_connections
close_old_connections()

import collections
import gevent.monkey
import psycogreen.gevent
gevent.monkey.patch_all()
psycogreen.gevent.patch_psycopg()

import inspect
import optparse
import random
import signal
import socket  # green
import traceback
import uuid

import ejson
import gevent
import gevent.queue
import gevent.select
import geventwebsocket
import psycopg2  # green
import psycopg2.extras
from django.core.handlers.base import BaseHandler
from django.core.handlers.wsgi import WSGIRequest
from django.core.management.base import BaseCommand
from django.db.models.loading import get_model

from dddp.msg import obj_change_as_msg


BASE_HANDLER = BaseHandler()


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


class MeteorError(Exception):

    """MeteorError."""

    pass


def validate_kwargs(func, kwargs, func_name=None):
    """Validate arguments to be supplied to func."""
    if func_name is None:
        func_name = func.__name__
    argspec = inspect.getargspec(func)
    args = argspec.args[:]

    # ignore implicit 'self' argument
    if inspect.ismethod(func) and args[0] == 'self':
        args[:1] = []

    # translate 'foo_' to avoid reserved names like 'id'
    trans = {
        arg: arg.endswith('_') and arg[:-1] or arg
        for arg
        in args
    }
    for key in list(kwargs):
        key_adj = '%s_' % key
        if key_adj in args:
            kwargs[key_adj] = kwargs.pop(key)

    required = args[:-len(argspec.defaults)]
    supplied = sorted(kwargs)
    missing = [
        trans.get(arg, arg) for arg in required
        if arg not in supplied
    ]
    if missing:
        raise MeteorError(
            'Missing required arguments to %s: %s' % (
                func_name,
                ' '.join(missing),
            ),
        )
    extra = [
        arg for arg in supplied
        if arg not in args
    ]
    if extra:
        raise MeteorError(
            'Unknown arguments to %s: %s' % (
                func_name,
                ' '.join(extra),
            ),
        )


class DDPApplication(geventwebsocket.WebSocketApplication):

    """Django DDP WebSocket application."""

    methods = {}
    versions = [  # first item is preferred version
        '1',
        'pre1',
        'pre2',
    ]
    pgworker = None
    remote_addr = None
    version = None
    support = None
    session = None
    subs = None
    request = None

    def on_open(self):
        """Handle new websocket connection."""
        self.request = WSGIRequest(self.ws.environ)
        # Apply request middleware (so we get request.user and other attrs)
        # pylint: disable=protected-access
        for middleware_method in BASE_HANDLER._request_middleware:
            response = middleware_method(self.request)
            if response:
                raise ValueError(response)

        self.remote_addr = '{0[REMOTE_ADDR]}:{0[REMOTE_PORT]}'.format(
            self.ws.environ,
        )
        self.subs = {}
        print('+ %s OPEN %s' % (self, self.request.user))
        self.send('o')
        self.send('a["{\\"server_id\\":\\"0\\"}"]')

    def __str__(self):
        """Show remote address that connected to us."""
        return self.remote_addr

    def on_close(self, reason):
        """Handle closing of websocket connection."""
        print('- %s %s' % (self, reason or 'CLOSE'))

    def on_message(self, message):
        """Process a message received from remote."""
        if self.ws.closed:
            return None
        try:
            print('< %s %r' % (self, message))

            # parse message set
            try:
                msgs = ejson.loads(message)
            except ValueError, err:
                raise MeteorError(400, 'Data is not valid EJSON')
            if not isinstance(msgs, list):
                raise MeteorError(400, 'Invalid EJSON messages')

            # process individual messages
            while msgs:
                # parse message payload
                raw = msgs.pop(0)
                try:
                    try:
                        data = ejson.loads(raw)
                    except ValueError, err:
                        raise MeteorError(400, 'Data is not valid EJSON')
                    if not isinstance(data, dict):
                        self.error(400, 'Invalid EJSON message payload', raw)
                        continue
                    try:
                        msg = data.pop('msg')
                    except KeyError:
                        raise MeteorError(400, 'Missing `msg` parameter', raw)
                    # dispatch message
                    self.dispatch(msg, data)
                except MeteorError, err:
                    self.error(err)
                except Exception, err:
                    traceback.print_exc()
                    self.error(err)
        except geventwebsocket.WebSocketError, err:
            self.ws.close()
        except MeteorError, err:
            self.error(err)

    def dispatch(self, msg, kwargs):
        """Dispatch msg to appropriate recv_foo handler."""
        # enforce calling 'connect' first
        if not self.session and msg != 'connect':
            raise MeteorError(400, 'Session not establised - try `connect`.')

        # lookup method handler
        try:
            handler = getattr(self, 'recv_%s' % msg)
        except (AttributeError, UnicodeEncodeError):
            raise MeteorError(404, 'Method not found')

        # validate handler arguments
        validate_kwargs(handler, kwargs)

        # dispatch to handler
        try:
            handler(**kwargs)
        except Exception, err:
            raise MeteorError(500, 'Internal server error', err)

    def send(self, data):
        """Send raw `data` to WebSocket client."""
        print('> %s %r' % (self, data))
        try:
            self.ws.send(data)
        except geventwebsocket.WebSocketError, err:
            self.ws.close()

    def reply(self, msg, **kwargs):
        """Send EJSON reply to remote."""
        kwargs['msg'] = msg
        data = ejson.dumps([ejson.dumps(kwargs)])
        self.send('a%s' % data)

    def error(self, err, reason=None, detail=None):
        """Send EJSON error to remote."""
        if isinstance(err, MeteorError):
            (err, reason, detail) = (err.args[:] + (None, None, None))[:3]
        data = {
            'error': '%s' % (err or '<UNKNOWN_ERROR>'),
        }
        if reason:
            data['reason'] = reason
        if detail:
            data['detail'] = detail
        print('! %s %r' % (self, data))
        self.reply('error', **data)

    def recv_connect(self, version, support, session=None):
        """DDP connect handler."""
        if self.session:
            self.error(
                'Session already established.',
                reason='Current session in detail.',
                detail=self.session,
            )
        elif version not in self.versions:
            self.reply('failed', version=self.versions[0])
        elif version not in support:
            self.error('Client version/support mismatch.')
        else:
            if not session:
                session = uuid.uuid4().hex
            self.version = version
            self.support = support
            self.session = session
            self.reply('connected', session=self.session)

    def recv_ping(self, id_=None):
        """DDP ping handler."""
        if id_ is None:
            self.reply('pong')
        else:
            self.reply('pong', id=id_)

    def sub_notify(self, id_, name, params, data):
        """Send added/changed/removed msg due to receiving NOTIFY."""
        self.reply(**data)

    def recv_sub(self, id_, name, params=None):
        """DDP sub handler."""
        self.pgworker.subscribe(self.sub_notify, self, id_, name, params)

        model = get_model(name)
        for obj in model.objects.all():
            _, payload = obj_change_as_msg(obj, 'added')
            self.sub_notify(id_, name, params, payload)

        self.reply('ready', subs=[id_])

    def sub_unnotify(self, id_):
        """Send added/changed/removed msg due to receiving NOTIFY."""
        pass  # TODO: find out if we're meant to send anything to the client

    def recv_unsub(self, id_):
        """DDP unsub handler."""
        self.pgworker.unsubscribe(self.sub_unnotify, self, id_)

    def recv_method(self, method, params, id_, randomSeed=None):
        """DDP method handler."""
        try:
            func = self.methods[method]
        except KeyError:
            self.reply('result', id=id_, error=u'Unknown method: %s' % method)
        else:
            try:
                self.reply('result', id=id_, result=func(**params))
            except Exception, err:
                self.reply('result', id=id_, error='%s' % err)
            finally:
                pass


def ddpp_sockjs_xhr(environ, start_response):
    """Dummy method that doesn't handle XHR requests."""
    start_response(
        '404 Not found',
        [
            ('Content-Type', 'text/plain; charset=UTF-8'),
            (
                'Access-Control-Allow-Origin',
                '/'.join(environ['HTTP_REFERER'].split('/')[:3]),
            ),
            ('Access-Control-Allow-Credentials', 'true'),
            #  ('access-control-allow-credentials', 'true'),
            ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0'),
            ('Connection', 'keep-alive'),
            ('Vary', 'Origin'),
        ],
    )
    yield 'No.'


def ddpp_sockjs_info(environ, start_response):
    """Inform client that WebSocket service is available."""
    start_response(
        '200 OK',
        [
            ('Content-Type', 'application/json; charset=UTF-8'),
            (
                'Access-Control-Allow-Origin',
                '/'.join(environ['HTTP_REFERER'].split('/')[:3]),
            ),
            ('Access-Control-Allow-Credentials', 'true'),
            #  ('access-control-allow-credentials', 'true'),
            ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0'),
            ('Connection', 'keep-alive'),
            ('Vary', 'Origin'),
        ],
    )
    yield ejson.dumps(collections.OrderedDict([
        ('websocket', True),
        ('origins', [
            '*:*',
        ]),
        ('cookie_needed', False),
        ('entropy', random.getrandbits(32)),
    ]))


from meerqat import wsgi
resource = geventwebsocket.Resource({
    r'/websocket': DDPApplication,
    r'^/sockjs/\d+/\w+/websocket$': DDPApplication,
    r'^/sockjs/\d+/\w+/xhr$': ddpp_sockjs_xhr,
    r'^/sockjs/info$': ddpp_sockjs_info,
    r'^/(?!(websocket|sockjs)/)': wsgi.application,
})


class Command(BaseCommand):

    """Command to run DDP web service."""

    args = 'HOST PORT'
    help = 'Run DDP service'
    requires_system_checks = False

    option_list = BaseCommand.option_list + (
        optparse.make_option(
            '-H', '--host', dest="host", metavar='HOST',
            help='TCP listening host (default: localhost)', default='localhost',
        ),
        optparse.make_option(
            '-p', '--port', dest="port", metavar='PORT',
            help='TCP listening port (default: 3000)', default='3000',
        ),
    )

    def handle(self, *args, **options):
        """Spawn greenlets for handling websockets and PostgreSQL calls."""
        # setup PostgresGreenlet to multiplex DB calls
        postgres = PostgresGreenlet(connection)
        DDPApplication.pgworker = postgres

        # setup WebSocketServer to dispatch web requests
        BASE_HANDLER.load_middleware()
        host = options['host']
        port = options['port']
        if port.isdigit():
            port = int(port)
        else:
            port = socket.getservbyname(port)
        webserver = geventwebsocket.WebSocketServer(
            (host, port),
            resource,
            debug=int(options['verbosity']) > 1,
        )

        def killall(*args, **kwargs):
            """Kill all green threads."""
            postgres.stop()
            webserver.stop()

        # die gracefully with SIGINT or SIGQUIT
        gevent.signal(signal.SIGINT, killall)
        gevent.signal(signal.SIGQUIT, killall)

        # start greenlets
        print('Running as ws://%s:%d/websocket' % (host, port))
        postgres.start()
        webserver.serve_forever()
