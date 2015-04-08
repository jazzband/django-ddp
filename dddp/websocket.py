"""Django DDP WebSocket service."""

from __future__ import absolute_import

import inspect
import traceback

import ejson
import geventwebsocket
from django.core.handlers.base import BaseHandler
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction

from dddp import THREAD_LOCAL as this, alea
from dddp.api import API


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

    required = args[:-len(argspec.defaults or [])]
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


class DDPWebSocketApplication(geventwebsocket.WebSocketApplication):

    """Django DDP WebSocket application."""

    methods = {}
    versions = [  # first item is preferred version
        '1',
        'pre1',
        'pre2',
    ]
    logger = None
    pgworker = None
    remote_addr = None
    version = None
    support = None
    connection = None
    subs = None
    request = None
    base_handler = BaseHandler()

    def on_open(self):
        """Handle new websocket connection."""
        self.logger = self.ws.logger
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
        this.send_msg = self.send_msg
        this.reply = self.reply
        this.error = self.error
        this.session_key = this.request.session.session_key

        this.remote_addr = self.remote_addr = \
            '{0[REMOTE_ADDR]}:{0[REMOTE_PORT]}'.format(
                self.ws.environ,
            )
        self.subs = {}
        self.logger.info('+ %s OPEN %s', self, this.request.user)
        self.send('o')
        self.send('a["{\\"server_id\\":\\"0\\"}"]')

    def __str__(self):
        """Show remote address that connected to us."""
        return self.remote_addr

    def on_close(self, reason):
        """Handle closing of websocket connection."""
        if self.connection is not None:
            self.connection.delete()
            self.connection = None
        self.logger.info('- %s %s', self, reason or 'CLOSE')

    @transaction.atomic
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

    def dispatch(self, msg, kwargs):
        """Dispatch msg to appropriate recv_foo handler."""
        # enforce calling 'connect' first
        if self.connection is None and msg != 'connect':
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
        except Exception, err:  # print stack trace --> pylint: disable=W0703
            traceback.print_exc()
            self.error(MeteorError(500, 'Internal server error', err))

    def send(self, data):
        """Send raw `data` to WebSocket client."""
        self.logger.debug('> %s %r', self, data)
        try:
            self.ws.send(data)
        except geventwebsocket.WebSocketError:
            self.ws.close()

    def send_msg(self, payload):
        """Send EJSON payload to remote."""
        data = ejson.dumps([ejson.dumps(payload)])
        self.send('a%s' % data)

    def reply(self, msg, **kwargs):
        """Send EJSON reply to remote."""
        kwargs['msg'] = msg
        self.send_msg(kwargs)

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

    def recv_connect(self, version, support, session=None):
        """DDP connect handler."""
        if self.connection is not None:
            self.error(
                'Session already established.',
                reason='Current session in detail.',
                detail=self.connection.connection_id,
            )
        elif version not in self.versions:
            self.reply('failed', version=self.versions[0])
        elif version not in support:
            self.error('Client version/support mismatch.')
        else:
            from dddp.models import Connection
            this.version = version
            this.support = support
            self.connection = Connection.objects.create(
                session_id=this.session_key,
                remote_addr=self.remote_addr,
                version=version,
            )
            self.reply('connected', session=self.connection.connection_id)

    def recv_ping(self, id_=None):
        """DDP ping handler."""
        if id_ is None:
            self.reply('pong')
        else:
            self.reply('pong', id=id_)

    def sub_notify(self, id_, name, params, data):
        """Send added/changed/removed msg due to receiving NOTIFY."""
        self.reply(**data)

    def recv_sub(self, id_, name, params):
        """DDP sub handler."""
        API.sub(id_, name, *params)

    def recv_unsub(self, id_):
        """DDP unsub handler."""
        API.unsub(id_)

    def recv_method(self, method, params, id_, randomSeed=None):
        """DDP method handler."""
        if randomSeed is not None:
            this.alea_random = alea.Alea(randomSeed)
        API.method(method, params, id_)
        self.reply('updated', methods=[id_])
