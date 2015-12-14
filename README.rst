==========
Django DDP
==========

`Django DDP`_ is a Django_/PostgreSQL_ implementation of the Meteor DDP server, allowing Meteor_ to subscribe to changes on Django_ models.  Released under the MIT license.


Requirements
------------
You must be using PostgreSQL_ with psycopg2_ in your Django_ project for django-ddp to work.  There is no requirement on any asynchronous framework such as Reddis or crossbar.io as they are simply not needed given the asynchronous support provided by PostgreSQL_ with psycopg2_.


Installation
------------

Install the latest release from pypi (recommended):

.. code:: sh

    pip install django-ddp

Clone and use development version direct from GitHub to test pre-release code (no GitHub account required):

.. code:: sh

    pip install -e git+https://github.com/commoncode/django-ddp@develop#egg=django-ddp


Overview and getting started
----------------------------

1. Django DDP registers handlers for `Django signals`_ on all model save/update operations.
    * Add ``'dddp'`` to INSTALLED_APPS in your project settings file.
2. Each Django application (ie: your code) registers Collections and Publications via ``ddp`` sub-modules for all INSTALLED_APPS.
    * Register collections and publications in a file named ``dddp.py`` inside your application module.
3. Clients subscribe to publications, entries are written into the ``dddp.Subscription`` and ``dddp.SubscriptionCollection`` model tables and the ``get_queries`` method of publications are called to retrieve the Django ORM queries that contain the objects that will be sent to the client.
    * Run ``manage.py migrate`` to update your database so it has the necessary tables needed for tracking client subscriptions.
4. When models are saved, the Django DDP signal handlers send change messages to clients subscribed to relevant publications.
    * Use the model ``save()`` and ``delete()`` methods as appropriate in your application code so that appropriate signals are raised and change messages are sent.
5. Gevent_ is used to run WebSocket connections concurrently along with any Django views defined in your project (via your project ``urls.py``).
    * Run your application using the ``dddp`` command which sets up the gevent mainloop and serves your Django project views.  This command takes care of routing WebSocket connections according to the URLs that Meteor uses, do not add URLs for WebSocket views to your project ``urls.py``.


Scalability
-----------
All database queries to support DDP events are done once by the server instance that has made changes via the Django ORM.  Django DDP multiplexes messages for active subscriptions, broadcasting an aggregated change message on channels specific to each Django model that has been published.

Peer servers subscribe to aggregate broadcast events which are de-multiplexed and dispatched to individual client connections.  No additional database queries are required for de-multiplexing or dispatch by peer servers.


Limitations
-----------
* No support for the SockJS XHR fallback protocol to support browsers
  that don't have WebSockets_ (see http://caniuse.com/websockets for
  supported browsers).  It is noteworthy that the only current browser
  listed that doesn't support WebSockets_ is Opera Mini, which doesn't
  support pages that use EcmaScript (JavaScript) for interactivity
  anyway.  Offering SockJS XHR fallback wouldn't help to substantially
  increase browser support: if Opera Mini is excluded then all current
  browser versions including IE, Edge, Firefox, Chrome, Safari, Opera,
  iOS Safari, Android Browser Android and Chrome for Android are
  supported.  Having said all that, pull requests are welcome.

* Changes must be made via the Django ORM as django-ddp uses `Django
  signals`_ to receive model save/update signals.  There are no
  technical reasons why database triggers couldn't be used - pull
  requests are welcome.


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

.. code:: python

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

Start the Django DDP service:

.. code:: sh

    DJANGO_SETTINGS_MODULE=myproject.settings dddp


Using django-ddp as a secondary DDP connection (RAPID DEVELOPMENT)
------------------------------------------------------------------

Running in this manner allows rapid development through use of the hot 
code push features provided by Meteor.

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

Start Meteor (from within your meteor application directory):

.. code:: sh

    meteor

Using django-ddp as the primary DDP connection (RECOMMENDED)
------------------------------------------------------------

If you'd prefer to not have two DDP connections (one to Meteor and one 
to django-ddp) you can set the `DDP_DEFAULT_CONNECTION_URL` environment 
variable to use the specified URL as the primary DDP connection in 
Meteor.  When doing this, you won't need to use `DDP.connect(...)` or 
specify `{connection: Django}` on your collections.  Running with 
django-ddp as the primary connection is recommended, and indeed required 
if you wish to use `dddp.accounts` to provide authentication using 
`django.contrib.auth` to your meteor app.

.. code:: sh

    DDP_DEFAULT_CONNECTION_URL=http://localhost:8000/ meteor


Serving your Meteor applications from django-ddp
------------------------------------------------

First, you will need to build your meteor app into a directory (examples 
below assume target directory named `myapp`):

.. code:: sh

    meteor build ../myapp

Then, add a MeteorView to your urls.py:

.. code:: python

    from dddp.views import MeteorView

    urlpatterns = patterns(
        url('^(?P<path>/.*)$', MeteorView.as_view(
            json_path=os.path.join(
                settings.PROJ_ROOT, 'myapp', 'bundle', 'star.json',
            ),
        ),
    )


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

`Yan Le <https://github.com/janusle>`_
    * Validate and bug fix dddp.accounts submodule.

`MEERQAT <http://meerqat.com.au/>`_
    * Project sponsor - many thanks for allowing this to be released under an open source license!

`David Burles <https://github.com/dburles>`_
    * Expert guidance on how DDP works in Meteor.

`Brenton Cleeland <https://github.com/sesh>`_
    * Great conversations around how collections and publications can limit visibility of published documents to specific users.

`Muhammed Thanish <https://github.com/mnmtanish>`_
    * Making the `DDP Test Suite <https://github.com/meteorhacks/ddptest>`_ available.

This project is forever grateful for the love, support and respect given 
by the awesome team at `Common Code`_.

.. _Django DDP: https://github.com/django-ddp/django-ddp
.. _Django: https://www.djangoproject.com/
.. _Django signals: https://docs.djangoproject.com/en/stable/topics/signals/
.. _Common Code: https://commoncode.com.au/
.. _Gevent: http://www.gevent.org/
.. _PostgreSQL: http://postgresql.org/
.. _psycopg2: http://initd.org/psycopg/
.. _WebSockets: http://www.w3.org/TR/websockets/
.. _Meteor: http://meteor.com/
