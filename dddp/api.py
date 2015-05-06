"""Django DDP API, Collections, Cursors and Publications."""
from __future__ import absolute_import, unicode_literals

# standard library
import collections
from copy import deepcopy
import heapq
import itertools
import sys
import traceback

from six.moves import range

# requirements
import dbarray
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.db.models import aggregates, Q
from django.db.models.expressions import ExpressionNode
from django.db.models.sql import aggregates as sql_aggregates
from django.utils.encoding import force_text
from django.db import DatabaseError
from django.db.models import signals
import ejson

# django-ddp
from dddp import AlreadyRegistered, THREAD_LOCAL as this
from dddp.models import Connection, Subscription, get_meteor_id


XMIN = {'select': {'xmin': "'xmin'"}}


class Sql(object):

    """Extensions to django.db.models.sql.aggregates module."""

    class Array(sql_aggregates.Aggregate):

        """Array SQL aggregate extension."""

        lookup_name = 'array'
        sql_function = 'array_agg'

sql_aggregates.Array = Sql.Array


class Array(aggregates.Aggregate):

    """Array aggregate function."""

    func = 'ARRAY'
    name = 'Array'

    def add_to_query(self, query, alias, col, source, is_summary):
        """Override source field internal type so the raw array is returned."""
        class ArrayField(dbarray.ArrayFieldBase, source.__class__):

            """ArrayField for override."""

            __metaclass__ = dbarray.ArrayFieldMetaclass

            @staticmethod
            def get_internal_type():
                """Return ficticious type so Django doesn't cast as int."""
                return 'ArrayType'

        new_source = ArrayField()
        super(Array, self).add_to_query(
            query, alias, col, new_source, is_summary,
        )


def api_endpoint(path_or_func):
    """Decorator to mark a method as an API endpoint for later registration."""
    if callable(path_or_func):
        path_or_func.api_path = path_or_func.__name__
        return path_or_func
    else:
        def _api_endpoint(func):
            """Decorator inner."""
            func.api_path = path_or_func
            return func
        return _api_endpoint


def api_endpoints(obj):
    """Iterator over all API endpoint names and callbacks."""
    for name in dir(obj):
        attr = getattr(obj, name)
        api_path = getattr(attr, 'api_path', None)
        if api_path:
            yield (
                '%s%s' % (obj.api_path_prefix, api_path),
                attr,
            )
    for api_provider in obj.api_providers:
        for api_path, attr in api_endpoints(api_provider):
            yield (api_path, attr)


class APIMeta(type):

    """DDP API metaclass."""

    def __new__(mcs, name, bases, attrs):
        """Create a new APIMixin class."""
        attrs['name'] = attrs.pop('name', None) or name
        name_format = attrs.get('name_format', None)
        if name_format:
            attrs['name'] = name_format.format(**attrs)
        api_path_prefix_format = attrs.get('api_path_prefix_format', None)
        if attrs.get('api_path_prefix', None) is not None:
            pass
        elif api_path_prefix_format is not None:
            attrs['api_path_prefix'] = api_path_prefix_format.format(**attrs)
        return super(APIMeta, mcs).__new__(mcs, name, bases, attrs)


class APIMixin(object):

    """Mixin to support finding API endpoints for class instances."""

    api_path_prefix_format = None

    api_providers = []
    api_path_prefix = '/'
    _api_path_cache = None

    def api_path_map(self):
        """Cached dict of api_path: func."""
        if self._api_path_cache is None:
            self._api_path_cache = {
                api_path: func
                for api_path, func
                in api_endpoints(self)
            }
        return self._api_path_cache

    def clear_api_path_map_cache(self):
        """Clear out cache for api_path_map."""
        self._api_path_cache = None
        for api_provider in self.api_providers:
            if api_provider.clear_api_path_map_cache.im_self is not None:
                api_provider.clear_api_path_map_cache()

    def api_endpoint(self, api_path):
        """Return API endpoint for given api_path."""
        return self.api_path_map()[api_path]


def model_name(model):
    """Return model name given model class."""
    # Django supports model._meta -> pylint: disable=W0212
    return force_text(model._meta)


COLLECTION_PATH_FORMAT = '/{name}/'


