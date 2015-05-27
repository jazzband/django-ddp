"""Django DDP WebSocket service."""

from __future__ import print_function, absolute_import

import collections
import os
import sys


Addr = collections.namedtuple('Addr', ['host', 'port'])


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
    import random
    import ejson

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


def serve(listen, debug=False, **ssl_args):
    """Spawn greenlets for handling websockets and PostgreSQL calls."""
    import signal
    from django.apps import apps
    from django.db import connection, close_old_connections
    from django.utils.module_loading import import_string
    from dddp.postgres import PostgresGreenlet
    from dddp.websocket import DDPWebSocketApplication
    import gevent
    import geventwebsocket

    # shutdown existing connections
    close_old_connections()

    # setup PostgresGreenlet to multiplex DB calls
    pgworker = PostgresGreenlet(connection, debug=debug)
    DDPWebSocketApplication.pgworker = pgworker

    # use settings.WSGI_APPLICATION or fallback to default Django WSGI app
    from django.conf import settings
    if hasattr(settings, 'WSGI_APPLICATION'):
        wsgi_name = settings.WSGI_APPLICATION
        wsgi_app = import_string(wsgi_name)
    else:
        from django.core.wsgi import get_wsgi_application
        wsgi_app = get_wsgi_application()
        wsgi_name = str(wsgi_app.__class__)

    resource = geventwebsocket.Resource(
        collections.OrderedDict([
            (r'/websocket', DDPWebSocketApplication),
            (r'^/sockjs/\d+/\w+/websocket$', DDPWebSocketApplication),
            (r'^/sockjs/\d+/\w+/xhr$', ddpp_sockjs_xhr),
            (r'^/sockjs/info$', ddpp_sockjs_info),
            (r'^/(?!(websocket|sockjs)/)', wsgi_app),
        ]),
    )

    # setup WebSocketServer to dispatch web requests
    webservers = [
        geventwebsocket.WebSocketServer(
            (host, port),
            resource,
            debug=debug,
            **{key:val for key, val in ssl_args.items() if val is not None}
        )
        for host, port
        in listen
    ]

    def killall(*args, **kwargs):
        """Kill all green threads."""
        pgworker.stop()
        for webserver in webservers:
            webserver.stop()

    # die gracefully with SIGINT or SIGQUIT
    gevent.signal(signal.SIGINT, killall)
    gevent.signal(signal.SIGQUIT, killall)

    print('=> Discovering DDP endpoints...')
    api = apps.get_app_config('dddp').api
    api.pgworker = pgworker
    DDPWebSocketApplication.api = api
    print(
        '\n'.join(
            '    %s' % api_path
            for api_path
            in sorted(api.api_path_map())
        ),
    )

    # start greenlets
    pgworker.start()
    print('=> Started PostgresGreenlet.')
    web_threads = [
        gevent.spawn(webserver.serve_forever)
        for webserver
        in webservers
    ]
    print('=> Started DDPWebSocketApplication.')
    print('=> Started your app (%s).' % wsgi_name)
    print('')
    for host, port in listen:
        print('=> App running at: http://%s:%d/' % (host, port))
    gevent.joinall(web_threads)
    pgworker.stop()
    gevent.joinall([pgworker])


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


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    django = parser.add_argument_group('Django Options')
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
        keyfile=namespace.keyfile,
        certfile=namespace.certfile,
    )


if __name__ == '__main__':
    from dddp import greenify
    greenify()
    main()
