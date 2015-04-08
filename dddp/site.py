"""Django DDP sites."""
from dddp import AlreadyRegistered
from dddp.api import PubSubAPI


class Site(object):

    """Django DDP site class."""

    def __init__(self):
        """Django DDP site init."""
        self._registry = {}

    def register(self, endpoint_or_iterable):
        """Register an API endpoint."""
        if not hasattr(endpoint_or_iterable, 'api_path'):
            endpoint_or_iterable = [endpoint_or_iterable]
        for endpoint in endpoint_or_iterable:
            if endpoint.api_path in self._registry:
                raise AlreadyRegistered(
                    'API endpoint with path %r already registerd to %r' % (
                        endpoint.api_path,
                        self._registry,
                    ),
                )
            self._registry[endpoint.api_path] = endpoint

    def unregister(self, endpoint_or_path_or_iterable):
        """Un-register an API endpoint."""
        if not hasattr(endpoint_or_iterable, 'api_path'):
            endpoint_or_iterable = [endpoint_or_iterable]
        for endpoint in endpoint_or_iterable:
            if isinstance(endpoint, basestring):
                del self._registry[endpoint.api_path] = endpoint
            else:
                del self._registry[endpoint.api_path] = endpoint

site = Site()

publications = PubSubAPI()
site.register(publications.api_endpoints)
