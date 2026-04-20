from django.db import migrations

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS `register_cashbankmovement` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `church_id` bigint NOT NULL,
  `date` date NOT NULL,
  `amount` decimal(12,2) NOT NULL,
  `direction` varchar(32) NOT NULL,
  `source_type` varchar(24) NOT NULL DEFAULT 'TRANSFER_ONLY',
  `source_id` bigint DEFAULT NULL,
  `memo` varchar(255) NOT NULL DEFAULT '',
  `reference_no` varchar(64) NOT NULL DEFAULT '',
  `proof_file` varchar(100) DEFAULT NULL,
  `status` varchar(16) NOT NULL DEFAULT 'PENDING',
  `created_by_id` bigint DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_cbm_church_date` (`church_id`, `date`),
  KEY `idx_cbm_church_direction_date` (`church_id`, `direction`, `date`),
  KEY `idx_cbm_source_type_source_id` (`source_type`, `source_id`),
  KEY `idx_cbm_church_status_date` (`church_id`, `status`, `date`),
  KEY `idx_cbm_created_by` (`created_by_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
"""

DROP_SQL = """
DROP TABLE IF EXISTS `register_cashbankmovement`;
"""

class Migration(migrations.Migration):

    dependencies = [
        ("Register", "0028_repair_register_releasedbudget"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_SQL,
            reverse_sql=DROP_SQL,
        ),
    ]