class CollectionMeta(APIMeta):

    """DDP Collection metaclass."""

    def __new__(mcs, name, bases, attrs):
        """Create a new Collection class."""
        attrs.update(
            api_path_prefix_format=COLLECTION_PATH_FORMAT,
        )
        model = attrs.get('model', None)
        if attrs.get('name', None) is None and model is not None:
            attrs.update(
                name=model_name(model),
            )
        return super(CollectionMeta, mcs).__new__(mcs, name, bases, attrs)


class Collection(APIMixin):

    """DDP Model Collection."""

    __metaclass__ = CollectionMeta

    name = None
    model = None
    qs_filter = None
    order_by = None
    user_rel = None

    def get_queryset(self, base_qs=None):
        """Return a filtered, ordered queryset for this collection."""
        qs = self.model.objects.all() if base_qs is None else base_qs
        # enforce ordering so later use of distinct() works as expected.
        if not qs.query.order_by:
            if self.order_by is None:
                qs = qs.order_by('pk')
            else:
                qs = qs.order_by(*self.order_by)
        if self.qs_filter:
            qs = qs.filter(self.qs_filter)
        return qs

    queryset = property(get_queryset)

    def objects_for_user(self, user, qs=None, xmin__lte=None):
        """Find objects in queryset related to specified user."""
        qs = self.get_queryset(qs)
        user_rels = self.user_rel
        if user_rels:
            if user is None:
                return qs.none()  # no user but we need one: return no objects.
            if isinstance(user_rels, basestring):
                user_rels = [user_rels]
            user_filter = None
            for user_rel in user_rels:
                filter_obj = Q(**{user_rel: user})
                if user_filter is None:
                    user_filter = filter_obj
                else:
                    user_filter |= filter_obj
            qs = qs.filter(user_filter).distinct()
        if xmin__lte is not None:
            qs = qs.extra(
                where=["'xmin' <= %s"],
                params=[xmin__lte],
            )
        return qs

    def user_ids_for_object(self, obj, base_qs=None, include_superusers=True):
        """Find user IDs related to object/pk in queryset."""
        qs = base_qs or self.queryset
        if self.user_rel:
            user_rels = self.user_rel
            if isinstance(user_rels, basestring):
                user_rels = [user_rels]
            user_rel_map = {
                '_user_rel_%d' % index: Array(user_rel)
                for index, user_rel
                in enumerate(user_rels)
            }

            user_ids = set()
            if include_superusers:
                user_ids.update(
                    get_user_model().objects.filter(
                        is_superuser=True, is_active=True,
                    ).values_list('pk', flat=True)
                )

            for rel_user_ids in qs.filter(
                    pk=hasattr(obj, 'pk') and obj.pk or obj,
            ).annotate(**user_rel_map).values_list(*user_rel_map.keys()).get():
                user_ids.update(rel_user_ids)
            user_ids.difference_update([None])
            return user_ids
        else:
            return None

    def field_schema(self):
        """Generate schema for consumption by clients."""
        type_map = {
            'AutoField': 'String',
            'BooleanField': 'Boolean',
            'CharField': 'String',
            'DateTimeField': 'Date',
            'DecimalField': 'Number',
            'FloatField': 'Number',
            'ForeignKey': 'String',
            'PositiveIntegerField': 'Number',
            'TextField': 'String',
        }
        db_type_map = {
            'serial': 'Number',
            'text': 'String',
            'boolean': 'Boolean',
            'integer': 'Number',
        }
        # Django supports model._meta -> pylint: disable=W0212
        meta = self.model._meta
        for field in meta.local_fields:
            int_type = field.get_internal_type()
            schema = {
                'type': (
                    type_map.get(int_type, None)
                ) or (
                    db_type_map.get(field.db_type(connection), 'String')
                )
            }

            rel = getattr(field, 'rel', None)
            if rel:
                schema['type'] = 'String'
                schema['relation'] = {
                    'name': field.name,
                    'collection': model_name(rel.to),
                }

            choices = getattr(field, 'choices', None)
            if choices:
                schema['allowedValues'] = [val for val, _ in choices]
                schema['autoform'] = {
                    'options': [
                        {'label': desc, 'value': val}
                        for val, desc in choices
                    ],
                }

            blank = getattr(field, 'blank', None)
            if blank:
                schema['optional'] = True

            formfield = field.formfield()
            if formfield:
                schema['label'] = force_text(formfield.label)

            max_length = getattr(field, 'max_length', None)
            if max_length is not None:
                schema['max'] = max_length

            if int_type == 'PositiveIntegerField':
                schema['min'] = 0
            if int_type in ('DecimalField', 'FloatField'):
                schema['decimal'] = True
            yield field.column, schema
        for field in meta.local_many_to_many:
            yield '%s_ids' % field.column, {
                'type': '[String]',
                'relation': {
                    'name': field.name,
                    'collection': model_name(field.rel.to),
                },
            }

    @api_endpoint
    def schema(self):
        """Return a representation of the schema for this collection."""
        return {
            name: schema
            for name, schema
            in self.field_schema()
        }

    def serialize(self, obj):
        """Generate a DDP msg for obj with specified msg type."""
        # check for F expressions
        exps = [
            name for name, val in vars(obj).items()
            if isinstance(val, ExpressionNode)
        ]
        if exps:
            # clone/update obj with values but only for the expression fields
            obj = deepcopy(obj)
            for name, val in self.model.objects.values(*exps).get(pk=obj.pk):
                setattr(obj, name, val)

        # run serialization now all fields are "concrete" (not F expressions)
        return this.serializer.serialize([obj])[0]

    def obj_change_as_msg(self, obj, msg):
        """Return DDP change message of specified type (msg) for obj."""
        if msg == 'removed':
            data = {'pk': get_meteor_id(obj)}  # `removed` only needs ID
        elif msg in ('added', 'changed'):
            data = self.serialize(obj)
            data['id'] = str(data.pop('pk'))  # force casting ID as string
        else:
            raise ValueError('Invalid message type: %r' % msg)

        data.update(msg=msg, collection=self.name)
        return data


