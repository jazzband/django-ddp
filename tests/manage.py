#!/usr/bin/env python
"""Entry point for Django DDP test project."""
import os
import sys

import dddp
dddp.greenify()

os.environ['DJANGO_SETTINGS_MODULE'] = 'test_project.settings'
sys.path.insert(0, os.path.dirname(__file__))


def run_tests():
    """Run the test suite."""
    import django
    from django.test.runner import DiscoverRunner
    django.setup()
    test_runner = DiscoverRunner(verbosity=2, interactive=False)
    failures = test_runner.run_tests(['.'])
    sys.exit(bool(failures))


def main(args):  # pragma: no cover
    """Execute a management command."""
    from django.core.management import execute_from_command_line
    execute_from_command_line(args)


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv)
