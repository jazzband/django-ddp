"""Django DDP publisher."""

class Publisher(object):

    """
    Django DDP publisher class.

    >>> all_books = Publisher('all_books', Book.objects.all())
    >>> my_books = Publisher(
    ...     'my_books',
    ...     Book.objects.all(),
    ...     lambda request, qs: qs.filter(author=req.user)
    ... )
    >>> books_by_author_email = Publisher(
    ...     'books_by_author_email',
    ...     Book.objects.all(),
    ...     lambda request, qs, email: qs.filter(author__email=email)
    ... )
    """

    registry = {}

    def __init__(self, name, qs, func=None, register=True):
        self.name = name
        self.qs = qs
        self.model = qs.query.model
        self.func = func
        if register:
            self.register()

    def __contains__(self, (collection, pk)):
        pass

    def register(self):
        self.registry[self.name or self.model] = self
