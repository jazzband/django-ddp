"""Django DDP utils for DDP messaging."""
from copy import deepcopy
from dddp import THREAD_LOCAL as this, REMOVED
try:
    from django.db.models.expressions import ExpressionNode
except AttributeError:
    ExpressionNode = None


def obj_change_as_msg(obj, msg):
    """Generate a DDP msg for obj with specified msg type."""
    if ExpressionNode is None:
        exps = False
    else:
        # check for F expressions
        exps = [
            name for name, val in vars(obj).items()
            if isinstance(val, ExpressionNode)
        ]
    if exps:
        # clone and update obj with values but only for the expression fields
        obj = deepcopy(obj)
        # Django 1.8 makes obj._meta public --> pylint: disable=W0212
        for name, val in obj._meta.model.objects.values(*exps).get(pk=obj.pk):
            setattr(obj, name, val)

    # run serialization now that all fields are "concrete" (not F expressions)
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
    if msg != REMOVED:
        payload['fields'] = data['fields']

    return (name, payload)
