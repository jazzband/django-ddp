"""Django DDP utils for DDP messaging."""

from django.core import serializers

SERIALIZER = serializers.get_serializer('python')()


def obj_change_as_msg(obj, msg):
    """Generate a DDP msg for obj with specified msg type."""
    data = SERIALIZER.serialize([obj])[0]
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
