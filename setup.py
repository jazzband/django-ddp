#!/usr/bin/env python
"""Django/PostgreSQL implementation of the Meteor server."""

# stdlib
import os.path
import posixpath  # all path specs in this file are UNIX-style paths
import shutil
import subprocess
from distutils import log
from distutils.version import StrictVersion
import setuptools.command.build_py
import setuptools.command.build_ext

# pypi
import setuptools

# setuptools 18.5 introduces support for the `platform_python_implementation`
# environment marker: https://github.com/jaraco/setuptools/pull/28
__requires__ = 'setuptools>=18.5'

assert StrictVersion(setuptools.__version__) >= StrictVersion('18.5'), \
    'Installation from source requires setuptools>=18.5.'

SETUP_DIR = os.path.dirname(__file__)


class build_meteor(setuptools.command.build_py.build_py):

    """Build a Meteor project."""

    user_options = [
        ('meteor=', None, 'path to `meteor` executable (default: meteor)'),
        ('meteor-debug', None, 'meteor build with `--debug`'),
        ('no-prune-npm', None, "don't prune meteor npm build directories"),
        ('build-lib', 'd', 'directory to "build" (copy) to'),
    ]

    negative_opt = []

    meteor = None
    meteor_debug = None
    build_lib = None
    package_dir = None
    meteor_builds = None
    no_prune_npm = None
    inplace = None

    def initialize_options(self):
        """Set command option defaults."""
        setuptools.command.build_py.build_py.initialize_options(self)
        self.meteor = 'meteor'
        self.meteor_debug = False
        self.build_lib = None
        self.package_dir = None
        self.meteor_builds = []
        self.no_prune_npm = None
        self.inplace = True

    def finalize_options(self):
        """Update command options."""
        # Get all the information we need to install pure Python modules
        # from the umbrella 'install' command -- build (source) directory,
        # install (target) directory, and whether to compile .py files.
        self.set_undefined_options(
            'build',
            ('build_lib', 'build_lib'),
        )
        self.set_undefined_options(
            'build_py',
            ('package_dir', 'package_dir'),
        )
        setuptools.command.build_py.build_py.finalize_options(self)

    @staticmethod
    def has_meteor_builds(distribution):
        """Returns `True` if distribution has meteor projects to be built."""
        return bool(
            distribution.command_options['build_meteor']['meteor_builds']
        )

    def get_package_dir(self, package):
        res = setuptools.command.build_py.orig.build_py.get_package_dir(
            self, package,
        )
        if self.distribution.src_root is not None:
            return os.path.join(self.distribution.src_root, res)
        return res

    def run(self):
        """Peform build."""
        for (package, source, target, extra_args) in self.meteor_builds:
            src_dir = self.get_package_dir(package)
            # convert UNIX-style paths to directory names
            project_dir = self.path_to_dir(src_dir, source)
            target_dir = self.path_to_dir(src_dir, target)
            output_dir = self.path_to_dir(
                os.path.abspath(SETUP_DIR if self.inplace else self.build_lib),
                target_dir,
            )
            # construct command line.
            cmdline = [self.meteor, 'build', '--directory', output_dir]
            no_prune_npm = self.no_prune_npm
            if extra_args[:1] == ['--no-prune-npm']:
                no_prune_npm = True
                extra_args[:1] = []
            if self.meteor_debug and '--debug' not in cmdline:
                cmdline.append('--debug')
            cmdline.extend(extra_args)
            # execute command
            log.info(
                'building meteor app %r (%s)', project_dir, ' '.join(cmdline),
            )
            subprocess.check_call(cmdline, cwd=project_dir)
            if not no_prune_npm:
                # django-ddp doesn't use bundle/programs/server/npm cruft
                npm_build_dir = os.path.join(
                    output_dir, 'bundle', 'programs', 'server', 'npm',
                )
                log.info('pruning meteor npm build %r', npm_build_dir)
                shutil.rmtree(npm_build_dir)

    @staticmethod
    def path_to_dir(*path_args):
        """Convert a UNIX-style path into platform specific directory spec."""
        return os.path.join(
            *list(path_args[:-1]) + path_args[-1].split(posixpath.sep)
        )


class build_py(setuptools.command.build_py.build_py):

    def run(self):
        if build_meteor.has_meteor_builds(self.distribution):
            self.reinitialize_command('build_meteor', inplace=False)
            self.run_command('build_meteor')
        return setuptools.command.build_py.build_py.run(self)


class build_ext(setuptools.command.build_ext.build_ext):

    def run(self):
        if build_meteor.has_meteor_builds(self.distribution):
            self.reinitialize_command('build_meteor', inplace=True)
            self.run_command('build_meteor')
        return setuptools.command.build_ext.build_ext.run(self)


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
    test_suite='dddp.test.manage.run_tests',
    tests_require=[
        'requests',
        'websocket_client',
    ],
    cmdclass={
        'build_ext': build_ext,
        'build_py': build_py,
        'build_meteor': build_meteor,
    },
    options={
        'bdist_wheel': {
            'universal': '1',
        },
        'build_meteor': {
            'meteor_builds': [
                ('dddp.test', 'meteor_todos', 'build', []),
            ],
        },
    },
)
