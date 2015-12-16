"""Django DDP Server views."""
from __future__ import absolute_import, unicode_literals

from copy import deepcopy
import io
import mimetypes
import os.path

from ejson import dumps, loads
from django.conf import settings
from django.http import HttpResponse
from django.views.generic import View

import pybars


# from https://www.xormedia.com/recursively-merge-dictionaries-in-python/
def dict_merge(lft, rgt):
    """
    Recursive dict merge.

    Recursively merges dict's. not just simple lft['key'] = rgt['key'], if
    both lft and rgt have a key who's value is a dict then dict_merge is
    called on both values and the result stored in the returned dictionary.
    """
    if not isinstance(rgt, dict):
        return rgt
    result = deepcopy(lft)
    for key, val in rgt.iteritems():
        if key in result and isinstance(result[key], dict):
            result[key] = dict_merge(result[key], val)
        else:
            result[key] = deepcopy(val)
    return result


def read(path, default=None, encoding='utf8'):
    """Read encoded contents from specified path or return default."""
    if not path:
        return default
    try:
        with io.open(path, mode='r', encoding=encoding) as contents:
            return contents.read()
    except IOError:
        if default is not None:
            return default
        raise


def read_json(path):
    """Read JSON encoded contents from specified path."""
    with open(path, mode='r') as json_file:
        return loads(json_file.read())


