from django.db.migrations.operations.base import Operation


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
