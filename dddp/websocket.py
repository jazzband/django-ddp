"""Django DDP WebSocket service."""

from __future__ import print_function, absolute_import

import inspect
import traceback
import uuid

import ejson
import geventwebsocket
from django.core.handlers.base import BaseHandler
from django.core.handlers.wsgi import WSGIRequest
from django.db.models.loading import get_model

from dddp.msg import obj_change_as_msg


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


class DDPWebSocketApplication(geventwebsocket.WebSocketApplication):

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
    base_handler = BaseHandler()

    def on_open(self):
        """Handle new websocket connection."""
        self.request = WSGIRequest(self.ws.environ)
        # Apply request middleware (so we get request.user and other attrs)
        # pylint: disable=protected-access
        if self.base_handler._request_middleware is None:
            self.base_handler.load_middleware()
        for middleware_method in self.base_handler._request_middleware:
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
        except geventwebsocket.WebSocketError:
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
