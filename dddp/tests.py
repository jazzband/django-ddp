"""Django DDP test suite."""
from __future__ import unicode_literals

import doctest
import errno
import os
import socket
import unittest
from django.test import TestCase
import dddp.alea
from dddp.main import DDPLauncher
# pylint: disable=E0611, F0401
from six.moves.urllib_parse import urljoin

os.environ['DJANGO_SETTINGS_MODULE'] = 'dddp.test.test_project.settings'

DOCTEST_MODULES = [
    dddp.alea,
]


class DDPServerTestCase(TestCase):

    """Test case that starts a DDP server."""

    server_addr = '127.0.0.1'
    server_port_range = range(8000, 8080)
    ssl_certfile_path = None
    ssl_keyfile_path = None

    def setUp(self):
        """Fire up the DDP server."""
        self.server_port = 8000
        kwargs = {}
        if self.ssl_certfile_path:
            kwargs['certfile'] = self.ssl_certfile_path
        if self.ssl_keyfile_path:
            kwargs['keyfile'] = self.ssl_keyfile_path
        self.scheme = 'https' if kwargs else 'http'
        for server_port in self.server_port_range:
            self.server = DDPLauncher(debug=True)
            self.server.add_web_servers(
                [
                    (self.server_addr, server_port),
                ],
                **kwargs
            )
            try:
                self.server.start()
                self.server_port = server_port
                return  # server started
            except socket.error as err:
                if err.errno != errno.EADDRINUSE:
                    raise  # error wasn't "address in use", re-raise.
                continue  # port in use, try next port.
        raise RuntimeError('Failed to start DDP server.')

    def tearDown(self):
        """Shut down the DDP server."""
        self.server.stop()

    def url(self, path):
        """Return full URL for given path."""
        return urljoin(
            '%s://%s:%d' % (self.scheme, self.server_addr, self.server_port),
            path,
        )


class LaunchTestCase(DDPServerTestCase):

    """Test that server launches and handles GET request."""

    def test_get(self):
        """Perform HTTP GET."""
        import requests
        resp = requests.get(self.url('/'))
        self.assertEqual(resp.status_code, 200)


def load_tests(loader, tests, pattern):
    """Specify which test cases to run."""
    del pattern
    suite = unittest.TestSuite()
    # add all TestCase classes from this (current) module
    for attr in globals().values():
        if attr is DDPServerTestCase:
            continue  # not meant to be executed, is has no tests.
        try:
            if not issubclass(attr, unittest.TestCase):
                continue  # not subclass of TestCase
        except TypeError:
            continue  # not a class
        tests = loader.loadTestsFromTestCase(attr)
        suite.addTests(tests)
    # add doctests defined in DOCTEST_MODULES
    for doctest_module in DOCTEST_MODULES:
        suite.addTest(doctest.DocTestSuite(doctest_module))
    return suite
