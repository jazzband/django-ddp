#!/usr/bin/env python
"""Django/PostgreSQL implementation of the Meteor server."""

import os.path
import setuptools
import subprocess
from distutils import log
from distutils.version import StrictVersion
from distutils.command.build import build

# setuptools 18.5 introduces support for the `platform_python_implementation`
# environment marker: https://github.com/jaraco/setuptools/pull/28
__requires__ = 'setuptools>=18.5'

assert StrictVersion(setuptools.__version__) >= StrictVersion('18.5'), \
    'Installation from source requires setuptools>=18.5.'


class Build(build):

    """Build all files of a package."""

    def run(self):
        """Build our package."""
        cmdline = [
            'meteor',
            'build',
            '--directory',
            '../build',
        ]
        meteor_dir = os.path.join(
            os.path.dirname(__file__),
            'dddp',
            'test',
            'meteor_todos',
        )
        log.info('Building meteor app %r (%s)', meteor_dir, ' '.join(cmdline))
        subprocess.check_call(cmdline, cwd=meteor_dir)
        return build.run(self)


CLASSIFIERS = [
    # Beta status until 1.0 is released
    "Development Status :: 4 - Beta",

    # Who and what the project is for
    "Intended Audience :: Developers",
    "Topic :: Database",
    "Topic :: Internet",
    "Topic :: Internet :: WWW/HTTP",
    "Topic :: Internet :: WWW/HTTP :: Browsers",
    "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
    "Topic :: Internet :: WWW/HTTP :: Dynamic Content :: CGI Tools/Libraries",
    "Topic :: Internet :: WWW/HTTP :: HTTP Servers",
    "Topic :: Internet :: WWW/HTTP :: Session",
    "Topic :: Internet :: WWW/HTTP :: WSGI",
    "Topic :: Internet :: WWW/HTTP :: WSGI :: Server",
    "Topic :: Software Development :: Libraries",
    "Topic :: Software Development :: Object Brokering",
    "Topic :: System :: Distributed Computing",

    # License classifiers
    "License :: OSI Approved :: MIT License",
    "License :: DFSG approved",
    "License :: OSI Approved",

    # Generally, we support the following.
    "Programming Language :: Python",
    "Programming Language :: Python :: 2",
    "Programming Language :: Python :: 3",
    "Framework :: Django",

    # Specifically, we support the following releases.
    "Programming Language :: Python :: 2.7",
    "Programming Language :: Python :: 3.2",
    "Programming Language :: Python :: 3.3",
    "Programming Language :: Python :: 3.4",
    "Framework :: Django :: 1.8",
    "Framework :: Django :: 1.9",
]

setuptools.setup(
    name='django-ddp',
    version='0.19.0',
    description=__doc__,
    long_description=open('README.rst').read(),
    author='Tyson Clugg',
    author_email='tyson@clugg.net',
    url='https://github.com/django-ddp/django-ddp',
    keywords=[
        'django ddp meteor websocket websockets realtime real-time live '
        'liveupdate live-update livequery live-query'
    ],
    license='MIT',
    packages=setuptools.find_packages(),
    include_package_data=True,  # install data files specified in MANIFEST.in
    zip_safe=False,  # TODO: Move dddp.test into it's own package.
    setup_requires=[
        # packages required to run the setup script
        __requires__,
    ],
    install_requires=[
        'Django>=1.8',
        'django-dbarray>=0.2',
        'meteor-ejson>=1.0',
        'psycogreen>=1.0',
        'pybars3>=0.9.1',
        'six>=1.10.0',
    ],
    extras_require={
        # We need gevent version dependent upon environment markers, but the
        # extras_require seem to be a separate phase from setup/install of
        # install_requires.  So we specify gevent-websocket (which depends on
        # gevent) here in order to honour environment markers.
        '': [
            'gevent-websocket>=0.9,!=0.9.4',
        ],
        # Django 1.9 doesn't support Python 3.3
        ':python_version=="3.3"': [
            'Django<1.9',
        ],
        # CPython < 3.0 can use gevent 1.0
        ':platform_python_implementation=="CPython" and python_version<"3.0"': [
            'gevent>=1.0',
        ],
        # everything else needs gevent 1.1
        ':platform_python_implementation!="CPython" or python_version>="3.0"': [
            'gevent>=1.1rc2',
        ],
        # CPython can use plain old psycopg2
        ':platform_python_implementation=="CPython"': [
            'psycopg2>=2.5.4',
        ],
        # everything else must use psycopg2cffi
        ':platform_python_implementation != "CPython"': [
            'psycopg2cffi>=2.7.2',
        ],
        'develop': [
            # things you need to distribute a wheel from source (`make dist`)
            'Sphinx>=1.3.3',
            'Sphinx-PyPI-upload>=0.2.1',
            'twine>=1.6.4',
            'sphinxcontrib-dashbuilder>=0.1.0',
        ],
    },
    entry_points={
        'console_scripts': [
            'dddp=dddp.main:main',
        ],
    },
    classifiers=CLASSIFIERS,
    test_suite='dddp.test.run_tests',
    tests_require=[
        'requests',
    ],
    cmdclass={
        'build': Build,
    },
)
