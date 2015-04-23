"""
A Python "serializer". Doesn't do much serializing per se -- just converts to
and from basic Python data types (lists, dicts, strings, etc.). Useful as a basis for
other serializers.
"""
from __future__ import unicode_literals

from django.apps import apps
from django.conf import settings
from django.core.serializers import base
from django.core.serializers import python
from django.db import DEFAULT_DB_ALIAS, models
from django.utils import six
from django.utils.encoding import force_text, is_protected_type
from dddp.models import get_meteor_id, get_object_id


class Serializer(python.Serializer):
    """
    Serializes a QuerySet to basic Python objects.
    """

    def get_dump_object(self, obj):
        data = super(Serializer, self).get_dump_object(obj)
        data["pk"] = get_meteor_id(obj)
        return data

    def handle_fk_field(self, obj, field):
        value = getattr(obj, field.name)
        self._current[field.column] = get_meteor_id(value)

    def handle_m2m_field(self, obj, field):
        if field.rel.through._meta.auto_created:
            m2m_value = lambda value: get_meteor_id(value)
            self._current['%s_ids' % field.name] = [m2m_value(related)
                               for related in getattr(obj, field.name).iterator()]


def Deserializer(object_list, **options):
    """
    Deserialize simple Python objects back into Django ORM instances.

    It's expected that you pass the Python objects themselves (instead of a
    stream or a string) to the constructor
    """
    db = options.pop('using', DEFAULT_DB_ALIAS)
    ignore = options.pop('ignorenonexistent', False)

    for d in object_list:
        # Look up the model and starting build a dict of data for it.
        try:
            Model = _get_model(d["model"])
        except base.DeserializationError:
            if ignore:
                continue
            else:
                raise
        data = {}
        if 'pk' in d:
            data[Model._meta.pk.attname] = Model._meta.pk.to_python(
                get_object_id(Model, d.get("pk", None)),
            )
        m2m_data = {}
        field_names = {f.name for f in Model._meta.fields}
        field_name_map = {
            f.column: f.name
            for f in Model._meta.fields
        }
        for field in Model._meta.many_to_many:
            field_name_map.setdefault('%s_ids' % field.name, field.name)

        # Handle each field
        for (field_column, field_value) in six.iteritems(d["fields"]):
            field_name = field_name_map.get(field_column, None)

            if ignore and field_name not in field_names:
                # skip fields no longer on model
                continue

            if isinstance(field_value, str):
                field_value = force_text(
                    field_value, options.get("encoding", settings.DEFAULT_CHARSET), strings_only=True
                )

            field = Model._meta.get_field(field_name)

            # Handle M2M relations
            if field.rel and isinstance(field.rel, models.ManyToManyRel):
                m2m_data[field.name] = [get_object_id(field.rel.to, pk) for pk in field_value]

            # Handle FK fields
            elif field.rel and isinstance(field.rel, models.ManyToOneRel):
                if field_value is not None:
                    field_value= get_object_id(field.rel.to, field_value)
                    data[field.attname] = field.rel.to._meta.get_field(field.rel.field_name).to_python(field_value)
                else:
                    data[field.attname] = None

            # Handle all other fields
            else:
                data[field.name] = field.to_python(field_value)

        obj = base.build_instance(Model, data, db)
        yield base.DeserializedObject(obj, m2m_data)


def _get_model(model_identifier):
    """
    Helper to look up a model from an "app_label.model_name" string.
    """
    try:
        return apps.get_model(model_identifier)
    except (LookupError, TypeError):
        raise base.DeserializationError("Invalid model identifier: '%s'" % model_identifier)
