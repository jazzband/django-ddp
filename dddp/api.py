"""Django DDP API, Collections, Cursors and Publications."""
from __future__ import absolute_import
import collections
import traceback
import dbarray
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import aggregates, Q
from django.db.models.sql import aggregates as sql_aggregates
from django.utils.encoding import force_text
from dddp import AlreadyRegistered, THREAD_LOCAL as this
from dddp.models import Subscription
from dddp.msg import obj_change_as_msg
import ejson


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
        if api_path_prefix_format is not None:
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


def collection_name(model):
    """Return collection name given model class."""
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
        if model is not None:
            attrs.update(
                name=collection_name(model),
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
                    'collection': collection_name(rel.to),
                }

            choices = getattr(field, 'choices', None)
            if choices:
                schema['allowedValues'] = [val for val, _ in choices]

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
                    'collection': collection_name(field.rel.to),
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


class PublicationMeta(APIMeta):

    """DDP Publication metaclass."""

    def __new__(mcs, name, bases, attrs):
        """Create a new Publication class."""
        attrs.update(
            api_path_prefix_format='publications/{name}/',
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
        return self.queries[:] or []

    @api_endpoint
    def collections(self, *params):
        """Return list of collections for this publication."""
        return sorted(
            set(
                collection_name(qs.model)
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

    def __init__(self):
        """DDP API init."""
        self._registry = {}
        self._subs = {}

    def get_collection(self, model):
        """Return collection instance for given model."""
        name = collection_name(model)
        path = COLLECTION_PATH_FORMAT.format(name=name)
        return self._registry[path]

    @property
    def api_providers(self):
        """Return an iterable of API providers."""
        return self._registry.values()

    def sub_notify(self, id_, names, data):
        """Dispatch DDP updates to connections."""
        ws, _ = self._subs[id_]
        ws.send_msg(data)

    @api_endpoint
    def sub(self, id_, name, *params):
        """Create subscription, send matched objects that haven't been sent."""
        return self._sub(id_, name, *params)

    @transaction.atomic
    def _sub(self, id_, name, *params):
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
                'publication_class': '%s.%s' % (
                    pub.__class__.__module__,
                    pub.__class__.__name__,
                ),
                'params_ejson': ejson.dumps(params),
            },
        )
        if not created:
            this.send_msg({'msg': 'ready', 'subs': [id_]})
            return
        # re-read from DB so we can get transaction ID (xmin)
        obj = Subscription.objects.extra(**XMIN).get(pk=obj.pk)
        queries = {
            collection_name(collection.model): (collection, qs)
            for (qs, collection)
            in (
                (qs, self.get_collection(qs.model))
                for qs
                in pub.get_queries(*params)
            )
        }
        self._subs[id_] = (this.ws, sorted(queries))
        self.pgworker.subscribe(self.sub_notify, id_, sorted(queries))
        # mergebox via MVCC!  For details on how this is possible, read this:
        # https://devcenter.heroku.com/articles/postgresql-concurrency
        to_send = collections.OrderedDict(
            (
                name,
                collection.objects_for_user(
                    user=this.request.user.pk,
                    qs=qs,
                    xmin__lte=obj.xmin,
                ),
            )
            for name, (collection, qs)
            in queries.items()
        )
        for name, (collection, qs) in queries.items():
            obj.collections.create(
                name=name,
                collection_class='%s.%s' % (
                    collection.__class__.__module__,
                    collection.__class__.__name__,
                ),
            )
        for other in Subscription.objects.filter(
                connection=this.ws.connection,
                collections__name__in=queries.keys(),
        ).exclude(
            pk=obj.pk,
        ).order_by('pk').distinct():
            other_pub = self._registry[pub_path(other.publication)]
            for qs in other_pub.get_queries(*other.params):
                collection = self.get_collection(qs.model)
                if collection.name not in to_send:
                    continue
                to_send[collection.name] = to_send[collection.name].exclude(
                    pk__in=collection.objects_for_user(
                        user=this.request.user.pk,
                        qs=qs,
                        xmin__lte=obj.xmin,
                    ).values('pk'),
                )
        for qs in to_send.values():
            for obj in qs:
                name, payload = obj_change_as_msg(obj, 'added')
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
                res[collection_name(collection.model)] = collection.schema()
        return res


API = DDP()
