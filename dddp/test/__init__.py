# This file mainly exists to allow `python setup.py test` to work.
import os
import sys

import dddp
import django
from django.test.utils import get_runner
from django.conf import settings


def run_tests():
    os.environ['DJANGO_SETTINGS_MODULE'] = 'dddp.test.test_project.settings'
    dddp.greenify()
    django.setup()
    test_runner = get_runner(settings)()
    failures = test_runner.run_tests(['dddp', 'dddp.test.django_todos'])
    sys.exit(bool(failures))
