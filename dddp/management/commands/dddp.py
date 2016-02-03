from django.core.management.base import BaseCommand
from ...main import addr,Addr


class Command(BaseCommand):
    help = "Runs a bbp as daemon"

    def add_arguments(self, parser):
        django = parser.add_argument_group('Django Options')
        # django.add_argument(
        #     '--verbosity', '-v', metavar='VERBOSITY', dest='verbosity', type=int,
        #     default=1,
        # )
        django.add_argument(
            '--noisy', '-n', metavar='NOISY', dest='noisy', type=int,
            default=1,
        )
        django.add_argument(
            '--debug-port', metavar='DEBUG_PORT', dest='debug_port', type=int,
            default=0,
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

    def handle(self,**options):
        from ...main import serve
        serve(
            options["listen"] or [Addr('localhost', 8000)],
            debug_port=options["debug_port"],
            keyfile=options["keyfile"],
            certfile=options["certfile"],
            verbosity=options["verbosity"],
        )
