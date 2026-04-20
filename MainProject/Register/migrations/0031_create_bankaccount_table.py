from django.db import migrations

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS `register_bankaccount` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `church_id` bigint NOT NULL,
  `bank_name` varchar(100) NOT NULL DEFAULT 'Main Bank Account',
  `account_name` varchar(100) NOT NULL DEFAULT 'Church Account',
  `account_number` varchar(50) NOT NULL,
  `current_balance` decimal(12,2) NOT NULL DEFAULT 0.00,
  `verification_image` varchar(100) NOT NULL,
  `last_updated` datetime(6) NOT NULL,
  `updated_by_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_bankaccount_church_id` (`church_id`),
  UNIQUE KEY `uniq_bankaccount_account_number` (`account_number`),
  KEY `idx_bankaccount_updated_by` (`updated_by_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
"""

DROP_SQL = """
DROP TABLE IF EXISTS `register_bankaccount`;
"""

class Migration(migrations.Migration):

    dependencies = [
        ("Register", "0030_create_temporarybankmovementfile_table"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_SQL,
            reverse_sql=DROP_SQL,
        ),
    ]