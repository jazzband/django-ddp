"""Django DDP utils for DDP messaging."""
from dddp import THREAD_LOCAL as this


def obj_change_as_msg(obj, msg):
    """Generate a DDP msg for obj with specified msg type."""
    serializer = this.serializer
    data = serializer.serialize([obj])[0]

    # collection name is <app>.<model>
    name = data['model']

    # cast ID as string
    if not isinstance(data['pk'], basestring):
        data['pk'] = '%d' % data['pk']

    payload = {
        'msg': msg,
        'collection': name,
        'id': data['pk'],
    }
    if msg != 'removed':
        payload['fields'] = data['fields']

    return (name, payload)
