"""Django Todos test suite."""

import doctest
import os
import unittest

os.environ['DJANGO_SETTINGS_MODULE'] = 'dddp.test.test_project.settings'

DOCTEST_MODULES = [
]


class NoOpTest(unittest.TestCase):
    def test_noop(self):
        assert True


def load_tests(loader, tests, pattern):
    """Specify which test cases to run."""
    del pattern
    suite = unittest.TestSuite()
    # add all TestCase classes from this (current) module
    for attr in globals().values():
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
