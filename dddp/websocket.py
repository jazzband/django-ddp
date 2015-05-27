"""Django DDP WebSocket service."""

from __future__ import absolute_import

import atexit
import collections
import inspect
import itertools
import sys
import traceback

from six.moves import range as irange

import ejson
import geventwebsocket
from django.core.handlers.base import BaseHandler
from django.core.handlers.wsgi import WSGIRequest
from django.db import connection, transaction

from dddp import THREAD_LOCAL as this, alea, ADDED, CHANGED, REMOVED


class MeteorError(Exception):

    """MeteorError."""

    pass


def validate_kwargs(func, kwargs):
    """Validate arguments to be supplied to func."""
    func_name = func.__name__
    argspec = inspect.getargspec(func)
    all_args = argspec.args[:]
    defaults = list(argspec.defaults or [])

    # ignore implicit 'self' argument
    if inspect.ismethod(func) and all_args[:1] == ['self']:
        all_args[:1] = []

    # don't require arguments that have defaults
    if defaults:
        required = all_args[:-len(defaults)]
    else:
        required = all_args[:]

    # translate 'foo_' to avoid reserved names like 'id'
    trans = {
        arg: arg.endswith('_') and arg[:-1] or arg
        for arg
        in all_args
    }
    for key in list(kwargs):
        key_adj = '%s_' % key
        if key_adj in all_args:
            kwargs[key_adj] = kwargs.pop(key)

    # figure out what we're missing
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
            getattr(func, 'err', None),
        )

    # figure out what is extra
    extra = [
        arg for arg in supplied
        if arg not in all_args
    ]
    if extra:
        raise MeteorError(
            'Unknown arguments to %s: %s' % (
                func_name,
                ' '.join(extra),
            ),
        )


