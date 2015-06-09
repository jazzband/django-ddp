"""Django DDP Server app config."""
from __future__ import print_function, absolute_import, unicode_literals

import io
import os.path

from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from ejson import dumps, loads
import pybars


STAR_JSON_SETTING_NAME = 'METEOR_STAR_JSON'


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


class ServerConfig(AppConfig):

    """Django config for dddp.server app."""

    name = 'dddp.server'
    verbose_name = 'Django DDP Meteor Web Server'

    manifest = None
    program_json = None
    program_json_path = None
    runtime_config = None

    star_json = None  # top level layout
    server_json = None  # web server layout
    web_browser_json = None  # web.browser (client) layout

    url_map = None
    internal_map = None
    server_load_map = None
    template_path = None  # web server HTML template path
    client_map = None  # web.browser (client) URL to path map
    html = '<!DOCTYPE html>\n<html><head><title>DDP App</title></head></html>'

    def ready(self):
        """Configure Django DDP server app."""
        self.url_map = {}

        try:
            json_path = getattr(settings, STAR_JSON_SETTING_NAME)
        except AttributeError:
            raise ImproperlyConfigured(
                '%s setting required by dddp.server.view.' % (
                    STAR_JSON_SETTING_NAME,
                ),
            )

        self.star_json = read_json(json_path)
        star_format = self.star_json['format']
        if star_format != 'site-archive-pre1':
            raise ValueError(
                'Unknown Meteor star format: %r' % star_format,
            )
        programs = {
            program['name']: program
            for program in self.star_json['programs']
        }

        server_json_path = os.path.join(
            os.path.dirname(json_path),
            os.path.dirname(programs['server']['path']),
            'program.json',
        )
        self.server_json = read_json(server_json_path)
        server_format = self.server_json['format']
        if server_format != 'javascript-image-pre1':
            raise ValueError(
                'Unknown Meteor server format: %r' % server_format,
            )
        self.server_load_map = {}
        for item in self.server_json['load']:
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

        web_browser_json_path = os.path.join(
            os.path.dirname(json_path),
            programs['web.browser']['path'],
        )
        self.web_browser_json = read_json(web_browser_json_path)
        web_browser_format = self.web_browser_json['format']
        if web_browser_format != 'web-program-pre1':
            raise ValueError(
                'Unknown Meteor web.browser format: %r' % (
                    web_browser_format,
                ),
            )
        self.client_map = {}
        self.internal_map = {}
        for item in self.web_browser_json['manifest']:
            item['path_full'] = os.path.join(
                os.path.dirname(web_browser_json_path),
                item['path'],
            )
            if item['where'] == 'client':
                if '?' in item['url']:
                    item['url'] = item['url'].split('?', 1)[0]
                self.client_map[item['url']] = item
                self.url_map[item['url']] = (
                    item['path_full'],
                    {
                        'js': 'text/javascript',
                        'css': 'text/css',
                    }.get(
                        item['type'], 'application/octet-stream',
                    ),
                )
            elif item['where'] == 'internal':
                self.internal_map[item['type']] = item

        config = {
            'css': [
                {'url': item['path']}
                for item in self.web_browser_json['manifest']
                if item['type'] == 'css' and item['where'] == 'client'
            ],
            'js': [
                {'url': item['path']}
                for item in self.web_browser_json['manifest']
                if item['type'] == 'js' and item['where'] == 'client'
            ],
            'meteorRuntimeConfig': '"%s"' % (
                dumps(self.runtime_config)
            ),
            'rootUrlPathPrefix': '/app',
            'bundledJsCssPrefix': '/app/',
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
