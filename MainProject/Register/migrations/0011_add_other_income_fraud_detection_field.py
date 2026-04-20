from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Register", "0010_add_expense_fraud_detection_field"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountingsettings",
            name="enable_other_income_fraud_detection",
            field=models.BooleanField(
                default=False,
                help_text="Enable AI fraud detection for other income proof uploads. Default is OFF.",
            ),
        ),
    ]