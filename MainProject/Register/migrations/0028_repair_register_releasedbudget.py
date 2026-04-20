from django.db import migrations

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS `register_releasedbudget` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `date_released` date NOT NULL,
  `amount` decimal(12,2) NOT NULL,
  `remarks` varchar(255) NOT NULL,
  `released_at` datetime(6) NOT NULL,
  `budget_id` bigint NOT NULL,
  `released_by_id` bigint DEFAULT NULL,
  `approved_request_id` bigint DEFAULT NULL,
  `church_id` bigint DEFAULT NULL,
  `amount_returned` decimal(12,2) NOT NULL,
  `is_liquidated` tinyint(1) NOT NULL,
  `ministry_id` bigint DEFAULT NULL,
  `budget_return_income_id` bigint DEFAULT NULL,
  `liquidated_date` date DEFAULT NULL,
  `deduct_from` varchar(10) NOT NULL,
  `return_to` varchar(10) NOT NULL,
  `cash_return_txn_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `approved_request_id` (`approved_request_id`),
  UNIQUE KEY `budget_return_income_id` (`budget_return_income_id`),
  UNIQUE KEY `cash_return_txn_id` (`cash_return_txn_id`),
  KEY `idx_releasedbudget_budget_id` (`budget_id`),
  KEY `idx_releasedbudget_released_by_id` (`released_by_id`),
  KEY `idx_releasedbudget_church_id` (`church_id`),
  KEY `idx_releasedbudget_ministry_id` (`ministry_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
"""

DROP_SQL = """
DROP TABLE IF EXISTS `register_releasedbudget`;
"""

class Migration(migrations.Migration):

    dependencies = [
        ("Register", "0027_expense_vendor"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_SQL,
            reverse_sql=DROP_SQL,
        ),
    ]