django-ddp
==========

Django_/PostgreSQL_ implementation of the Meteor DDP service, allowing Meteor_ to subscribe to changes on Django_ models.  Released under the MIT license.


Requirements
------------
The core concept is that events are dispatched asynchronously to browsers using WebSockets_ and server-side using a PostgreSQL_ extension to the SQL syntax called NOTIFY (and its bretheren, LISTEN and UNLISTEN).  You must be using PostgreSQL_ with psycopg2_ in your Django_ project for django-ddp to work.  There is no requirement on any asynchronous framework such as Reddis or crossbar.io as they are simply not needed given the asynchronous support provided by PostgreSQL_ with psycopg2_.  As an added bonus, events dispatched using NOTIFY in a transaction are only emitted if the transaction is successfully committed.


Scalability
-----------
All database queries to support DDP events are done once by the server instance that has made changes via the Django ORM.  Django DDP multiplexes messages for active subscriptions, broadcasting an aggregated change message on channels specific to each Django model that has been published.

Peer servers subscribe to aggregate broadcast events which are de-multiplexed and dispatched to individual client connections.  No additional database queries are required for de-multiplexing or dispatch by peer servers.


Limitations
-----------
* No support for the SockJS protocol to support browsers that
  don't have WebSockets_ (see http://caniuse.com/websockets for
  supported browsers).

* Changes must be made via the Django ORM as django-ddp uses `Django
  signals`_ to receive model save/update signals.


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

If you'd like support for the Meteor Accounts package (ie: login/logout
with django.contrib.auth) consult the section on authentication below
and use the following line instead:

    # settings.py
    ...
    INSTALLED_APPS = list(INSTALLED_APPS) + ['dddp', 'dddp.accounts']

Add ddp.py to your Django application:

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

Connect your Meteor application to the Django DDP service:

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

In a separate terminal, start Meteor (from within your meteor
application directory):

.. code:: sh

    meteor


Adding API endpoints (server method definitions)
------------------------------------------------
API endpoints can be added by calling `register` method of the
dddp.api.API object from the ddp.py module of your Django app, on a
subclass of dddp.api.APIMixin - both dddp.api.Collection and
dddp.api.Publication are suitable, or you may define your own subclass
of dddp.api.APIMixin.  A good example of this can be seen in
dddp/accounts/ddp.py in the source of django-ddp.


Authentication
--------------
Authentication is provided using the standard meteor accounts system,
along with the `accounts-secure` package which turns off Meteor's
password hashing in favour of using TLS (HTTPS + WebSockets). This
ensures strong protection for all data over the wire.  Correctly using
TLS/SSL also protects your site against man-in-the-middle and replay
attacks - Meteor is vulnerable to both of these without using
encryption.

Add `dddp.accounts` to your `settings.INSTALLED_APPS` as described in
the example usage section above, then add `tysonclugg:accounts-secure`
to your Meteor application (from within your meteor application
directory):

.. code:: sh

    meteor add tysonclugg:accounts-secure

Then follow the normal procedure to add login/logout views to your
Meteor application.


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
