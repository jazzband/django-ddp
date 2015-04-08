django-ddp
==========

Django/PostgreSQL implementation of the Meteor DDP service, allowing Meteor to subsribe to changes on Django models.

Example usage
-------------

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

.. code:: sh

    # start DDP service using default port (8000)
    $ manage.py dddp
