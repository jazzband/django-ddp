"""Django DDP models."""
from __future__ import absolute_import

import collections

from django.db import models, transaction
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.utils.encoding import python_2_unicode_compatible
import ejson
from dddp import meteor_random_id


@transaction.atomic
def get_meteor_id(obj_or_model, obj_pk=None):
    """Return an Alea ID for the given object."""
    if obj_or_model is None:
        return None
    # Django model._meta is now public API -> pylint: disable=W0212
    meta = obj_or_model._meta
    model = meta.model
    if model is ObjectMapping:
        # this doesn't make sense - raise TypeError
        raise TypeError("Can't map ObjectMapping instances through self.")

    # try getting value of AleaIdField straight from instance if possible
    if isinstance(obj_or_model, model):
        # obj_or_model is an instance, not a model.
        if isinstance(meta.pk, AleaIdField):
            return obj_or_model.pk
        alea_unique_fields = [
            field
            for field in meta.local_fields
            if isinstance(field, AleaIdField) and field.unique
        ]
        if len(alea_unique_fields) == 1:
            # found an AleaIdField with unique=True, assume it's got the value.
            return getattr(obj_or_model, alea_unique_fields[0].attname)
        if obj_pk is None:
            # fall back to primary key, but coerce as string type for lookup.
            obj_pk = str(obj_or_model.pk)

    if obj_pk is None:
        # bail out if args are (model, pk) but pk is None.
        return None

    # fallback to using AleaIdField from ObjectMapping model.
    content_type = ContentType.objects.get_for_model(model)
    try:
        return ObjectMapping.objects.values_list(
            'meteor_id', flat=True,
        ).get(
            content_type=content_type,
            object_id=obj_pk,
        )
    except ObjectDoesNotExist:
        return ObjectMapping.objects.create(
            content_type=content_type,
            object_id=obj_pk,
            meteor_id=meteor_random_id('/collection/%s' % meta),
        ).meteor_id


@transaction.atomic
def get_meteor_ids(model, object_ids):
    """Return Alea ID mapping for all given ids of specified model."""
    content_type = ContentType.objects.get_for_model(model)
    # Django model._meta is now public API -> pylint: disable=W0212
    meta = model._meta
    if isinstance(meta.pk, AleaIdField):
        # primary_key is an AleaIdField, use it.
        return collections.OrderedDict(
            (obj_pk, obj_pk) for obj_pk in object_ids
        )
    result = collections.OrderedDict(
        (str(obj_pk), None)
        for obj_pk
        in object_ids
    )
    for obj_pk, meteor_id in ObjectMapping.objects.filter(
            content_type=content_type,
            object_id__in=list(result)
    ).values_list('object_id', 'meteor_id'):
        result[obj_pk] = meteor_id
    for obj_pk, meteor_id in result.items():
        if meteor_id is None:
            result[obj_pk] = ObjectMapping.objects.create(
                content_type=content_type,
                object_id=obj_pk,
                meteor_id=meteor_random_id('/collection/%s' % meta),
            ).meteor_id
    return result


@transaction.atomic
def get_object_id(model, meteor_id):
    """Return an object ID for the given meteor_id."""
    if meteor_id is None:
        return None
    # Django model._meta is now public API -> pylint: disable=W0212
    meta = model._meta

    if model is ObjectMapping:
        # this doesn't make sense - raise TypeError
        raise TypeError("Can't map ObjectMapping instances through self.")

    if isinstance(meta.pk, AleaIdField):
        # meteor_id is the primary key
        return meteor_id

    alea_unique_fields = [
        field
        for field in meta.local_fields
        if isinstance(field, AleaIdField) and field.unique
    ]
    if len(alea_unique_fields) == 1:
        # found an AleaIdField with unique=True, assume it's got the value.
        return model.objects.values_list(
            'pk', flat=True,
        ).get(**{
            alea_unique_fields[0].attname: meteor_id,
        })

    content_type = ContentType.objects.get_for_model(model)
    return ObjectMapping.objects.filter(
        content_type=content_type,
        meteor_id=meteor_id,
    ).values_list('object_id', flat=True).get()


