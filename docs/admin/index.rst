***********************
Administration Handbook
***********************

This section is aimed at DevOps and project administrators to assist in 
installing and maintaining a site using Django DDP.

Requirements
============

You must be using PostgreSQL_ with psycopg2_ in your Django_ project for 
django-ddp to work.  There is no requirement on any asynchronous 
framework such as Reddis or crossbar.io as they are simply not needed 
given the asynchronous support provided by PostgreSQL_ with psycopg2_.


Installation
============

Install the latest release from pypi (recommended):

.. code:: sh

    pip install django-ddp

Don't forget to add `dddp` to your `requirements.txt` and/or the 
`install_requires` section in `setup.py` for your project as necessary.

Clone and use development version direct from GitHub to test pre-release 
code (no GitHub account required):

.. code:: sh

    pip install -e 
    git+https://github.com/commoncode/django-ddp@develop#egg=django-ddp


.. _Django: https://www.djangoproject.com/
.. _Django signals: https://docs.djangoproject.com/en/stable/topics/signals/
.. _Gevent: http://www.gevent.org/
.. _PostgreSQL: http://postgresql.org/
.. _psycopg2: http://initd.org/psycopg/
.. _WebSockets: http://www.w3.org/TR/websockets/
