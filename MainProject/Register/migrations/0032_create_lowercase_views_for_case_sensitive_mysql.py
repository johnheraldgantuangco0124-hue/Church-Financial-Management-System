from django.db import migrations


def create_lowercase_views(apps, schema_editor):
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        cursor.execute("SHOW FULL TABLES")
        rows = cursor.fetchall()

        # rows usually look like: (table_name, 'BASE TABLE') or (table_name, 'VIEW')
        objects = {}
        for row in rows:
            if len(row) >= 2:
                objects[row[0]] = row[1]

        prefixes = ("Register_", "Church_")

        for obj_name, obj_type in objects.items():
            if obj_type != "BASE TABLE":
                continue

            if not obj_name.startswith(prefixes):
                continue

            lower_name = obj_name.lower()

            # Skip if lowercase object already exists as a table or view
            if lower_name in objects:
                continue

            cursor.execute(
                f"CREATE VIEW `{lower_name}` AS SELECT * FROM `{obj_name}`"
            )


def drop_lowercase_views(apps, schema_editor):
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        cursor.execute("SHOW FULL TABLES")
        rows = cursor.fetchall()

        objects = {}
        for row in rows:
            if len(row) >= 2:
                objects[row[0]] = row[1]

        prefixes = ("Register_", "Church_")

        for obj_name, obj_type in objects.items():
            if obj_type != "BASE TABLE":
                continue

            if not obj_name.startswith(prefixes):
                continue

            lower_name = obj_name.lower()

            # Only drop lowercase object if it exists and is a VIEW
            if objects.get(lower_name) == "VIEW":
                cursor.execute(f"DROP VIEW `{lower_name}`")


class Migration(migrations.Migration):

    dependencies = [
        ("Register", "0031_create_bankaccount_table"),
        ("Church", "0004_alter_churchapplication_options_and_more"),
    ]

    operations = [
        migrations.RunPython(
            create_lowercase_views,
            reverse_code=drop_lowercase_views,
        ),
    ]