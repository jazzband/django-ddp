"""Django DDP test project - URL configuraiton."""

from django.conf import settings
from django.conf.urls import patterns, include, url
from django.contrib import admin
from django_todos.views import MeteorTodos


urlpatterns = patterns(
    '',
    # Examples:
    # url(r'^$', 'test_project.views.home', name='home'),
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
    url(r'^(?P<path>.*)$', MeteorTodos.as_view()),
)