class MeteorView(View):

    """Django DDP Meteor server view."""

    http_method_names = ['get', 'head']

    json_path = None
    runtime_config = None

    star_json = None  # top level layout

    url_map = None
    internal_map = None
    server_load_map = None
    template_path = None  # web server HTML template path
    client_map = None  # web.browser (client) URL to path map
    html = '<!DOCTYPE html>\n<html><head><title>DDP App</title></head></html>'

    meteor_settings = None
    meteor_public_envs = None
    root_url_path_prefix = ''
    bundled_js_css_prefix = '/'

    def __init__(self, **kwargs):
        """
        Initialisation for Django DDP server view.

        The following items populate `Meteor.settings` (later take precedence):
          1. django.conf.settings.METEOR_SETTINGS
          2. os.environ['METEOR_SETTINGS']
          3. MeteorView.meteor_settings (class attribute) or empty dict
          4. MeteorView.as_view(meteor_settings=...)

        Additionally, `Meteor.settings.public` is updated with values from
        environemnt variables specified from the following sources:
          1. django.conf.settings.METEOR_PUBLIC_ENVS
          2. os.environ['METEOR_PUBLIC_ENVS']
          3. MeteorView.meteor_public_envs (class attribute) or empty dict
          4. MeteorView.as_view(meteor_public_envs=...)
        """
        self.runtime_config = {}
        self.meteor_settings = {}
        for other in [
                getattr(settings, 'METEOR_SETTINGS', {}),
                loads(os.environ.get('METEOR_SETTINGS', '{}')),
                self.meteor_settings or {},
                kwargs.pop('meteor_settings', {}),
        ]:
            self.meteor_settings = dict_merge(self.meteor_settings, other)
        self.meteor_public_envs = set()
        self.meteor_public_envs.update(
            getattr(settings, 'METEOR_PUBLIC_ENVS', []),
            os.environ.get('METEOR_PUBLIC_ENVS', '').replace(',', ' ').split(),
            self.meteor_public_envs or [],
            kwargs.pop('meteor_public_envs', []),
        )
        public = self.meteor_settings.setdefault('public', {})
        for env_name in self.meteor_public_envs:
            try:
                public[env_name] = os.environ[env_name]
            except KeyError:
                pass  # environment variable not set
        # super(...).__init__ assigns kwargs to instance.
        super(MeteorView, self).__init__(**kwargs)

        # read and process /etc/mime.types
        mimetypes.init()

        self.url_map = {}

        # process `star_json`
        self.star_json = read_json(self.json_path)
        star_format = self.star_json['format']
        if star_format != 'site-archive-pre1':
            raise ValueError(
                'Unknown Meteor star format: %r' % star_format,
            )
        programs = {
            program['name']: program
            for program in self.star_json['programs']
        }

        # process `bundle/programs/server/program.json` from build dir
        server_json_path = os.path.join(
            os.path.dirname(self.json_path),
            os.path.dirname(programs['server']['path']),
            'program.json',
        )
        server_json = read_json(server_json_path)
        server_format = server_json['format']
        if server_format != 'javascript-image-pre1':
            raise ValueError(
                'Unknown Meteor server format: %r' % server_format,
            )
        self.server_load_map = {}
        for item in server_json['load']:
            item['path_full'] = os.path.join(
                os.path.dirname(server_json_path),
                item['path'],
            )
            self.server_load_map[item['path']] = item
            self.url_map[item['path']] = (
                item['path_full'], 'text/javascript'
            )
            try:
                item['source_map_full'] = os.path.join(
                    os.path.dirname(server_json_path),
                    item['sourceMap'],
                )
                self.url_map[item['sourceMap']] = (
                    item['source_map_full'], 'text/plain'
                )
            except KeyError:
                pass
        self.template_path = os.path.join(
            os.path.dirname(server_json_path),
            self.server_load_map[
                'packages/boilerplate-generator.js'
            ][
                'assets'
            ][
                'boilerplate_web.browser.html'
            ],
        )

        # process `bundle/programs/web.browser/program.json` from build dir
        web_browser_json_path = os.path.join(
            os.path.dirname(self.json_path),
            programs['web.browser']['path'],
        )
        web_browser_json = read_json(web_browser_json_path)
        web_browser_format = web_browser_json['format']
        if web_browser_format != 'web-program-pre1':
            raise ValueError(
                'Unknown Meteor web.browser format: %r' % (
                    web_browser_format,
                ),
            )
        self.client_map = {}
        self.internal_map = {}
        for item in web_browser_json['manifest']:
            item['path_full'] = os.path.join(
                os.path.dirname(web_browser_json_path),
                item['path'],
            )
            if item['where'] == 'client':
                if '?' in item['url']:
                    item['url'] = item['url'].split('?', 1)[0]
                if item['url'].startswith('/'):
                    item['url'] = item['url'][1:]
                self.client_map[item['url']] = item
                self.url_map[item['url']] = (
                    item['path_full'],
                    mimetypes.guess_type(
                        item['path_full'],
                    )[0] or 'application/octet-stream',
                )
            elif item['where'] == 'internal':
                self.internal_map[item['type']] = item

        config = {
            'css': [
                {'url': item['path']}
                for item in web_browser_json['manifest']
                if item['type'] == 'css' and item['where'] == 'client'
            ],
            'js': [
                {'url': item['path']}
                for item in web_browser_json['manifest']
                if item['type'] == 'js' and item['where'] == 'client'
            ],
            'meteorRuntimeConfig': '"%s"' % (
                dumps(self.runtime_config)
            ),
            'rootUrlPathPrefix': self.root_url_path_prefix,
            'bundledJsCssPrefix': self.bundled_js_css_prefix,
            'inlineScriptsAllowed': False,
            'inline': None,
            'head': read(
                self.internal_map.get('head', {}).get('path_full', None),
                default=u'',
            ),
            'body': read(
                self.internal_map.get('body', {}).get('path_full', None),
                default=u'',
            ),
        }
        tmpl_raw = read(self.template_path, encoding='utf8')
        compiler = pybars.Compiler()
        tmpl = compiler.compile(tmpl_raw)
        self.html = '<!DOCTYPE html>\n%s' % tmpl(config)

    def get(self, request, path):
        """Return HTML (or other related content) for Meteor."""
        if path == 'meteor_runtime_config.js':
            config = {
                'DDP_DEFAULT_CONNECTION_URL': request.build_absolute_uri('/'),
                'PUBLIC_SETTINGS': self.meteor_settings.get('public', {}),
                'ROOT_URL': request.build_absolute_uri(
                    '%s/' % (
                        self.runtime_config.get('ROOT_URL_PATH_PREFIX', ''),
                    ),
                ),
                'ROOT_URL_PATH_PREFIX': '',
            }
            # Use HTTPS instead of HTTP if SECURE_SSL_REDIRECT is set
            if config['DDP_DEFAULT_CONNECTION_URL'].startswith('http:') \
                    and settings.SECURE_SSL_REDIRECT:
                config['DDP_DEFAULT_CONNECTION_URL'] = 'https:%s' % (
                    config['DDP_DEFAULT_CONNECTION_URL'].split(':', 1)[1],
                )
            config.update(self.runtime_config)
            return HttpResponse(
                '__meteor_runtime_config__ = %s;' % dumps(config),
                content_type='text/javascript',
            )
        try:
            file_path, content_type = self.url_map[path]
            with open(file_path, 'r') as content:
                return HttpResponse(
                    content.read(),
                    content_type=content_type,
                )
        except KeyError:
            return HttpResponse(self.html)
