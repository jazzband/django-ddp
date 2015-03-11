#!/usr/bin/env python
"""Django/PostgreSQL implementation of the Meteor DDP service."""
import os.path
from setuptools import setup, find_packages

setup(
    name='django-ddp',
    version='0.1.0',
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
    ],
    classifiers=[
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 3",
        "Topic :: Internet :: WWW/HTTP",
    ],
)
