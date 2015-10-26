#!/usr/bin/env python
"""Django/PostgreSQL implementation of the Meteor DDP service."""
import platform
from setuptools import setup, find_packages

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
    "Framework :: Django :: 1.7",
    "Framework :: Django :: 1.8",
]

# Ensure correct dependencies between different python implementations.
IMPLEMENTATION_INSTALL_REQUIRES = {
    # extra requirements for CPython implementation
    'CPython': [
        'psycopg2>=2.5.4',
    ],
    # extra requirements for all other Python implementations
    None: [
        'psycopg2cffi>=2.7.2',
    ],
}

setup(
    name='django-ddp',
    version='0.17.1',
    description=__doc__,
    long_description=open('README.rst').read(),
    author='Tyson Clugg',
    author_email='tyson@clugg.net',
    url='https://github.com/commoncode/django-ddp',
    license='MIT',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'Django>=1.7',
        'gevent>=1.0',
        'gevent-websocket>=0.9,!=0.9.4',
        'meteor-ejson>=1.0',
        'psycogreen>=1.0',
        'django-dbarray>=0.2',
        'pybars3>=0.9.1',
    ] + IMPLEMENTATION_INSTALL_REQUIRES.get(
        platform.python_implementation(),
        IMPLEMENTATION_INSTALL_REQUIRES[None],  # default to non-CPython reqs
    ),
    entry_points={
        'console_scripts': [
            'dddp=dddp.main:main',
        ],
    },
    classifiers=CLASSIFIERS,
)
