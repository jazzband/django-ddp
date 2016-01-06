from __future__ import absolute_import
import os.path

from dddp.views import MeteorView
import tests


class MeteorTodos(MeteorView):
    """Meteor Todos."""

    json_path = os.path.join(
        os.path.dirname(tests.__file__),
        'build', 'bundle', 'star.json'
    )
