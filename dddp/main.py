"""Django DDP WebSocket service."""

from __future__ import absolute_import, print_function

import argparse
import collections
import os
import signal

import gevent
from gevent.backdoor import BackdoorServer
import gevent.event
import gevent.pywsgi
import geventwebsocket
import geventwebsocket.handler


Addr = collections.namedtuple('Addr', ['host', 'port'])


def common_headers(environ, **kwargs):
    """Return list of common headers for SockJS HTTP responses."""
    return [
        # DDP doesn't use cookies or HTTP level auth, so CSRF attacks are
        # ineffective.  We can safely allow cross-domain DDP connections and
        # developers may choose to allow anonymous access to publications and
        # RPC methods as they see fit.  More to the point, developers should
        # restrict access to publications and RPC endpoints as appropriate.
        ('Access-Control-Allow-Origin', '*'),
        ('Access-Control-Allow-Credentials', 'false'),
        ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0'),
        ('Connection', 'keep-alive'),
        ('Vary', 'Origin'),
    ]


def ddpp_sockjs_xhr(environ, start_response):
    """Dummy method that doesn't handle XHR requests."""
    start_response(
        '404 Not found',
        [
            ('Content-Type', 'text/plain; charset=UTF-8'),
        ] + common_headers(environ),
    )
    yield 'No.'


def ddpp_sockjs_info(environ, start_response):
    """Inform client that WebSocket service is available."""
    import random
    import ejson

    start_response(
        '200 OK',
        [
            ('Content-Type', 'application/json; charset=UTF-8'),
        ] + common_headers(environ),
    )
    yield ejson.dumps(collections.OrderedDict([
        ('websocket', True),
        ('origins', [
            '*:*',
        ]),
        ('cookie_needed', False),
        ('entropy', random.getrandbits(32)),
    ]))


