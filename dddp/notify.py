"""Django DDP notification support."""
from __future__ import absolute_import

import collections

import ejson
from django.db import connections
from django.utils.module_loading import import_string

from dddp.api import collection_name
from dddp.models import get_meteor_id, Subscription
from dddp.msg import obj_change_as_msg


class ImportCache(collections.defaultdict):
    @staticmethod
    def __missing__(key):
        return import_string(key)

_CLS_CACHE = ImportCache()


def send_notify(model, obj, msg, using):
    """Dispatch PostgreSQL async NOTIFY."""
    user_cache = {}
    col_name = collection_name(model)
    if col_name == 'migrations.migration':
        return  # never send migration models.
    if col_name.startswith('dddp.'):
        return  # don't send DDP internal models.
    sub_ids = set()
    for sub in Subscription.objects.filter(
            collections__name=col_name,
    ):
        pub = _CLS_CACHE[sub.publication_class]()
        pub_queries = {
            collection_name(qs.model): qs
            for qs
            in pub.get_queries(*sub.params)
            if qs.model is model
        }
        for sub_col in sub.collections.filter(
                name=col_name,
        ):
            qs = pub_queries[sub_col.name]
            col = _CLS_CACHE[sub_col.collection_class]()
            # filter qs using user_rel paths on collection
            try:
                user_ids = user_cache[sub_col.collection_class]
            except KeyError:
                user_ids = user_cache.setdefault(
                    sub_col.collection_class, col.user_ids_for_object(obj)
                )

            if user_ids is None:
                pass  # unrestricted collection, anyone can see.
            elif sub.user_id not in user_ids:
                continue  # not for this user

            qs = col.get_queryset(qs)
            if qs.filter(pk=obj.pk).exists():
                sub_ids.add(sub.sub_id)

    if not sub_ids:
        get_meteor_id(obj)  # force creation of meteor ID using randomSeed
        return  # no subscribers for this object, nothing more to do.

    name, payload = obj_change_as_msg(obj, msg)
    payload['_sub_ids'] = sorted(sub_ids)
    cursor = connections[using].cursor()
    cursor.execute(
        'NOTIFY "%s", %%s' % name,
        [
            ejson.dumps(payload),
        ],
    )
