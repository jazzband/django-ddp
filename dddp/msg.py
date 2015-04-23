"""Django DDP utils for DDP messaging."""
from dddp import THREAD_LOCAL as this
from django.core.serializers import get_serializer


def serializer_factory():
    """Make a new DDP serializer."""
    return get_serializer('ddp')()


def obj_change_as_msg(obj, msg):
    """Generate a DDP msg for obj with specified msg type."""
    serializer = this.get('serializer', serializer_factory)
    data = serializer.serialize([obj])[0]
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