class DDPLauncher(object):

    """Orchestrate the setup and launching of DDP greenlets in a sane manner."""

    pgworker = None

    def __init__(self, debug=False, verbosity=1):
        """
        Spawn greenlets for handling websockets and PostgreSQL calls.

        Only one pgworker should be started for any process, and ideally only
        one instance per node as well (ie: use IPC to communicate events between
        processes on the same host).  This class handles the former (per
        process), per host IPC is an excercise left to you, dear reader - pull
        requests are of course welcome.  ;)

        For the record, there's no technical reason that you can't have multiple
        pgworker instances running on one host (or even one process), it's just
        inefficient to send exactly the same traffic multiple times between your
        web servers and your database host.
        """
        import logging
        from django.apps import apps
        from django.utils.module_loading import import_string
        from dddp.websocket import DDPWebSocketApplication

        self.verbosity = verbosity
        self._stop_event = gevent.event.Event()
        self._stop_event.set()  # start in stopped state.
        self.logger = logging.getLogger('dddp.launcher')

        if DDPLauncher.pgworker is None:
            from django.db import connection, close_old_connections
            from dddp.postgres import PostgresGreenlet
            # shutdown existing connections
            close_old_connections()

            DDPLauncher.pgworker = PostgresGreenlet(connection)

        # use settings.WSGI_APPLICATION or fallback to default Django WSGI app
        from django.conf import settings
        self.wsgi_app = None
        if hasattr(settings, 'WSGI_APPLICATION'):
            self.wsgi_name = settings.WSGI_APPLICATION
            try:
                self.wsgi_app = import_string(self.wsgi_name)
            except ImportError:
                pass
        if self.wsgi_app is None:
            from django.core.wsgi import get_wsgi_application
            self.wsgi_app = get_wsgi_application()
            self.wsgi_name = str(self.wsgi_app.__class__)

        self.api = apps.get_app_config('dddp').api
        self.api.pgworker = DDPLauncher.pgworker
        DDPWebSocketApplication.api = self.api

        # setup PostgresGreenlet to multiplex DB calls
        DDPWebSocketApplication.pgworker = self.pgworker

        self.resource = geventwebsocket.Resource(
            collections.OrderedDict([
                (r'/websocket', DDPWebSocketApplication),
                (r'^/sockjs/\d+/\w+/websocket$', DDPWebSocketApplication),
                (r'^/sockjs/\d+/\w+/xhr$', ddpp_sockjs_xhr),
                (r'^/sockjs/info$', ddpp_sockjs_info),
                (r'^/(?!(websocket|sockjs)/)', self.wsgi_app),
            ]),
        )

        self.servers = []
        self.threads = []

    def print(self, msg, *args, **kwargs):
        """Print formatted msg if verbosity set at 1 or above."""
        if self.verbosity >= 1:
            print(msg, *args, **kwargs)

    def add_web_servers(self, listen_addrs, debug=False, **ssl_args):
        """Add WebSocketServer for each (host, port) in listen_addrs."""
        self.servers.extend(
            self.get_web_server(listen_addr, debug=debug, **ssl_args)
            for listen_addr in listen_addrs
        )

    def get_web_server(self, listen_addr, debug=False, **ssl_args):
        """Setup WebSocketServer on listen_addr (host, port)."""
        return geventwebsocket.WebSocketServer(
            listen_addr,
            self.resource,
            debug=debug,
            **{key: val for key, val in ssl_args.items() if val is not None}
        )

    def get_backdoor_server(self, listen_addr, **context):
        """Add a backdoor (debug) server."""
        from django.conf import settings
        local_vars = {
            'launcher': self,
            'servers': self.servers,
            'pgworker': self.pgworker,
            'stop': self.stop,
            'api': self.api,
            'resource': self.resource,
            'settings': settings,
            'wsgi_app': self.wsgi_app,
            'wsgi_name': self.wsgi_name,
        }
        local_vars.update(context)
        return BackdoorServer(
            listen_addr, banner='Django DDP', locals=local_vars,
        )

    def stop(self):
        """Stop all green threads."""
        self.logger.debug('PostgresGreenlet stop')
        self._stop_event.set()
        # ask all threads to stop.
        for server in self.servers + [DDPLauncher.pgworker]:
            self.logger.debug('Stopping %s', server)
            server.stop()
        # wait for all threads to stop.
        gevent.joinall(self.threads + [DDPLauncher.pgworker])
        self.threads = []

    def start(self):
        """Run PostgresGreenlet and web/debug servers."""
        self.logger.debug('PostgresGreenlet start')
        self._stop_event.clear()
        self.print('=> Discovering DDP endpoints...')
        if self.verbosity > 1:
            for api_path in sorted(self.api.api_path_map()):
                print('    %s' % api_path)

        # start greenlets
        self.pgworker.start()
        self.print('=> Started PostgresGreenlet.')
        for server in self.servers:
            thread = gevent.spawn(server.serve_forever)
            gevent.sleep()  # yield to thread in case it can't start
            self.threads.append(thread)
            if thread.dead:
                # thread died, stop everything and re-raise the exception.
                self.stop()
                thread.get()
            if isinstance(server, geventwebsocket.WebSocketServer):
                self.print(
                    '=> App running at: %s://%s:%d/' % (
                        'https' if server.ssl_enabled else 'http',
                        server.server_host,
                        server.server_port,
                    ),
                )
            elif isinstance(server, gevent.backdoor.BackdoorServer):
                self.print(
                    '=> Debug service running at: telnet://%s:%d/' % (
                        server.server_host,
                        server.server_port,
                    ),
                )
        self.print('=> Started your app (%s).' % self.wsgi_name)

    def run(self):
        """Run DDP greenlets."""
        self.logger.debug('PostgresGreenlet run')
        self.start()
        self._stop_event.wait()
        # wait for all threads to stop.
        gevent.joinall(self.threads + [DDPLauncher.pgworker])
        self.threads = []


