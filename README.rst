django-ddp
==========

Django_/PostgreSQL_ implementation of the Meteor DDP service, allowing Meteor_ to subscribe to changes on Django_ models.  Released under the MIT license.


Requirements
------------
The core concept is that events are dispatched asynchronously to browsers using WebSockets_ and server-side using a PostgreSQL_ extension to the SQL syntax called NOTIFY (and its bretheren, LISTEN and UNLISTEN).  You must be using PostgreSQL_ with psycopg2_ in your Django_ project for django-ddp to work.  There is no requirement on any asynchronous framework such as Reddis or crossbar.io as they are simply not needed given the asynchronous support provided by PostgreSQL_ with psycopg2_.  As an added bonus, events dispatched using NOTIFY in a transaction are only emitted if the transaction is successfully committed.


Scalability
-----------
All database queries to support DDP events are done once by the server instance that has made changes via the Django ORM.  Django DDP multiplexes messages for active subscriptions, broadcasting an aggregated change message on channels specific to each Django model that has been published.

Peer servers subscribe to aggregate broadcast events only for channels (Django models) that their connected clients subscribe to.  The aggregate events received are de-multiplexed and dispatched to individual client connections.  No additional database queries are required for de-multiplexing or dispatch by peer servers.


Limitations
-----------
The current release series only supports DDP via WebSockets_.  Future
development may resolve this by using SockJS, to support browsers that
don't have WebSockets.

Changes must be made via the Django ORM as django-ddp uses `Django signals`_ to receive model save/update signals.


Installation
------------

Install the latest release from pypi (recommended):

.. code:: sh

    pip install django-ddp

Clone and use development version direct from GitHub (to test pre-release code):

.. code:: sh

    pip install -e git+https://github.com/commoncode/django-ddp@develop#egg=django-ddp


Example usage
-------------

Add 'dddp' to your settings.INSTALLED_APPS:

.. code:: python

    # settings.py
    ...
    INSTALLED_APPS = list(INSTALLED_APPS) + ['dddp']

Add ddp.py to your Django app:

.. code:: python

    # bookstore/ddp.py
    
    from dddp.api import API, Collection, Publication
    from bookstore import models
    
    class Book(Collection):
        model = models.Book
    
    
    class Author(Collection):
        model = models.Author
    
    
    class AllBooks(Publication):
        queries = [
            models.Author.objects.all(),
            models.Book.objects.all(),
        ]
    
    
    class BooksByAuthorEmail(Publication):
        def get_queries(self, author_email):
            return [
                models.Author.objects.filter(
                    email=author_email,
                ),
                models.Book.objects.filter(
                    author__email=author_email,
                ),
            ]
    
    
    API.register(
        [Book, Author, AllBooks, BooksByAuthorEmail]
    )

Connect your Meteor app to the Django DDP service:

.. code:: javascript

    // bookstore.js
    if (Meteor.isClient) {
        // Connect to Django DDP service
        Django = DDP.connect('http://'+window.location.hostname+':8000/');
        // Create local collections for Django models received via DDP
        Authors = new Mongo.Collection("bookstore.author", {connection: Django});
        Books = new Mongo.Collection("bookstore.book", {connection: Django});
        // Subscribe to all books by Janet Evanovich
        Django.subscribe('BooksByAuthorEmail', 'janet@evanovich.com');
    }

Start the Django DDP service:

.. code:: sh

    DJANGO_SETTINGS_MODULE=myproject.settings dddp

In a separate terminal, start Meteor (from within your meteor app directory):

.. code:: sh

    meteor


Contributors
------------
`Tyson Clugg <https://github.com/tysonclugg>`_
    * Author, conceptual design.

`MEERQAT <http://meerqat.com.au/>`_
    * Project sponsor - many thanks for allowing this to be released under an open source license!

`David Burles <https://github.com/dburles>`_
    * Expert guidance on how DDP works in Meteor.

`Brenton Cleeland <https://github.com/sesh>`_
    * Great conversations around how collections and publications can limit visibility of published documents to specific users.

`Muhammed Thanish <https://github.com/mnmtanish>`_
    * Making the `DDP Test Suite <https://github.com/meteorhacks/ddptest>`_ available.

.. _Django: https://www.djangoproject.com/
.. _Django signals: https://docs.djangoproject.com/en/stable/topics/signals/
.. _PostgreSQL: http://postgresql.org/
.. _psycopg2: http://initd.org/psycopg/
.. _WebSockets: http://www.w3.org/TR/websockets/
.. _Meteor: http://meteor.com/:0
