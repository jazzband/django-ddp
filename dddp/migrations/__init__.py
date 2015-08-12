import functools
from django.db import migrations
from django.db.migrations.operations.base import Operation
from dddp.models import AleaIdField, get_meteor_id


class TruncateOperation(Operation):

    """Truncate (delete all rows) from the models specified."""

    def __init__(self, forwards=None, backwards=None):
        """Accept model names which are to be migrated."""
        self.truncate_forwards = forwards or []
        self.truncate_backwards = backwards or []

    def truncate(self, app_label, schema_editor, models):
        """Truncate tables."""
        for model_name in models:
            model = '%s_%s' % (app_label, model_name)
            schema_editor.execute(
                'TRUNCATE TABLE %s RESTART IDENTITY CASCADE' % (
                    model.lower(),
                ),
            )

    def state_forwards(self, app_label, state):
        """Mutate state to match schema changes."""
        pass  # Truncate doesn't change schema.

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        """Use schema_editor to apply any forward changes."""
        self.truncate(app_label, schema_editor, self.truncate_forwards)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        """Use schema_editor to apply any reverse changes."""
        self.truncate(app_label, schema_editor, self.truncate_backwards)

    def describe(self):
        """Describe what the operation does in console output."""
        return "Truncate tables"


def set_default_forwards(app_name, operation, apps, schema_editor):
    """Set default value for AleaIdField."""
    model = apps.get_model(app_name, operation.model_name)
    for obj_pk in model.objects.values_list('pk', flat=True):
        model.objects.filter(pk=obj_pk).update(**{
            operation.name: get_meteor_id(model, obj_pk),
        })


def set_default_reverse(app_name, operation, apps, schema_editor):
    """Unset default value for AleaIdField."""
    model = apps.get_model(app_name, operation.model_name)
    for obj_pk in model.objects.values_list('pk', flat=True):
        get_meteor_id(model, obj_pk)


class DefaultAleaIdOperations(object):

    def __init__(self, app_name):
        self.app_name = app_name

    def __add__(self, operations):
        default_operations = []
        for operation in operations:
            if not isinstance(operation, migrations.AlterField):
                continue
            if not isinstance(operation.field, AleaIdField):
                continue
            if operation.name != 'aid':
                continue
            if operation.field.null:
                continue
            default_operations.append(
                migrations.RunPython(
                    code=functools.partial(
                        set_default_forwards, self.app_name, operation,
                    ),
                    reverse_code=functools.partial(
                        set_default_reverse, self.app_name, operation,
                    ),
                )
            )
        return default_operations + operations
