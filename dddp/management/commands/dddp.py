"""Django DDP WebSocket service."""

from __future__ import print_function, absolute_import

import collections
import optparse
import random
import signal
import socket

from django.core.management.base import BaseCommand
from django.db import connection, close_old_connections
import ejson
import gevent
import gevent.monkey
import gevent.queue
import gevent.select
import geventwebsocket
import psycogreen.gevent

from dddp.postgres import PostgresGreenlet
from dddp.websocket import DDPWebSocketApplication


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
    r'/websocket': DDPWebSocketApplication,
    r'^/sockjs/\d+/\w+/websocket$': DDPWebSocketApplication,
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
        # shutdown existing connections, mokey patch stdlib for gevent.
        close_old_connections()
        gevent.monkey.patch_all()
        psycogreen.gevent.patch_psycopg()

        # setup PostgresGreenlet to multiplex DB calls
        postgres = PostgresGreenlet(connection)
        DDPWebSocketApplication.pgworker = postgres

        # setup WebSocketServer to dispatch web requests
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
        postgres.start()
        print('=> Started PostgresGreenlet.')
        web = gevent.spawn(webserver.serve_forever)
        print('=> Started your app.')
        print('')
        print('=> App running at: http://%s:%d/' % (host, port))
        gevent.joinall([postgres, web])
