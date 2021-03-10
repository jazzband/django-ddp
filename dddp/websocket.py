"""Django DDP WebSocket service."""



import atexit
import collections
import inspect
import itertools
import sys
import traceback

from six.moves import range as irange

import ejson
import gevent
import geventwebsocket
from django.conf import settings
from django.core import signals
from django.core.handlers.base import BaseHandler
from django.core.handlers.wsgi import WSGIRequest
from django.db import connection, transaction

from dddp import alea, this, ADDED, CHANGED, REMOVED, MeteorError


def safe_call(func, *args, **kwargs):
    """
    Call `func(*args, **kwargs)` but NEVER raise an exception.

    Useful in situations such as inside exception handlers where calls to
    `logging.error` try to send email, but the SMTP server isn't always
    availalbe and you don't want your exception handler blowing up.
    """
    try:
        return None, func(*args, **kwargs)
    except Exception:  # pylint: disable=broad-except
        # something went wrong during the call, return a stack trace that can
        # be dealt with by the caller
        return traceback.format_exc(), None


def dprint(name, val):
    """Debug print name and val."""
    from pprint import pformat
    print(
        '% 5s: %s' % (
            name,
            '\n       '.join(
                pformat(
                    val, indent=4, width=75,
                ).split('\n')
            ),
        ),
    )


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
            400,
            func.err,
            'Missing required arguments to %s: %s' % (
                func_name,
                ' '.join(missing),
            ),
        )

    # figure out what is extra
    extra = [
        arg for arg in supplied
        if arg not in all_args
    ]
    if extra:
        raise MeteorError(
            400,
            func.err,
            'Unknown arguments to %s: %s' % (func_name, ' '.join(extra)),
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
    remote_ids = None
    base_handler = BaseHandler()

    def get_tx_id(self):
        """Get the next TX msg ID."""
        return next(self._tx_buffer_id_gen)

    def on_open(self):
        """Handle new websocket connection."""
        this.request = WSGIRequest(self.ws.environ)
        this.ws = self
        this.send = self.send
        this.reply = self.reply

        self.logger = self.ws.logger
        self.remote_ids = collections.defaultdict(set)

        # `_tx_buffer` collects outgoing messages which must be sent in order
        self._tx_buffer = {}
        # track the head of the queue (buffer) and the next msg to be sent
        self._tx_buffer_id_gen = itertools.cycle(irange(sys.maxsize))
        self._tx_next_id_gen = itertools.cycle(irange(sys.maxsize))
        # start by waiting for the very first message
        self._tx_next_id = next(self._tx_next_id_gen)

        this.remote_addr = self.remote_addr = \
            '{0[REMOTE_ADDR]}:{0[REMOTE_PORT]}'.format(
                self.ws.environ,
            )
        this.subs = {}
        safe_call(self.logger.info, '+ %s OPEN', self)
        self.send('o')
        self.send('a["{\\"server_id\\":\\"0\\"}"]')

    def __str__(self):
        """Show remote address that connected to us."""
        return self.remote_addr

    def on_close(self, *args, **kwargs):
        """Handle closing of websocket connection."""
        if self.connection is not None:
            del self.pgworker.connections[self.connection.pk]
            self.connection.delete()
            self.connection = None
        signals.request_finished.send(sender=self.__class__)
        safe_call(self.logger.info, '- %s %s', self, args or 'CLOSE')

    def on_message(self, message):
        """Process a message received from remote."""
        if self.ws.closed:
            return None
        try:
            safe_call(self.logger.debug, '< %s %r', self, message)

            # process individual messages
            for data in self.ddp_frames_from_message(message):
                self.process_ddp(data)
                # emit request_finished signal to close DB connections
                signals.request_finished.send(sender=self.__class__)
        except geventwebsocket.WebSocketError:
            self.ws.close()

    def ddp_frames_from_message(self, message):
        """Yield DDP messages from a raw WebSocket message."""
        # parse message set
        try:
            msgs = ejson.loads(message)
        except ValueError:
            self.reply(
                'error', error=400, reason='Data is not valid EJSON',
            )
            raise StopIteration
        if not isinstance(msgs, list):
            self.reply(
                'error', error=400, reason='Invalid EJSON messages',
            )
            raise StopIteration
        # process individual messages
        while msgs:
            # pop raw message from the list
            raw = msgs.pop(0)
            # parse message payload
            try:
                data = ejson.loads(raw)
            except (TypeError, ValueError):
                data = None
            if not isinstance(data, dict):
                self.reply(
                    'error', error=400,
                    reason='Invalid SockJS DDP payload',
                    offendingMessage=raw,
                )
            yield data
            if msgs:
                # yield to other greenlets before processing next msg
                gevent.sleep()

    def process_ddp(self, data):
        """Process a single DDP message."""
        msg_id = data.get('id', None)
        try:
            msg = data.pop('msg')
        except KeyError:
            self.reply(
                'error', reason='Bad request',
                offendingMessage=data,
            )
            return
        try:
            # dispatch message
            self.dispatch(msg, data)
        except Exception as err:  # pylint: disable=broad-except
            # This should be the only protocol exception handler
            kwargs = {
                'msg': {'method': 'result'}.get(msg, 'error'),
            }
            if msg_id is not None:
                kwargs['id'] = msg_id
            if isinstance(err, MeteorError):
                error = err.as_dict()
            else:
                error = {
                    'error': 500,
                    'reason': 'Internal server error',
                }
            if kwargs['msg'] == 'error':
                kwargs.update(error)
            else:
                kwargs['error'] = error
            if not isinstance(err, MeteorError):
                # not a client error, should always be logged.
                stack, _ = safe_call(
                    self.logger.error, '%r %r', msg, data, exc_info=1,
                )
                if stack is not None:
                    # something went wrong while logging the error, revert to
                    # writing a stack trace to stderr.
                    traceback.print_exc(file=sys.stderr)
                    sys.stderr.write(
                        'Additionally, while handling the above error the '
                        'following error was encountered:\n'
                    )
                    sys.stderr.write(stack)
            elif settings.DEBUG:
                print('ERROR: %s' % err)
                dprint('msg', msg)
                dprint('data', data)
                error.setdefault('details', traceback.format_exc())
                # print stack trace for client errors when DEBUG is True.
                print(error['details'])
            self.reply(**kwargs)
            if msg_id and msg == 'method':
                self.reply('updated', methods=[msg_id])

    @transaction.atomic
    def dispatch(self, msg, kwargs):
        """Dispatch msg to appropriate recv_foo handler."""
        # enforce calling 'connect' first
        if self.connection is None and msg != 'connect':
            self.reply('error', reason='Must connect first')
            return
        if msg == 'method':
            if (
                'method' not in kwargs
            ) or (
                'id' not in kwargs
            ):
                self.reply(
                    'error', error=400, reason='Malformed method invocation',
                )
                return

        # lookup method handler
        try:
            handler = getattr(self, 'recv_%s' % msg)
        except (AttributeError, UnicodeEncodeError):
            raise MeteorError(404, 'Method not found')

        # validate handler arguments
        validate_kwargs(handler, kwargs)

        # dispatch to handler
        handler(**kwargs)

    def send(self, data, tx_id=None):
        """Send `data` (raw string or EJSON payload) to WebSocket client."""
        # buffer data until we get pre-requisite data
        if tx_id is None:
            tx_id = self.get_tx_id()
        self._tx_buffer[tx_id] = data

        # de-queue messages from buffer
        while self._tx_next_id in self._tx_buffer:
            # pull next message from buffer
            data = self._tx_buffer.pop(self._tx_next_id)
            if self._tx_buffer:
                safe_call(self.logger.debug, 'TX found %d', self._tx_next_id)
            # advance next message ID
            self._tx_next_id = next(self._tx_next_id_gen)
            if not isinstance(data, str):
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
            safe_call(self.logger.debug, '> %s %r', self, data)
            try:
                self.ws.send(data)
            except geventwebsocket.WebSocketError:
                self.ws.close()
                self._tx_buffer.clear()
                break
        num_waiting = len(self._tx_buffer)
        if num_waiting > 10:
            safe_call(
                self.logger.warn,
                'TX received %d, waiting for %d, have %d waiting: %r.',
                tx_id, self._tx_next_id, num_waiting, self._tx_buffer,
            )

    def reply(self, msg, **kwargs):
        """Send EJSON reply to remote."""
        kwargs['msg'] = msg
        self.send(kwargs)

    def recv_connect(self, version=None, support=None, session=None):
        """DDP connect handler."""
        del session  # Meteor doesn't even use this!
        if self.connection is not None:
            raise MeteorError(
                400, 'Session already established.',
                self.connection.connection_id,
            )
        elif None in (version, support) or version not in self.versions:
            self.reply('failed', version=self.versions[0])
        elif version not in support:
            raise MeteorError(400, 'Client version/support mismatch.')
        else:
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
    recv_connect.err = 'Malformed connect'

    def recv_ping(self, id_=None):
        """DDP ping handler."""
        if id_ is None:
            self.reply('pong')
        else:
            self.reply('pong', id=id_)
    recv_ping.err = 'Malformed ping'

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
    recv_unsub.err = 'Malformed unsubscription'

    def recv_method(self, method, params, id_, randomSeed=None):
        """DDP method handler."""
        if randomSeed is not None:
            this.random_streams.random_seed = randomSeed
            this.alea_random = alea.Alea(randomSeed)
        self.api.method(method, params, id_)
        self.reply('updated', methods=[id_])
    recv_method.err = 'Malformed method invocation'