class DDPWebSocketApplication(geventwebsocket.WebSocketApplication):

    """Django DDP WebSocket application."""

    _tx_buffer = None
    _tx_buffer_id_gen = None
    _tx_next_id_gen = None
    _tx_next_id = None

    methods = {}
    versions = [  # first item is preferred version
        '1',
        'pre1',
        'pre2',
    ]
    api = None
    logger = None
    pgworker = None
    remote_addr = None
    version = None
    support = None
    connection = None
    subs = None
    request = None
    remote_ids = None
    base_handler = BaseHandler()

    def get_tx_id(self):
        """Get the next TX msg ID."""
        return next(self._tx_buffer_id_gen)

    def on_open(self):
        """Handle new websocket connection."""
        self.logger = self.ws.logger
        self.remote_ids = collections.defaultdict(set)

        # self._tx_buffer collects outgoing messages which must be sent in order
        self._tx_buffer = {}
        # track the head of the queue (buffer) and the next msg to be sent
        self._tx_buffer_id_gen = itertools.cycle(irange(sys.maxint))
        self._tx_next_id_gen = itertools.cycle(irange(sys.maxint))
        # start by waiting for the very first message
        self._tx_next_id = next(self._tx_next_id_gen)

        this.remote_addr = self.remote_addr = \
            '{0[REMOTE_ADDR]}:{0[REMOTE_PORT]}'.format(
                self.ws.environ,
            )
        self.subs = {}
        self.logger.info('+ %s OPEN', self)
        self.send('o')
        self.send('a["{\\"server_id\\":\\"0\\"}"]')

    def __str__(self):
        """Show remote address that connected to us."""
        return self.remote_addr

    def on_close(self, reason):
        """Handle closing of websocket connection."""
        if self.connection is not None:
            del self.pgworker.connections[self.connection.pk]
            self.connection.delete()
            self.connection = None
        self.logger.info('- %s %s', self, reason or 'CLOSE')

    def on_message(self, message):
        """Process a message received from remote."""
        if self.ws.closed:
            return None
        try:
            self.logger.debug('< %s %r', self, message)

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
                        raise MeteorError(
                            400, 'Bad request', None, {'offendingMessage': data}
                        )
                    # dispatch message
                    self.dispatch(msg, data)
                except MeteorError, err:
                    traceback.print_exc()
                    self.error(err)
                except Exception, err:
                    traceback.print_exc()
                    self.error(err)
        except geventwebsocket.WebSocketError, err:
            self.ws.close()
        except MeteorError, err:
            self.error(err)

    @transaction.atomic
    def dispatch(self, msg, kwargs):
        """Dispatch msg to appropriate recv_foo handler."""
        # enforce calling 'connect' first
        if self.connection is None and msg != 'connect':
            raise MeteorError(400, 'Must connect first')

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
        except Exception, err:  # print stack trace --> pylint: disable=W0703
            traceback.print_exc()
            self.error(MeteorError(500, 'Internal server error', err))

    def send(self, data, tx_id=None):
        """Send `data` (raw string or EJSON payload) to WebSocket client."""
        # buffer data until we get pre-requisite data
        if tx_id is None:
            tx_id = self.get_tx_id()
        if self._tx_buffer:
            self.logger.debug(
                'TX received %d, waiting for %d, have %r.',
                tx_id, self._tx_next_id, self._tx_buffer,
            )
        self._tx_buffer[tx_id] = data

        # de-queue messages from buffer
        while self._tx_next_id in self._tx_buffer:
            # pull next message from buffer
            data = self._tx_buffer.pop(self._tx_next_id)
            if self._tx_buffer:
                self.logger.debug('TX found %d', self._tx_next_id)
            # advance next message ID
            self._tx_next_id = next(self._tx_next_id_gen)
            if not isinstance(data, basestring):
                # ejson payload
                msg = data.get('msg', None)
                if msg in (ADDED, CHANGED, REMOVED):
                    ids = self.remote_ids[data['collection']]
                    meteor_id = data['id']
                    if msg == ADDED:
                        if meteor_id in ids:
                            msg = data['msg'] = CHANGED
                        else:
                            ids.add(meteor_id)
                    elif msg == CHANGED:
                        if meteor_id not in ids:
                            # object has become visible, treat as `added`.
                            msg = data['msg'] = ADDED
                            ids.add(meteor_id)
                    elif msg == REMOVED:
                        try:
                            ids.remove(meteor_id)
                        except KeyError:
                            continue  # client doesn't have this, don't send.
                data = 'a%s' % ejson.dumps([ejson.dumps(data)])
            # send message
            self.logger.debug('> %s %r', self, data)
            try:
                self.ws.send(data)
            except geventwebsocket.WebSocketError:
                self.ws.close()
                break

    def reply(self, msg, **kwargs):
        """Send EJSON reply to remote."""
        kwargs['msg'] = msg
        self.send(kwargs)

    def error(self, err, reason=None, detail=None, **kwargs):
        """Send EJSON error to remote."""
        if isinstance(err, MeteorError):
            (
                err, reason, detail, kwargs,
            ) = (
                err.args[:] + (None, None, None, None)
            )[:4]
        elif isinstance(err, Exception):
            reason = str(err)
        data = {
            'error': '%s' % (err or '<UNKNOWN_ERROR>'),
        }
        if reason:
            if reason is Exception:
                reason = str(reason)
            data['reason'] = reason
        if detail:
            if isinstance(detail, Exception):
                detail = str(detail)
            data['detail'] = detail
        if kwargs:
            data.update(kwargs)
        self.logger.error('! %s %r', self, data)
        self.reply('error', **data)

    def recv_connect(self, version=None, support=None, session=None):
        """DDP connect handler."""
        if self.connection is not None:
            self.error(
                'Session already established.',
                reason='Current session in detail.',
                detail=self.connection.connection_id,
            )
        elif None in (version, support) or version not in self.versions:
            self.reply('failed', version=self.versions[0])
        elif version not in support:
            self.error('Client version/support mismatch.')
        else:
            self.request = WSGIRequest(self.ws.environ)
            # Apply request middleware (so we get request.user and other attrs)
            # pylint: disable=protected-access
            if self.base_handler._request_middleware is None:
                self.base_handler.load_middleware()
            for middleware_method in self.base_handler._request_middleware:
                response = middleware_method(self.request)
                if response:
                    raise ValueError(response)
            this.ws = self
            this.request = self.request
            this.send = self.send
            this.reply = self.reply
            this.error = self.error
            this.request.session.save()

            from dddp.models import Connection
            cur = connection.cursor()
            cur.execute('SELECT pg_backend_pid()')
            (backend_pid,) = cur.fetchone()
            this.version = version
            this.support = support
            self.connection = Connection.objects.create(
                server_addr='%d:%s' % (
                    backend_pid,
                    self.ws.handler.socket.getsockname(),
                ),
                remote_addr=self.remote_addr,
                version=version,
            )
            self.pgworker.connections[self.connection.pk] = self
            atexit.register(self.on_close, 'Shutting down.')
            self.reply('connected', session=self.connection.connection_id)

    def recv_ping(self, id_=None):
        """DDP ping handler."""
        if id_ is None:
            self.reply('pong')
        else:
            self.reply('pong', id=id_)

    def recv_sub(self, id_, name, params):
        """DDP sub handler."""
        self.api.sub(id_, name, *params)
    recv_sub.err = 'Malformed subscription'

    def recv_unsub(self, id_=None):
        """DDP unsub handler."""
        if id_:
            self.api.unsub(id_)
        else:
            self.reply('nosub')

    def recv_method(self, method, params, id_, randomSeed=None):
        """DDP method handler."""
        if randomSeed is not None:
            this.random_streams.random_seed = randomSeed
            this.alea_random = alea.Alea(randomSeed)
        self.api.method(method, params, id_)
        self.reply('updated', methods=[id_])
    recv_method.err = 'Malformed method invocation'
