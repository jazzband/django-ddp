"""Django DDP utils for DDP messaging."""
import collections
from django.core.serializers import get_serializer

_SERIALIZER = None

def obj_change_as_msg(obj, msg):
    """Generate a DDP msg for obj with specified msg type."""
    global _SERIALIZER
    if _SERIALIZER is None:
        _SERIALIZER = get_serializer('ddp')()
    data = _SERIALIZER.serialize([obj])[0]
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
