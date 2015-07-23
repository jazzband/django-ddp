"""Django DDP Server app config."""
from __future__ import print_function, absolute_import, unicode_literals

import mimetypes

from django.apps import AppConfig


class ServerConfig(AppConfig):

    """Django config for dddp.server app."""

    name = 'dddp.server'
    verbose_name = 'Django DDP Meteor Web Server'

    def ready(self):
        """Configure Django DDP server app."""
        mimetypes.init()  # read and process /etc/mime.types
