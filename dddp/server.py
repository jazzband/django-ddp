"""Django DDP WebSocket service."""

from __future__ import print_function

import collections
import gevent.monkey
import psycogreen.gevent
gevent.monkey.patch_all()
psycogreen.gevent.patch_psycopg()

import inspect
import random
import signal
import socket  # green
import sys
import traceback
import uuid

import ejson
import gevent
import gevent.queue
import gevent.select
import geventwebsocket
import psycopg2  # green
import psycopg2.extras
from django.db import connection


sub_queue = gevent.queue.Queue()
unsub_queue = gevent.queue.Queue()
all_subs = collections.defaultdict(list)


def subscribe(func, name, params):
    sub_queue.put((func, name, params))


def unsubscribe(func, name, params):
    unsub_queue.put((func, name, params))


def pg_loop(conn):
    if gevent.select.select([conn], [], [], 5) == ([], [], []):
        print("Timeout")
    else:
        pg_wait(conn)


def pg_wait(conn):
    while True:
        state = conn.poll()
        if state == psycopg2.extensions.POLL_OK:
            while conn.notifies:
                notify = conn.notifies.pop()
                name = notify.channel
                print("Got NOTIFY:", notify.pid, name, notify.payload)
                subs = all_subs[name]
                data = ejson.loads(notify.payload)
                for (func, params) in subs:
                    try:
                        gevent.spawn(func, name, params, data)
                        #func(name, params, data)
                    except Exception, err:
                        print("Callback error: %s" % err)
                        traceback.print_exc()
            break
        elif state == psycopg2.extensions.POLL_WRITE:
            print('POLL_WRITE')
            gevent.select.select([], [conn.fileno()], [])
        elif state == psycopg2.extensions.POLL_READ:
            print('POLL_READ')
            gevent.select.select([conn.fileno()], [], [])
        else:
            print('POLL_ERR: %s' % state)
            raise psycopg2.OperationalError("poll() returned %s" % state)


