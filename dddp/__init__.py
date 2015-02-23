"""Django/PostgreSQL implementation of the Meteor DDP service."""
import os.path
from pkg_resources import get_distribution, DistributionNotFound


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
