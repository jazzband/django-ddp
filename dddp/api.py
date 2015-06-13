"""Django DDP API, Collections, Cursors and Publications."""
from __future__ import absolute_import, unicode_literals, print_function

# standard library
import collections
from copy import deepcopy
import traceback

# requirements
import dbarray
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.db.models import aggregates, Q
try:
    from django.db.models.expressions import ExpressionNode
except ImportError:
    from django.db.models import Expression as ExpressionNode
from django.db.models.sql import aggregates as sql_aggregates
from django.utils.encoding import force_text
from django.db import DatabaseError
from django.db.models import signals
import ejson

# django-ddp
from dddp import (
    AlreadyRegistered, THREAD_LOCAL as this, ADDED, CHANGED, REMOVED,
)
from dddp.models import Connection, Subscription, get_meteor_id, get_meteor_ids


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
    function = 'array_agg'
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
        try:
            super(Array, self).add_to_query(
                query, alias, col, new_source, is_summary,
            )
        except AttributeError:
            query.aggregates[alias] = new_source

    def convert_value(self, value, expression, connection, context):
        if not value:
            return []
        return value


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
            user_ids = set()
            if obj.pk is None:
                return user_ids  # nobody can see objects that don't exist
            user_rels = self.user_rel
            if isinstance(user_rels, basestring):
                user_rels = [user_rels]
            user_rel_map = {
                '_user_rel_%d' % index: Array(user_rel)
                for index, user_rel
                in enumerate(user_rels)
            }

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
            schema = {
                'type': '[String]',
                'relation': {
                    'name': field.name,
                    'collection': model_name(field.rel.to),
                },
            }

            blank = getattr(field, 'blank', None)
            if blank:
                schema['optional'] = True

            formfield = field.formfield()
            if formfield:
                schema['label'] = force_text(formfield.label)

            yield '%s_ids' % field.column, schema

    @api_endpoint
    def schema(self):
        """Return a representation of the schema for this collection."""
        return {
            name: schema
            for name, schema
            in self.field_schema()
        }

    def serialize(self, obj, meteor_ids):
        """Generate a DDP msg for obj with specified msg type."""
        # check for F expressions
        exps = [
            name for name, val in vars(obj).items()
            if isinstance(val, ExpressionNode)
        ]
        if exps:
            # clone/update obj with values but only for the expression fields
            obj = deepcopy(obj)
            for name, val in self.model.objects.values(*exps).get(
                    pk=obj.pk,
            ).items():
                setattr(obj, name, val)

        # run serialization now all fields are "concrete" (not F expressions)
        data = this.serializer.serialize([obj])[0]
        fields = data['fields']
        del data['pk'], data['model']
        # Django supports model._meta -> pylint: disable=W0212
        meta = self.model._meta
        for field in meta.local_fields:
            rel = getattr(field, 'rel', None)
            if rel:
                fields[field.column] = get_meteor_id(
                    rel.to, fields.pop(field.name),
                )
        for field in meta.local_many_to_many:
            fields['%s_ids' % field.name] = get_meteor_ids(
                field.rel.to, fields.pop(field.name),
            ).values()
        return data

    def obj_change_as_msg(self, obj, msg, meteor_ids=None):
        """Return DDP change message of specified type (msg) for obj."""
        if meteor_ids is None:
            meteor_ids = {}
        try:
            meteor_id = meteor_ids[str(obj.pk)]
        except KeyError:
            meteor_id = None
        if meteor_id is None:
            meteor_ids[str(obj.pk)] = meteor_id = get_meteor_id(obj)
        assert meteor_id is not None
        if msg == REMOVED:
            data = {}  # `removed` only needs ID (added below)
        elif msg in (ADDED, CHANGED):
            data = self.serialize(obj, meteor_ids)
        else:
            raise ValueError('Invalid message type: %r' % msg)

        data.update(msg=msg, collection=self.name, id=meteor_id)
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


