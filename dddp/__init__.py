"""Django/PostgreSQL implementation of the Meteor DDP service."""
from __future__ import unicode_literals
import os.path
from pkg_resources import get_distribution, DistributionNotFound
from gevent.local import local
from django.utils.module_loading import autodiscover_modules
from dddp import alea

try:
    _dist = get_distribution('django-ddp')
    if not __file__.startswith(os.path.join(_dist.location, 'django-ddp', '')):
        # not installed, but there is another version that *is*
        raise DistributionNotFound
except DistributionNotFound:
    __version__ = 'development'
else:
    __version__ = _dist.version

default_app_config = 'dddp.apps.DjangoDDPConfig'


class AlreadyRegistered(Exception):

    """Raised when registering over the top of an existing registration."""

    pass


class ThreadLocal(local):

    """Thread local storage for greenlet state."""

    _init_done = False

    def __init__(self, **default_factories):
        """Create new thread storage instance."""
        if self._init_done:
            raise SystemError('__init__ called too many times')
        self._init_done = True
        self._default_factories = default_factories

    def __getattr__(self, name):
        """Create missing attributes using default factories."""
        try:
            factory = self._default_factories[name]
        except KeyError:
            raise AttributeError(name)
        obj = factory()
        setattr(self, name, obj)
        return obj

    def get(self, name, factory, *factory_args, **factory_kwargs):
        """Get attribute, creating if required using specified factory."""
        if not hasattr(self, name):
            return setattr(self, name, factory(*factory_args, **factory_kwargs))
        return getattr(self, name)


THREAD_LOCAL = ThreadLocal(alea_random=alea.Alea)
METEOR_ID_CHARS = u'23456789ABCDEFGHJKLMNPQRSTWXYZabcdefghijkmnopqrstuvwxyz'


def meteor_random_id():
    return THREAD_LOCAL.alea_random.random_string(17, METEOR_ID_CHARS)


def autodiscover():
    from dddp.api import API
    autodiscover_modules('ddp', register_to=API)
    return API