def pg_listen():
    conn_params = connection.get_connection_params()
    conn_params['async'] = True
    #psycopg2.extensions.set_wait_callback(psycopg2.extras.wait_select)
    #pg_wait = psycopg2.extras.wait_select
    conn = connection.get_new_connection(conn_params)
    #pg_wait(conn)
    pg_wait(conn)
    #psycopg2.extras.wait_select(conn)
    cur = conn.cursor()
    #cur.execute('LISTEN "survey.response";')
    print('LISTEN')
    while 1:
        try:
            func, name, params = sub_queue.get_nowait()
            subs = all_subs[name]
            if len(subs) == 0:
                print('LISTEN "%s";' % name)
                cur.execute('LISTEN "%s";' % name)
            subs.append((func, params))
        except gevent.queue.Empty:
            pass
        try:
            func, name, params = unsub_queue.get_nowait()
            subs = all_subs[name]
            subs.remove(func, params)
            if len(subs) == 0:
                print('UNLISTEN "%s";' % name)
                cur.execute('UNLISTEN "%s";' % name)
        except gevent.queue.Empty:
            pass

        pg_loop(conn)
    #psycopg2.extras.wait_select(conn)


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
    if inspect.ismethod(func):
        args[:1] = []

    # translate 'foo' args into 'foo_' to avoid crap argument names
    for key in list(kwargs):
        key_adj = '%s_' % key
        if key_adj in args:
            kwargs[key_adj] = kwargs.pop(key)

    required = args[:-len(argspec.defaults)]
    supplied = sorted(kwargs)
    missing = [
        arg for arg in required
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
    remote_addr = None
    version = None
    support = None
    session = None
    subs = None

    #def __init__(self, environ, start_response, *args, **kwargs):
    #    print('INIT: %r %r' % (args, kwargs))
    #    super_init = super(DDPApplication, self).__init__
    #    print(inspect.getargspec(super_init))
    #    return super_init(environ, start_response, *args, **kwargs)

    def on_open(self):
        """Handle new websocket connection."""
        self.remote_addr = '{0[REMOTE_ADDR]}:{0[REMOTE_PORT]}'.format(
            self.ws.environ,
        )
        self.subs = {}
        print('+ %s OPEN' % self)
        self.send('o')
        self.send('a["{\\"server_id\\":\\"0\\"}"]')

    def __str__(self):
        """Show remote address that connected to us."""
        return self.remote_addr

    def on_close(self, reason):
        """Handle closing of websocket connection."""
        print('- %s %s' % (self, reason or 'CLOSE'))

    def on_message(self, raw):
        """Process a message received from remote."""
        if self.ws.closed:
            return None
        try:
            print('< %s %r' % (self, raw))
            data = ejson.loads(raw)
            data = ejson.loads(data[0])
            try:
                msg = data.pop('msg')
            except (AttributeError, TypeError, IndexError):
                raise MeteorError('Invalid EJSON message type.')
            except KeyError:
                raise MeteorError('Missing required field: msg')
            else:
                self.dispatch(msg, data)
        except geventwebsocket.WebSocketError, err:
            self.on_close(err)
        except Exception, err:
            self.error(err)

    def dispatch(self, msg, kwargs):
        """Dispatch msg to appropriate recv_foo handler."""
        # enforce calling 'connect' first
        if not self.session and msg != 'connect':
            raise MeteorError("Session not establised - try 'connect'.")

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
        print('> %s %r' % (self, data))
        self.ws.send(data)

    def reply(self, msg, **kwargs):
        """Send EJSON reply to remote."""
        kwargs['msg'] = msg
        data = ejson.dumps([ejson.dumps(kwargs)])
        self.send('a%s' % data)

    def error(self, err, reason=None, detail=None):
        """Send EJSON error to remote."""
        if isinstance(err, MeteorError):
            (err, reason, detail) = (err.args[:] + (None, None, None))[:3]
        if not err:
            err = '<UNKNOWN_ERROR>'
        data = {
            'error': err,
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

    def sub_notify(self, name, params, data):
        self.reply(**data)

    def recv_sub(self, id_, name, params=None):
        """DDP sub handler."""
        print('recv_sub: %r %r %r' % (id_, name, params))
        subscribe(self.sub_notify, name, params)
        self.reply('ready', subs=[id_])

    def recv_unsub(self, id_):
        """DDP unsub handler."""
        unsubscribe(self.sub_notify, name, params)

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
    start_response(
        '404 Not found',
        [
            ('Content-Type', 'text/plain; charset=UTF-8'),
            (
                'Access-Control-Allow-Origin',
                '%s://%s:3000' % (
                    environ['wsgi.url_scheme'],
                    environ['HTTP_HOST'].split(':')[0],
                ),
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
    print(environ)
    host = environ['HTTP_HOST'].split(':')[0]
    start_response(
        '200 OK',
        [
            ('Content-Type', 'application/json; charset=UTF-8'),
            (
                'Access-Control-Allow-Origin',
                '%s://%s:3000' % (
                    environ['wsgi.url_scheme'],
                    environ['HTTP_HOST'].split(':')[0],
                ),
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

class DDPServer(geventwebsocket.WebSocketServer):
    def __init__(self, *args, **kwargs):
        print('INIT: %r %r' % (args, kwargs))
        return super(DDPServer, self).__init__(*args, **kwargs)

resource = geventwebsocket.Resource({
    r'/websocket': DDPApplication,
    r'^/sockjs/\d+/\w+/websocket$': DDPApplication,
    r'^/sockjs/\d+/\w+/xhr$': ddpp_sockjs_xhr,
    r'^/sockjs/info$': ddpp_sockjs_info,
})

if __name__ == '__main__':
    addr = (sys.argv[1:] + [':8001'])[0]
    (host, port) = (addr.rsplit(':', 1)[:2] + [':8001'])[:2]
    if port.isdigit():
        port = int(port)
    else:
        port = socket.getservbyname(port)
    server = geventwebsocket.WebSocketServer(
        (host, port),
        resource,
        debug='-v' in sys.argv,
    )
    print('Running as ws://%s:%d/websocket' % (host, port))
    threads = [
        gevent.spawn(server.serve_forever),
        gevent.spawn(pg_listen),
    ]

    def killall():
        """Kill all green threads."""
        for thread in threads:
            thread.kill()

    gevent.signal(signal.SIGINT, killall)
    gevent.signal(signal.SIGQUIT, killall)
    gevent.joinall(threads)