def addr(val, default_port=8000, defualt_host='localhost'):
    """
    Convert a string of format host[:port] into Addr(host, port).

    >>> addr('0:80')
    Addr(host='0', port=80)

    >>> addr('127.0.0.1:80')
    Addr(host='127.0.0.1', port=80)

    >>> addr('0.0.0.0', default_port=8000)
    Addr(host='0.0.0.0', port=8000)
    """
    import re
    import socket

    match = re.match(r'\A(?P<host>.*?)(:(?P<port>(\d+|\w+)))?\Z', val)
    if match is None:
        raise argparse.ArgumentTypeError(
            '%r is not a valid host[:port] address.' % val
        )
    host, port = match.group('host', 'port')

    if not host:
        host = defualt_host

    if not port:
        port = default_port
    elif port.isdigit():
        port = int(port)
    else:
        port = socket.getservbyname(port)

    return Addr(host, port)


def serve(listen, verbosity=1, debug_port=0, **ssl_args):
    """Spawn greenlets for handling websockets and PostgreSQL calls."""
    launcher = DDPLauncher(debug=verbosity == 3, verbosity=verbosity)
    if debug_port:
        launcher.servers.append(
            launcher.get_backdoor_server('localhost:%d' % debug_port)
        )
    launcher.add_web_servers(listen, **ssl_args)
    # die gracefully with SIGINT or SIGQUIT
    sigmap = {
        val: name
        for name, val
        in vars(signal).items()
        if name.startswith('SIG')
    }

    def sighandler(signum=None, frame=None):
        """Signal handler"""
        launcher.logger.info(
            'Received signal %s in frame %r',
            sigmap.get(signum, signum),
            frame,
        )
        launcher.stop()
    for signum in [signal.SIGINT, signal.SIGQUIT]:
        gevent.signal(signum, sighandler)
    launcher.run()


def main():
    """Main entry point for `dddp` command."""
    parser = argparse.ArgumentParser(description=__doc__)
    django = parser.add_argument_group('Django Options')
    django.add_argument(
        '--verbosity', '-v', metavar='VERBOSITY', dest='verbosity', type=int,
        default=1,
    )
    django.add_argument(
        '--debug-port', metavar='DEBUG_PORT', dest='debug_port', type=int,
        default=0,
    )
    django.add_argument(
        '--settings', metavar='SETTINGS', dest='settings',
        help="The Python path to a settings module, e.g. "
        "\"myproject.settings.main\". If this isn't provided, the "
        "DJANGO_SETTINGS_MODULE environment variable will be used.",
    )
    http = parser.add_argument_group('HTTP Options')
    http.add_argument(
        'listen', metavar='address[:port]', nargs='*', type=addr,
        help='Listening address for HTTP(s) server.',
    )
    ssl = parser.add_argument_group('SSL Options')
    ssl.add_argument('--ssl-version', metavar='SSL_VERSION', dest='ssl_version',
                     help="SSL version to use (see stdlib ssl module's) [3]",
                     choices=['1', '2', '3'], default='3')
    ssl.add_argument('--certfile', metavar='FILE', dest='certfile',
                     help="SSL certificate file [None]")
    ssl.add_argument('--ciphers', metavar='CIPHERS', dest='ciphers',
                     help="Ciphers to use (see stdlib ssl module's) [TLSv1]")
    ssl.add_argument('--ca-certs', metavar='FILE', dest='ca_certs',
                     help="CA certificates file [None]")
    ssl.add_argument('--keyfile', metavar='FILE', dest='keyfile',
                     help="SSL key file [None]")
    namespace = parser.parse_args()
    if namespace.settings:
        os.environ['DJANGO_SETTINGS_MODULE'] = namespace.settings
    serve(
        namespace.listen or [Addr('localhost', 8000)],
        debug_port=namespace.debug_port,
        keyfile=namespace.keyfile,
        certfile=namespace.certfile,
        verbosity=namespace.verbosity,
    )


if __name__ == '__main__':
    from dddp import greenify
    greenify()
    main()
