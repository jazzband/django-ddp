"""Django DDP models."""

from django.db import models, transaction
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.utils.encoding import python_2_unicode_compatible
import ejson
from dddp import meteor_random_id


@transaction.atomic
def get_meteor_id(obj):
    """Return an Alea ID for the given object."""
    if obj is None:
        return None
    # Django model._meta is now public API -> pylint: disable=W0212
    meta = obj._meta
    if meta.model is ObjectMapping:
        # this doesn't make sense - raise TypeError
        raise TypeError("Can't map ObjectMapping instances through self.")
    obj_pk = str(obj.pk)
    content_type = ContentType.objects.get_for_model(meta.model)
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
def get_object_id(model, meteor_id):
    """Return an object ID for the given meteor_id."""
    if model is ObjectMapping:
        # this doesn't make sense - raise TypeError
        raise TypeError("Can't map ObjectMapping instances through self.")
    # Django model._meta is now public API -> pylint: disable=W0212
    content_type = ContentType.objects.get_for_model(model)
    return ObjectMapping.objects.filter(
        content_type=content_type,
        meteor_id=meteor_id,
    ).values_list('object_id', flat=True).get()


@transaction.atomic
def get_object(model, meteor_id):
    """Return an object for the given meteor_id."""
    return model.objects.get(
        pk=get_object_id(model, meteor_id),
    )


class AleaIdField(models.CharField):

    """CharField that generates its own values using Alea PRNG before INSERT."""

    def __init__(self, *args, **kwargs):
        """Assume max_length of 17 to match Meteor implementation."""
        kwargs.update(
            default=meteor_random_id,
            max_length=17,
        )
        super(AleaIdField, self).__init__(*args, **kwargs)


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

    session = models.ForeignKey('sessions.Session')
    connection_id = AleaIdField()
    server_addr = models.CharField(max_length=255)
    remote_addr = models.CharField(max_length=255)
    version = models.CharField(max_length=255)

    class Meta(object):

        """Connection model meta."""

        unique_together = [
            ['connection_id', 'session'],
        ]

    def __str__(self):
        """Text representation of subscription."""
        return u'%s/\u200b%s/\u200b%s' % (
            self.session_id,
            self.connection_id,
            self.remote_addr,
        )


@python_2_unicode_compatible
class Subscription(models.Model, object):

    """Session subscription to a publication with params."""

    _publication_cache = {}
    connection = models.ForeignKey(Connection)
    sub_id = models.CharField(max_length=17)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, blank=True, null=True)
    publication = models.CharField(max_length=255)
    publication_class = models.CharField(max_length=255)
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
    name = models.CharField(max_length=255)
    collection_class = models.CharField(max_length=255)

    def __str__(self):
        """Human readable representation of colleciton for a subscription."""
        return '%s' % (
            self.name,
        )
