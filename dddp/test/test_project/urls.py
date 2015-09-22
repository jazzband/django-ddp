"""Django DDP test project - URL configuraiton."""
import os.path

from django.conf import settings
from django.conf.urls import patterns, include, url
from django.contrib import admin
from dddp.views import MeteorView
import dddp.test

app = MeteorView.as_view(
    json_path=os.path.join(
        os.path.dirname(dddp.test.__file__),
        'build', 'bundle', 'star.json'
    ),
)

urlpatterns = patterns('',
    # Examples:
    # url(r'^$', 'dddp.test.test_project.views.home', name='home'),
    # url(r'^blog/', include('blog.urls')),

    url(r'^admin/', include(admin.site.urls)),
    url(
        r'^static/(?P<path>.*)$',
        'django.views.static.serve',
        {
            'document_root': settings.STATIC_ROOT,
            'show_indexes': False,
        },
    ),
    # all remaining URLs routed to Meteor app.
    url(r'^(?P<path>.*)$', app),
)
