"""Django DDP Server views."""
from __future__ import print_function, absolute_import
from ejson import dumps
from django.apps import apps
from django.http import HttpResponse
from django.views.generic import View


STAR_JSON_SETTING_NAME = 'METEOR_STAR_JSON'


class MeteorView(View):

    """Django DDP Meteor server view."""

    http_method_names = ['get', 'head']

    app = None
    runtime_config = None

    def __init__(self, **kwargs):
        """Initialisation for Django DDP server view."""
        super(MeteorView, self).__init__(**kwargs)
        self.app = apps.get_app_config('server')

    def get(self, request, path):
        """Return HTML (or other related content) for Meteor."""
        if path == '/meteor_runtime_config.js':
            config = {
                'DDP_DEFAULT_CONNECTION_URL': request.build_absolute_uri('/'),
                'ROOT_URL': request.build_absolute_uri('/'),
                'ROOT_URL_PATH_PREFIX': '',
            }
            config.update(self.runtime_config)
            return HttpResponse(
                '__meteor_runtime_config__ = %s;' % dumps(config),
                content_type='text/javascript',
            )
        try:
            file_path, content_type = self.app.url_map[path]
            with open(file_path, 'r') as content:
                return HttpResponse(
                    content.read(),
                    content_type=content_type,
                )
        except KeyError:
            print(path)
            return HttpResponse(self.app.html)
            #raise Http404
