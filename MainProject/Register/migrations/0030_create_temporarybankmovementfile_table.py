from django.db import migrations

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS `register_temporarybankmovementfile` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `file` varchar(100) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
"""

DROP_SQL = """
DROP TABLE IF EXISTS `register_temporarybankmovementfile`;
"""

class Migration(migrations.Migration):

    dependencies = [
        ("Register", "0029_create_cashbankmovement_table"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_SQL,
            reverse_sql=DROP_SQL,
        ),
    ]