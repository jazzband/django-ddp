#!/usr/bin/env python
"""Django/PostgreSQL implementation of the Meteor DDP service."""
import os.path
from setuptools import setup, find_packages

setup(
    name='django-ddp',
    version='0.9.1',
    description=__doc__,
    long_description=open('README.rst').read(),
    author='Tyson Clugg',
    author_email='tyson@clugg.net',
    url='https://github.com/commoncode/django-ddp',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'Django>=1.7',
        'psycopg2>=2.5.4',
        'gevent>=1.0',
        'gevent-websocket>=0.9,!=0.9.4',
        'meteor-ejson>=1.0',
        'psycogreen>=1.0',
        'django-dbarray>=0.2',
        'pybars3>=0.9.1',
    ],
    entry_points={
        'console_scripts': [
            'dddp=dddp.main:main',
        ],
    },
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 3",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Software Development :: Libraries",
    ],
)
