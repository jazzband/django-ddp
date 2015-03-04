"""Django DDP models."""

from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from dddp import THREAD_LOCAL

METEOR_ID_CHARS = '23456789ABCDEFGHJKLMNPQRSTWXYZabcdefghijkmnopqrstuvwxyz'


class AleaIdField(models.CharField):

    """CharField that generates its own values using Alea PRNG before INSERT."""

    def __init__(self, *args, **kwargs):
        """Assume max_length of 17 to match Meteor implementation."""
        kwargs.setdefault('max_length', 17)
        super(AleaIdField, self).__init__(*args, **kwargs)

    def pre_save(self, model_instance, add):
        """Generate value if not set during INSERT."""
        if add and not getattr(model_instance, self.attname):
            value = THREAD_LOCAL.alea_random.random_string(
                self.max_length, METEOR_ID_CHARS,
            )
            setattr(model_instance, self.attname, value)
            return value
        else:
            return super(AleaIdField, self).pre_save(self, model_instance, add)


class ObjectMapping(models.Model):

    """Mapping from regular Django model primary keys to Meteor object IDs."""

    meteor_id = AleaIdField()
    content_type = models.ForeignKey(ContentType, db_index=True)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta(object):

        """Meta info for ObjectMapping model."""

        unique_together = [
            ['content_type', 'meteor_id'],
        ]
        index_together = [
            ['content_type', 'object_id'],
            ['content_type', 'meteor_id'],
        ]
