"""Django/PostgreSQL implementation of the Meteor DDP service."""
import os.path
from pkg_resources import get_distribution, DistributionNotFound
from django.utils.module_loading import autodiscover_modules
from gevent.local import local
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

class ThreadLocal(local):
    _init_done = False

    def __init__(self, **default_factories):
        if self._init_done:
            raise SystemError('__init__ called too many times')
        self._init_done = True
        self._default_factories = default_factories

    def __getattr__(self, name):
        try:
            factory = self._default_factories[name]
        except KeyError:
            raise AttributeError
        obj = factory()
        setattr(self, name, obj)
        return obj

    def get(self, name, factory, *factory_args, **factory_kwargs):
        if not hasattr(self, name):
            return setattr(self, name, factory(*factory_args, **factory_kwargs))
        return getattr(self, name)

THREAD_LOCAL = ThreadLocal(alea_random=alea.Alea)