@transaction.atomic
def get_object(model, meteor_id, *args, **kwargs):
    """Return an object for the given meteor_id."""
    # Django model._meta is now public API -> pylint: disable=W0212
    meta = model._meta
    if isinstance(meta.pk, AleaIdField):
        # meteor_id is the primary key
        return model.objects.filter(*args, **kwargs).get(pk=meteor_id)

    return model.objects.filter(*args, **kwargs).get(
        pk=get_object_id(model, meteor_id),
    )


class AleaIdField(models.CharField):

    """CharField that generates its own values using Alea PRNG before INSERT."""

    def __init__(self, *args, **kwargs):
        """Assume max_length of 17 to match Meteor implementation."""
        kwargs.update(
            editable=False,
            max_length=17,
        )
        super(AleaIdField, self).__init__(*args, **kwargs)

    def deconstruct(self):
        """Return details on how this field was defined."""
        name, path, args, kwargs = super(AleaIdField, self).deconstruct()
        del kwargs['max_length']
        return name, path, args, kwargs

    def pre_save(self, model_instance, add):
        """Generate ID if required."""
        _, _, _, kwargs = self.deconstruct()
        val = getattr(model_instance, self.attname)
        if val is None and kwargs.get('default', None) is None:
            val = meteor_random_id('/collection/%s' % model_instance._meta)
            setattr(model_instance, self.attname, val)
        return val


class AleaIdMixin(models.Model):

    """Django model mixin that provides AleaIdField field (as _id)."""

    id = AleaIdField(
        primary_key=True,
    )

    class Meta(object):

        """Model meta options for AleaIdMixin."""

        abstract = True


@python_2_unicode_compatible
class ObjectMapping(models.Model):

    """Mapping from regular Django model primary keys to Meteor object IDs."""

    meteor_id = AleaIdField()
    content_type = models.ForeignKey(ContentType, db_index=True)
    object_id = models.CharField(max_length=255)
    # content_object = GenericForeignKey('content_type', 'object_id')

    def __str__(self):
        """Text representation of a mapping."""
        return '%s: %s[%s]' % (
            self.meteor_id, self.content_type, self.object_id,
        )

    class Meta(object):

        """Meta info for ObjectMapping model."""

        unique_together = [
            ['content_type', 'meteor_id'],
        ]
        index_together = [
            ['content_type', 'object_id'],
            ['content_type', 'meteor_id'],
        ]


@python_2_unicode_compatible
class Connection(models.Model, object):

    """Django DDP connection instance."""

    connection_id = AleaIdField()
    server_addr = models.CharField(max_length=255)
    remote_addr = models.CharField(max_length=255)
    version = models.CharField(max_length=255)

    def __str__(self):
        """Text representation of subscription."""
        return u'%s/\u200b%s' % (
            self.connection_id,
            self.remote_addr,
        )


@python_2_unicode_compatible
class Subscription(models.Model, object):

    """Subscription to a publication with params."""

    _publication_cache = {}
    connection = models.ForeignKey(Connection)
    sub_id = models.CharField(max_length=17)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, blank=True, null=True)
    publication = models.CharField(max_length=255)
    params_ejson = models.TextField(default='{}')

    class Meta(object):

        """Subscription model meta."""

        unique_together = [
            ['connection', 'sub_id'],
        ]

    def __str__(self):
        """Text representation of subscription."""
        return u'%s/\u200b%s/\u200b%s: %s%s' % (
            self.user,
            self.connection_id,
            self.sub_id,
            self.publication,
            self.params_ejson,
        )

    def get_params(self):
        """Get params dict."""
        return ejson.loads(self.params_ejson or '{}')

    def set_params(self, vals):
        """Set params dict."""
        self.params_ejson = ejson.dumps(vals or {})

    params = property(get_params, set_params)


@python_2_unicode_compatible
class SubscriptionCollection(models.Model):

    """Collections for a subscription."""

    subscription = models.ForeignKey(Subscription, related_name='collections')
    model_name = models.CharField(max_length=255)
    collection_name = models.CharField(max_length=255)

    def __str__(self):
        """Human readable representation of colleciton for a subscription."""
        return u'%s \u200b %s (%s)' % (
            self.subscription,
            self.collection_name,
            self.model_name,
        )