class PublicationMeta(APIMeta):

    """DDP Publication metaclass."""

    def __new__(mcs, name, bases, attrs):
        """Create a new Publication class."""
        attrs.update(
            api_path_prefix_format='publication/{name}/',
        )
        return super(PublicationMeta, mcs).__new__(mcs, name, bases, attrs)


class Publication(APIMixin):

    """DDP Publication (a set of queries)."""

    __metaclass__ = PublicationMeta

    name = None
    queries = None

    def get_queries(self, *params):
        """DDP get_queries - must override if using params."""
        if params:
            raise NotImplementedError(
                'Publication params not implemented on %r publication.' % (
                    self.name,
                ),
            )
        return self.queries[:]

    @api_endpoint
    def collections(self, *params):
        """Return list of collections for this publication."""
        return sorted(
            set(
                hasattr(qs, 'model') and model_name(qs.model) or qs[1]
                for qs
                in self.get_queries(*params)
            )
        )


def pub_path(publication_name):
    """Return api_path for a publication."""
    return Publication.api_path_prefix_format.format(name=publication_name)




class DDP(APIMixin):

    """Django DDP API."""

    __metaclass__ = APIMeta

    pgworker = None
    _in_migration = False

    class Msg(object):

        """DDP message type enumeration."""

        ADDED = 'added'
        CHANGED = 'changed'
        REMOVED = 'removed'

    def __init__(self):
        """DDP API init."""
        self._registry = {}
        self._subs = {}
        # self._tx_buffer collects outgoing messages which must be sent in order
        self._tx_buffer = []
        # track the head of the queue (buffer) and the next msg to be sent
        self._tx_buffer_id_gen = itertools.repeat(range(sys.maxint))
        self._tx_next_id_gen = itertools.repeat(range(sys.maxint))
        # start by waiting for the very first message
        self._tx_next_id = self._tx_next_id_gen.next()

    def get_collection(self, model):
        """Return collection instance for given model."""
        name = model_name(model)
        return self.get_col_by_name(name)

    def get_col_by_name(self, name):
        """Return collection instance for given name."""
        return self._registry[COLLECTION_PATH_FORMAT.format(name=name)]

    @property
    def api_providers(self):
        """Return an iterable of API providers."""
        return self._registry.values()

    def sub_notify(self, id_, names, data):
        """Dispatch DDP updates to connections."""
        ws, _ = self._subs[id_]
        ws.send_msg(data)

    def qs_and_collection(self, qs):
        """Return (qs, collection) from qs (which may be a tuple)."""
        if hasattr(qs, 'model'):
            return (qs, self.get_collection(qs.model))
        elif isinstance(qs, (list, tuple)):
            return (qs[0], self.get_col_by_name(qs[1]))
        else:
            raise TypeError('Invalid query spec: %r' % qs)

    @api_endpoint
    def sub(self, id_, name, *params):
        """Create subscription, send matched objects that haven't been sent."""
        try:
            pub = self._registry[pub_path(name)]
        except KeyError:
            this.error('Invalid publication name: %r' % name)
            return
        obj, created = Subscription.objects.get_or_create(
            connection_id=this.ws.connection.pk,
            sub_id=id_,
            user_id=this.request.user.pk,
            defaults={
                'publication': pub.name,
                'params_ejson': ejson.dumps(params),
            },
        )
        if not created:
            this.send_msg({'msg': 'ready', 'subs': [id_]})
            return
        # re-read from DB so we can get transaction ID (xmin)
        obj = Subscription.objects.extra(**XMIN).get(pk=obj.pk)
        queries = collections.OrderedDict(
            (col.name, (col, qs))
            for (qs, col)
            in (
                self.qs_and_collection(qs)
                for qs
                in pub.get_queries(*params)
            )
        )
        self._subs[id_] = (this.ws, sorted(queries))
        self.pgworker.subscribe(self.sub_notify, id_, sorted(queries))
        # mergebox via MVCC!  For details on how this is possible, read this:
        # https://devcenter.heroku.com/articles/postgresql-concurrency
        to_send = collections.OrderedDict(
            (
                name,
                col.objects_for_user(
                    user=this.request.user.pk,
                    qs=qs,
                    xmin__lte=obj.xmin,
                ),
            )
            for name, (col, qs)
            in queries.items()
        )
        for name, (col, qs) in queries.items():
            obj.collections.create(
                model_name=model_name(qs.model),
                collection_name=name,
            )
        for other in Subscription.objects.filter(
                connection=this.ws.connection,
                collections__collection_name__in=queries.keys(),
        ).exclude(
            pk=obj.pk,
        ).order_by('pk').distinct():
            other_pub = self._registry[pub_path(other.publication)]
            for qs in other_pub.get_queries(*other.params):
                qs, col = self.qs_and_collection(qs)
                if col not in to_send:
                    continue
                to_send[col] = to_send[col.name].exclude(
                    pk__in=col.objects_for_user(
                        user=this.request.user.pk,
                        qs=qs,
                        xmin__lte=obj.xmin,
                    ).values('pk'),
                )
        for collection_name, qs in to_send.items():
            col = self.get_col_by_name(collection_name)
            for obj in qs:
                payload = col.obj_change_as_msg(obj, self.Msg.ADDED)
                this.send_msg(payload)
        this.send_msg({'msg': 'ready', 'subs': [id_]})

    def unsub_notify(self, id_):
        """Dispatch DDP updates to connections."""
        (ws, _) = self._subs.pop(id_, (None, []))
        if ws is not None:
            Subscription.objects.filter(
                connection=ws.connection,
                sub_id=id_,
            ).delete()
            ws.send_msg({'msg': 'nosub', 'id': id_})

    @api_endpoint
    def unsub(self, id_):
        """Remove a subscription."""
        self.pgworker.unsubscribe(self.unsub_notify, id_)

    @api_endpoint
    def method(self, method, params, id_):
        """Invoke a method."""
        try:
            handler = self.api_path_map()[method]
        except KeyError:
            this.error('Unknown method: %s' % method)
            return
        try:
            result = handler(*params)
            msg = {'msg': 'result', 'id': id_}
            if result is not None:
                msg['result'] = result
            this.send_msg(msg)
        except Exception, err:  # log error+stack trace -> pylint: disable=W0703
            details = traceback.format_exc()
            this.ws.logger.error(err, exc_info=True)
            msg = {
                'msg': 'result',
                'id': id_,
                'error': {
                    'error': 500,
                    'reason': str(err),
                },
            }
            if settings.DEBUG:
                msg['error']['details'] = details
            this.send_msg(msg)

    def register(self, api_or_iterable):
        """Register an API endpoint."""
        if hasattr(api_or_iterable, 'api_path_prefix'):
            api_or_iterable = [api_or_iterable]
        for api in api_or_iterable:
            api = api()
            if api.api_path_prefix in self._registry:
                raise AlreadyRegistered(
                    'API with prefix %r is already registered to %r' % (
                        api.api_path_prefix,
                        self._registry[api.api_path_prefix],
                    ),
                )
            self._registry[api.api_path_prefix] = api
            self.clear_api_path_map_cache()

    @api_endpoint
    def schema(self):
        """Return schema for all registered collections."""
        res = {}
        for api_provider in self.api_providers:
            if isinstance(api_provider, Collection):
                collection = api_provider
                res[model_name(collection.model)] = collection.schema()
        return res

    def ready(self):
        """Initialisation for django-ddp (setup lookups and signal handlers)."""
        signals.post_save.connect(self.on_save)
        signals.post_delete.connect(self.on_delete)
        signals.m2m_changed.connect(self.on_m2m_changed)
        signals.post_migrate.connect(self.on_post_migrate)

    def on_save(self, sender, **kwargs):
        """Post-save signal handler."""
        if self._in_migration:
            return
        self.send_notify(
            model=sender,
            obj=kwargs['instance'],
            msg=kwargs['created'] and self.Msg.ADDED or self.Msg.CHANGED,
            using=kwargs['using'],
        )

    def on_delete(self, sender, **kwargs):
        """Post-delete signal handler."""
        if self._in_migration:
            return
        self.send_notify(
            model=sender,
            obj=kwargs['instance'],
            msg='removed',
            using=kwargs['using'],
        )

    def on_m2m_changed(self, sender, **kwargs):
        """M2M-changed signal handler."""
        if self._in_migration:
            return
        # See https://docs.djangoproject.com/en/1.7/ref/signals/#m2m-changed
        if kwargs['action'] in (
                'post_add',
                'post_remove',
                'post_clear',
        ):
            if kwargs['reverse'] is False:
                objs = [kwargs['instance']]
                model = objs[0].__class__
            else:
                model = kwargs['model']
                objs = model.objects.filter(pk__in=kwargs['pk_set'])

            for obj in objs:
                self.send_notify(
                    model=model,
                    obj=obj,
                    msg='changed',
                    using=kwargs['using'],
                )

    def on_pre_migrate(self, sender, **kwargs):
        """Pre-migrate signal handler."""
        self._in_migration = True

    def on_post_migrate(self, sender, **kwargs):
        """Post-migrate signal handler."""
        self._in_migration = False
        try:
            Connection.objects.all().delete()
        except DatabaseError:  # pylint: disable=E0712
            pass

    def send_notify(self, model, obj, msg, using):
        """Dispatch PostgreSQL async NOTIFY."""
        col_user_ids = {}
        mod_name = model_name(model)
        if mod_name.split('.', 1)[0] in ('migrations', 'dddp'):
            return  # never send migration or DDP internal models
        col_sub_ids = collections.defaultdict(set)
        for sub in Subscription.objects.filter(
                collections__model_name=mod_name,
        ).prefetch_related('collections'):
            for qs, col in (
                    self.qs_and_collection(qs)
                    for qs
                    in self._registry[
                        'publication/%s/' % sub.publication
                    ].get_queries(*sub.params)
            ):
                # check if obj is an instance of the model for the queryset
                if qs.model is not model:
                    continue  # wrong model on queryset

                # check if obj is included in this subscription
                if not qs.filter(pk=obj.pk).exists():
                    continue  # subscription doesn't include this obj

                # filter qs using user_rel paths on collection
                # retreieve list of allowed users via colleciton
                try:
                    user_ids = col_user_ids[col.__class__]
                except KeyError:
                    user_ids = col_user_ids[col.__class__] = \
                        col.user_ids_for_object(obj)
                if user_ids is None:
                    pass  # unrestricted collection, anyone permitted to see.

                # check if user is in permitted list of users
                if user_ids is not None:
                    pass  # unrestricted collection, anyone permitted to see.
                elif sub.user_id in user_ids:
                    continue  # not for this user

                col_sub_ids[col].add(sub.sub_id)

        if not col_sub_ids:
            get_meteor_id(obj)  # force creation of meteor ID using randomSeed
            return  # no subscribers for this object, nothing more to do.

        for col, sub_ids in col_sub_ids.items():
            payload = col.obj_change_as_msg(obj, msg)
            payload['_sub_ids'] = sorted(sub_ids)
            cursor = connections[using].cursor()
            cursor.execute(
                'NOTIFY "%s", %%s' % col.name,
                [
                    ejson.dumps(payload),
                ],
            )


API = DDP()
