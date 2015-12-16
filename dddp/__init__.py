"""Django/PostgreSQL implementation of the Meteor server."""
from __future__ import unicode_literals
import sys
from gevent.local import local
from dddp import alea

__version__ = '0.19.0'
__url__ = 'https://github.com/django-ddp/django-ddp'

default_app_config = 'dddp.apps.DjangoDDPConfig'

ADDED = 'added'
CHANGED = 'changed'
REMOVED = 'removed'

_GREEN = {}


def greenify():
    """Patch threading and psycopg2 modules for green threads."""
    # don't greenify twice.
    if _GREEN:
        return
    _GREEN[True] = True

    from gevent.monkey import patch_all, saved
    if ('threading' in sys.modules) and ('threading' not in saved):
        import warnings
        warnings.warn('threading module loaded before patching!')
    patch_all()

    try:
        # Use psycopg2 by default
        import psycopg2
        del psycopg2
    except ImportError:
        # Fallback to psycopg2cffi if required (eg: pypy)
        from psycopg2cffi import compat
        compat.register()

    from psycogreen.gevent import patch_psycopg
    patch_psycopg()


class AlreadyRegistered(Exception):

    """Raised when registering over the top of an existing registration."""

    pass


class ThreadLocal(local):

    """Thread local storage for greenlet state."""

    _init_done = False

    def __init__(self):
        """Create new thread storage instance."""
        if self._init_done:
            raise SystemError('__init__ called too many times')
        self._init_done = True

    def __getattr__(self, name):
        """Create missing attributes using default factories."""
        try:
            factory = THREAD_LOCAL_FACTORIES[name]
        except KeyError:
            raise AttributeError(name)
        return self.get(name, factory)

    def get(self, name, factory, *factory_args, **factory_kwargs):
        """Get attribute, creating if required using specified factory."""
        update_thread_local = getattr(factory, 'update_thread_local', True)
        if (not update_thread_local) or (name not in self.__dict__):
            obj = factory(*factory_args, **factory_kwargs)
            if update_thread_local:
                setattr(self, name, obj)
            return obj
        return getattr(self, name)

    @staticmethod
    def get_factory(name):
        """Get factory for given name."""
        return THREAD_LOCAL_FACTORIES[name]


class RandomStreams(object):

    """Namespaced PRNG generator."""

    def __init__(self):
        """Initialize with random PRNG state."""
        self._streams = {}
        self._seed = THREAD_LOCAL.alea_random.hex_string(20)

    def get_seed(self):
        """Retrieve current PRNG seed."""
        return self._seed

    def set_seed(self, val):
        """Set current PRNG seed."""
        self._streams = {}
        self._seed = val
    random_seed = property(get_seed, set_seed)

    def __getitem__(self, key):
        """Get namespaced PRNG stream."""
        if key not in self._streams:
            return self._streams.setdefault(key, alea.Alea(self._seed, key))
        return self._streams[key]


def serializer_factory():
    """Make a new DDP serializer."""
    from django.core.serializers import get_serializer
    return get_serializer('python')()


THREAD_LOCAL_FACTORIES = {
    'alea_random': alea.Alea,
    'random_streams': RandomStreams,
    'serializer': serializer_factory,
    'user_id': lambda: None,
    'user_ddp_id': lambda: None,
    'user': lambda: None,
}
THREAD_LOCAL = ThreadLocal()
METEOR_ID_CHARS = u'23456789ABCDEFGHJKLMNPQRSTWXYZabcdefghijkmnopqrstuvwxyz'


def meteor_random_id(name=None, length=17):
    """Generate a new ID, optionally using namespace of given `name`."""
    if name is None:
        stream = THREAD_LOCAL.alea_random
    else:
        stream = THREAD_LOCAL.random_streams[name]
    return stream.random_string(length, METEOR_ID_CHARS)


def autodiscover():
    """Import all `ddp` submodules from `settings.INSTALLED_APPS`."""
    from django.utils.module_loading import autodiscover_modules
    from dddp.api import API
    autodiscover_modules('ddp', register_to=API)
    return API
