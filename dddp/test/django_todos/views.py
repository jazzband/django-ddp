import os.path

from dddp.views import MeteorView
import dddp.test


class MeteorTodos(MeteorView):
    """Meteor Todos."""

    json_path = os.path.join(
        os.path.dirname(dddp.test.__file__),
        'build', 'bundle', 'star.json'
    )