class DDP(APIMixin):

    """Django DDP API."""

    __metaclass__ = APIMeta

    pgworker = None
    _in_migration = False

    def __init__(self):
        """DDP API init."""
        self._registry = {}
        self._ddp_subscribers = {}

    def get_collection(self, model):
        """Return collection instance for given model."""
        name = model_name(model)
        return self.get_col_by_name(name)

    def get_col_by_name(self, name):
        """Return collection instance for given name."""
        return self._registry[COLLECTION_PATH_FORMAT.format(name=name)]

    def get_pub_by_name(self, name):
        """Return publication instance for given name."""
        path = Publication.api_path_prefix_format.format(name=name)
        return self._registry[path]

    @property
    def api_providers(self):
        """Return an iterable of API providers."""
        return self._registry.values()

    def qs_and_collection(self, qs):
        """Return (qs, collection) from qs (which may be a tuple)."""
        if hasattr(qs, 'model'):
            return (qs, self.get_collection(qs.model))
        elif isinstance(qs, (list, tuple)):
            return (qs[0], self.get_col_by_name(qs[1]))
        else:
            raise TypeError('Invalid query spec: %r' % qs)

    def sub_unique_objects(self, obj, params=None, pub=None, *args, **kwargs):
        """Return objects that are only visible through given subscription."""
        if params is None:
            params = ejson.loads(obj.params_ejson)
        if pub is None:
            pub = self.get_pub_by_name(obj.publication)
        queries = collections.OrderedDict(
            (col, qs) for (qs, col) in (
                self.qs_and_collection(qs)
                for qs
                in pub.get_queries(*params)
            )
        )
        # mergebox via MVCC!  For details on how this is possible, read this:
        # https://devcenter.heroku.com/articles/postgresql-concurrency
        to_send = collections.OrderedDict(
            (
                col,
                col.objects_for_user(
                    user=obj.user_id,
                    qs=qs,
                    *args, **kwargs
                ),
            )
            for col, qs
            in queries.items()
        )
        for other in Subscription.objects.filter(
                connection=obj.connection_id,
                collections__collection_name__in=[col.name for col in queries],
        ).exclude(
            pk=obj.pk,
        ).order_by('pk').distinct():
            other_pub = self.get_pub_by_name(other.publication)
            for qs in other_pub.get_queries(*other.params):
                qs, col = self.qs_and_collection(qs)
                if col not in to_send:
                    continue
                to_send[col] = to_send[col].exclude(
                    pk__in=col.objects_for_user(
                        user=other.user_id,
                        qs=qs,
                        *args, **kwargs
                    ).values('pk'),
                )
        for col, qs in to_send.items():
            yield col, qs.distinct()

    @api_endpoint
    def sub(self, id_, name, *params):
        """Create subscription, send matched objects that haven't been sent."""
        try:
            pub = self.get_pub_by_name(name)
        except KeyError:
            this.send({
                'msg': 'nosub',
                'error': {
                    'error': 404,
                    'errorType': 'Meteor.Error',
                    'message': 'Subscription not found [404]',
                    'reason': 'Subscription not found',
                },
            })
            return
        sub, created = Subscription.objects.get_or_create(
            connection_id=this.ws.connection.pk,
            sub_id=id_,
            user_id=this.request.user.pk,
            defaults={
                'publication': pub.name,
                'params_ejson': ejson.dumps(params),
            },
        )
        if not created:
            this.send({'msg': 'ready', 'subs': [id_]})
            return
        # re-read from DB so we can get transaction ID (xmin)
        sub = Subscription.objects.extra(**XMIN).get(pk=sub.pk)
        for col, qs in self.sub_unique_objects(
                sub, params, pub, xmin__lte=sub.xmin,
        ):
            sub.collections.create(
                model_name=model_name(qs.model),
                collection_name=col.name,
            )
            meteor_ids = get_meteor_ids(
                qs.model, qs.values_list('pk', flat=True),
            )
            for obj in qs:
                payload = col.obj_change_as_msg(obj, ADDED, meteor_ids)
                this.send(payload)
        this.send({'msg': 'ready', 'subs': [id_]})

    @api_endpoint
    def unsub(self, id_):
        """Remove a subscription."""
        sub = Subscription.objects.get(
            connection=this.ws.connection, sub_id=id_,
        )
        for col, qs in self.sub_unique_objects(sub):
            meteor_ids = get_meteor_ids(
                qs.model, qs.values_list('pk', flat=True),
            )
            for obj in qs:
                payload = col.obj_change_as_msg(obj, REMOVED, meteor_ids)
                this.send(payload)
        sub.delete()
        this.send({'msg': 'nosub', 'id': id_})

    @api_endpoint
    def method(self, method, params, id_):
        """Invoke a method."""
        try:
            handler = self.api_path_map()[method]
        except KeyError:
            this.error('Unknown method: %s' % method)
            return
        params_repr = repr(params)
        try:
            result = handler(*params)
            msg = {'msg': 'result', 'id': id_}
            if result is not None:
                msg['result'] = result
            this.send(msg)
        except Exception, err:  # log error+stack trace -> pylint: disable=W0703
            details = traceback.format_exc()
            print(id_, method, params_repr)
            print(details)
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
            this.send(msg)

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
        # set/unset self._in_migration
        signals.pre_migrate.connect(self.on_pre_migrate)
        signals.post_migrate.connect(self.on_post_migrate)
        # update self._ddp_subscribers before changes made
        signals.pre_delete.connect(self.on_pre_change)
        signals.pre_save.connect(self.on_pre_change)
        # emit change message after changes made
        signals.post_save.connect(self.on_post_save)
        signals.post_delete.connect(self.on_post_delete)
        signals.m2m_changed.connect(self.on_m2m_changed)

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

    def on_pre_change(self, sender, **kwargs):
        """Pre change (save/delete) signal handler."""
        if self._in_migration:
            return
        if model_name(sender).split('.', 1)[0] in ('migrations', 'dddp'):
            return  # never send migration or DDP internal models
        obj = kwargs['instance']
        using = kwargs['using']
        self._ddp_subscribers.setdefault(
            using, {},
        ).setdefault(
            sender, {},
        )[obj.pk] = self.valid_subscribers(
            model=sender, obj=obj, using=using,
        )

    def on_m2m_changed(self, sender, **kwargs):
        """M2M-changed signal handler."""
        if self._in_migration:
            return
        if kwargs['reverse'] is False:
            objs = [kwargs['instance']]
            model = objs[0].__class__
        else:
            model = kwargs['model']
            objs = model.objects.filter(pk__in=kwargs['pk_set'])
        mod_name = model_name(model)
        if mod_name.split('.', 1)[0] in ('migrations', 'dddp'):
            return  # never send migration or DDP internal models
        # See https://docs.djangoproject.com/en/1.7/ref/signals/#m2m-changed
        if kwargs['action'] in (
                'pre_add',
                'pre_remove',
                'pre_clear',
        ):
            for obj in objs:
                self.on_pre_change(
                    sender=model, instance=obj, using=kwargs['using'],
                )
        elif kwargs['action'] in (
                'post_add',
                'post_remove',
                'post_clear',
        ):

            for obj in objs:
                self.send_notify(
                    model=model,
                    obj=obj,
                    msg=CHANGED,
                    using=kwargs['using'],
                )

    def on_post_save(self, sender, **kwargs):
        """Post-save signal handler."""
        if self._in_migration:
            return
        self.send_notify(
            model=sender,
            obj=kwargs['instance'],
            msg=kwargs['created'] and ADDED or CHANGED,
            using=kwargs['using'],
        )

    def on_post_delete(self, sender, **kwargs):
        """Post-delete signal handler."""
        if self._in_migration:
            return
        self.send_notify(
            model=sender,
            obj=kwargs['instance'],
            msg=REMOVED,
            using=kwargs['using'],
        )

    def valid_subscribers(self, model, obj, using):
        """Calculate valid subscribers (connections) for obj."""
        col_user_ids = {}
        col_connection_ids = collections.defaultdict(set)
        for sub in Subscription.objects.filter(
                collections__model_name=model_name(model),
        ).prefetch_related('collections'):
            pub = self.get_pub_by_name(sub.publication)
            for qs, col in (
                    self.qs_and_collection(qs)
                    for qs
                    in pub.get_queries(*sub.params)
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

                # check if user is in permitted list of users
                if user_ids is None:
                    pass  # unrestricted collection, anyone permitted to see.
                elif sub.user_id not in user_ids:
                    continue  # not for this user

                col_connection_ids[col].add(sub.connection_id)

        # result is {colleciton: set([connection_id])}
        return col_connection_ids

    def send_notify(self, model, obj, msg, using):
        """Dispatch PostgreSQL async NOTIFY."""
        if model_name(model).split('.', 1)[0] in ('migrations', 'dddp'):
            return  # never send migration or DDP internal models

        new_col_connection_ids = self.valid_subscribers(model, obj, using)
        old_col_connection_ids = self._ddp_subscribers.get(
            using, {},
        ).get(
            model, {},
        ).pop(
            obj.pk, collections.defaultdict(set),
        )
        try:
            my_connection_id = this.ws.connection.pk
        except AttributeError:
            my_connection_id = None
        meteor_ids = {}
        for col in set(old_col_connection_ids).union(new_col_connection_ids):
            old_connection_ids = old_col_connection_ids[col]
            new_connection_ids = new_col_connection_ids[col]
            for (msg, connection_ids) in (
                    (REMOVED, old_connection_ids - new_connection_ids),
                    (CHANGED, old_connection_ids & new_connection_ids),
                    (ADDED, new_connection_ids - old_connection_ids),
            ):
                if not connection_ids:
                    continue  # nobody subscribed
                payload = col.obj_change_as_msg(obj, msg, meteor_ids)
                payload['_connection_ids'] = sorted(connection_ids)
                if my_connection_id is not None:
                    payload['_sender'] = my_connection_id
                    if my_connection_id in connection_ids:
                        # msg must go to connection that initiated the change
                        payload['_tx_id'] = this.ws.get_tx_id()
                cursor = connections[using].cursor()
                cursor.execute(
                    'NOTIFY "ddp", %s',
                    [
                        ejson.dumps(payload),
                    ],
                )


API = DDP()
