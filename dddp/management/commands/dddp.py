"""Django DDP WebSocket service."""

from __future__ import print_function, absolute_import

import collections
import inspect
import optparse
import random
import signal
import socket

from django.core.management import get_commands, load_command_class
from django.core.management.base import BaseCommand
from django.db import connection, close_old_connections
from django.utils.module_loading import import_string
import ejson
import gevent
import gevent.monkey
import gevent.queue
import gevent.select
import geventwebsocket
import psycogreen.gevent

from dddp import autodiscover
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


app_name = get_commands()['runserver']
if isinstance(app_name, BaseCommand):
    command_class = app_name
else:
    command_class = load_command_class(app_name, 'runserver')
command_class = command_class.__class__


class Command(command_class):

    """Command to run DDP web service."""

    args = 'HOST PORT'
    help = 'Run DDP service'

    def run(self, *args, **options):
        """Spawn greenlets for handling websockets and PostgreSQL calls."""
        # shutdown existing connections, mokey patch stdlib for gevent.
        close_old_connections()
        gevent.monkey.patch_all()
        psycogreen.gevent.patch_psycopg()

        debug = int(options['verbosity']) > 1

        # setup PostgresGreenlet to multiplex DB calls
        postgres = PostgresGreenlet(connection, debug=debug)
        DDPWebSocketApplication.pgworker = postgres

        # use settings.WSGI_APPLICATION or fallback to default Django WSGI app
        from django.conf import settings
        wsgi_app = self.get_handler(*args, **options)
        if hasattr(settings, 'WSGI_APPLICATION'):
            wsgi_name = settings.WSGI_APPLICATION
        else:
            wsgi_name = str(wsgi_app.__class__)

        resource = geventwebsocket.Resource({
            r'/websocket': DDPWebSocketApplication,
            r'^/sockjs/\d+/\w+/websocket$': DDPWebSocketApplication,
            r'^/sockjs/\d+/\w+/xhr$': ddpp_sockjs_xhr,
            r'^/sockjs/info$': ddpp_sockjs_info,
            r'^/(?!(websocket|sockjs)/)': wsgi_app,
        })

        # setup WebSocketServer to dispatch web requests
        host = self.addr
        port = self.port
        if port.isdigit():
            port = int(port)
        else:
            port = socket.getservbyname(port)
        webserver = geventwebsocket.WebSocketServer(
            (host, port),
            resource,
            debug=debug,
        )

        def killall(*args, **kwargs):
            """Kill all green threads."""
            postgres.stop()
            webserver.stop()

        # die gracefully with SIGINT or SIGQUIT
        gevent.signal(signal.SIGINT, killall)
        gevent.signal(signal.SIGQUIT, killall)

        print('=> Discovering DDP endpoints...')
        ddp = autodiscover()
        ddp.pgworker = postgres
        print(
            '\n'.join(
                '    %s' % api_path
                for api_path
                in sorted(ddp.api_path_map())
            ),
        )

        # start greenlets
        postgres.start()
        print('=> Started PostgresGreenlet.')
        web = gevent.spawn(webserver.serve_forever)
        print('=> Started DDPWebSocketApplication.')
        print('=> Started your app (%s).' % wsgi_name)
        print('')
        print('=> App running at: http://%s:%d/' % (host, port))
        gevent.joinall([postgres, web])
