-- Cleaned stored procedures extracted from Dump20260416 (1).sql
-- Import this into the same MySQL database used by your Django app.
-- Changes made:
-- - removed DEFINER=`root`@`localhost`
-- - converted each procedure into a portable CREATE PROCEDURE
-- - kept DROP PROCEDURE IF EXISTS for re-runs

DROP PROCEDURE IF EXISTS `Calculate_CashOnHand`;
DELIMITER $$
CREATE PROCEDURE `Calculate_CashOnHand`(
    IN target_church_id BIGINT
)
BEGIN
    DECLARE v_cash_income            DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_cash_exp               DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_deposits               DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_withdrawals            DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_budget_return_cash     DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_legacy_deposits        DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_legacy_withdrawals     DECIMAL(18,2) DEFAULT 0.00;

    /*
      =========================================================
      1) LIQUIDATION RETURNS TO PHYSICAL CASH ONLY
         Only returns explicitly marked return_to='cash'
         should increase physical cash on hand.
      =========================================================
    */
    SELECT COALESCE(SUM(rb.amount_returned), 0.00)
    INTO v_budget_return_cash
    FROM register_releasedbudget rb
    WHERE rb.church_id = target_church_id
      AND COALESCE(rb.is_liquidated, 0) = 1
      AND COALESCE(rb.amount_returned, 0) > 0
      AND LOWER(TRIM(COALESCE(rb.return_to, ''))) = 'cash';

    /*
      =========================================================
      2) CASH INCOME
         Income that truly belongs to physical cash.

         EXCLUDE:
         - anything explicitly received directly to bank
         - budget return OtherIncome rows already handled via
           released budget return logic above
      =========================================================
    */
    SELECT
        COALESCE((
            SELECT SUM(t.amount)
            FROM register_tithe t
            WHERE t.church_id = target_church_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM register_cashbankmovement m
                  WHERE m.church_id = target_church_id
                    AND m.status = 'CONFIRMED'
                    AND m.source_type = 'TITHE'
                    AND m.source_id = t.id
                    AND m.direction IN ('DIRECT_BANK_RECEIPT', 'BANK_TO_BANK')
              )
        ), 0.00)
      + COALESCE((
            SELECT SUM(o.amount)
            FROM register_offering o
            WHERE o.church_id = target_church_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM register_cashbankmovement m
                  WHERE m.church_id = target_church_id
                    AND m.status = 'CONFIRMED'
                    AND m.source_type = 'OFFERING'
                    AND m.source_id = o.id
                    AND m.direction IN ('DIRECT_BANK_RECEIPT', 'BANK_TO_BANK')
              )
        ), 0.00)
      + COALESCE((
            SELECT SUM(d.amount)
            FROM register_donations d
            WHERE d.church_id = target_church_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM register_cashbankmovement m
                  WHERE m.church_id = target_church_id
                    AND m.status = 'CONFIRMED'
                    AND m.source_type = 'DONATION'
                    AND m.source_id = d.id
                    AND m.direction IN ('DIRECT_BANK_RECEIPT', 'BANK_TO_BANK')
              )
        ), 0.00)
      + COALESCE((
            SELECT SUM(oi.amount)
            FROM register_otherincome oi
            WHERE oi.church_id = target_church_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM register_cashbankmovement m
                  WHERE m.church_id = target_church_id
                    AND m.status = 'CONFIRMED'
                    AND m.source_type = 'OTHER_INCOME'
                    AND m.source_id = oi.id
                    AND m.direction IN ('DIRECT_BANK_RECEIPT', 'BANK_TO_BANK')
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM register_releasedbudget rb
                  WHERE rb.church_id = target_church_id
                    AND rb.budget_return_income_id = oi.id
              )
        ), 0.00)
      + COALESCE(v_budget_return_cash, 0.00)
    INTO v_cash_income;

    /*
      =========================================================
      3) REAL CASH/BANK TRANSFERS FROM CASHBANKMOVEMENT
         CASH_TO_BANK  => subtract from physical cash
         BANK_TO_CASH  => add to physical cash
      =========================================================
    */
    SELECT COALESCE(SUM(m.amount), 0.00)
    INTO v_deposits
    FROM register_cashbankmovement m
    WHERE m.church_id = target_church_id
      AND m.status = 'CONFIRMED'
      AND m.direction = 'CASH_TO_BANK';

    SELECT COALESCE(SUM(m.amount), 0.00)
    INTO v_withdrawals
    FROM register_cashbankmovement m
    WHERE m.church_id = target_church_id
      AND m.status = 'CONFIRMED'
      AND m.direction = 'BANK_TO_CASH';

    /*
      =========================================================
      3B) LEGACY BANK DEPOSITS / WITHDRAWALS IN register_expense
         Legacy rows still affect physical cash, but avoid
         double-counting if already represented in cashbankmovement.
      =========================================================
    */
    SELECT COALESCE(SUM(e.amount), 0.00)
    INTO v_legacy_deposits
    FROM register_expense e
    LEFT JOIN register_expensecategory c ON c.id = e.category_id
    WHERE e.church_id = target_church_id
      AND COALESCE(e.status, '') <> 'Rejected'
      AND COALESCE(c.is_system, 0) = 0
      AND COALESCE(c.is_transfer, 0) = 0
      AND (
            LOWER(TRIM(COALESCE(e.description, ''))) LIKE 'bank deposit%'
         OR LOWER(TRIM(COALESCE(c.name, ''))) LIKE 'bank deposit%'
      )
      AND NOT EXISTS (
          SELECT 1
          FROM register_cashbankmovement m
          WHERE m.church_id = target_church_id
            AND m.status = 'CONFIRMED'
            AND m.source_type = 'EXPENSE'
            AND m.source_id = e.id
            AND m.direction = 'CASH_TO_BANK'
      );

    SELECT COALESCE(SUM(e.amount), 0.00)
    INTO v_legacy_withdrawals
    FROM register_expense e
    LEFT JOIN register_expensecategory c ON c.id = e.category_id
    WHERE e.church_id = target_church_id
      AND COALESCE(e.status, '') <> 'Rejected'
      AND COALESCE(c.is_system, 0) = 0
      AND COALESCE(c.is_transfer, 0) = 0
      AND (
            LOWER(TRIM(COALESCE(e.description, ''))) LIKE 'bank withdraw%'
         OR LOWER(TRIM(COALESCE(e.description, ''))) LIKE 'bank withdrawal%'
         OR LOWER(TRIM(COALESCE(c.name, ''))) LIKE 'bank withdraw%'
         OR LOWER(TRIM(COALESCE(c.name, ''))) LIKE 'bank withdrawal%'
      )
      AND NOT EXISTS (
          SELECT 1
          FROM register_cashbankmovement m
          WHERE m.church_id = target_church_id
            AND m.status = 'CONFIRMED'
            AND m.source_type = 'EXPENSE'
            AND m.source_id = e.id
            AND m.direction = 'BANK_TO_CASH'
      );

    SET v_deposits = COALESCE(v_deposits, 0.00) + COALESCE(v_legacy_deposits, 0.00);
    SET v_withdrawals = COALESCE(v_withdrawals, 0.00) + COALESCE(v_legacy_withdrawals, 0.00);

    /*
      =========================================================
      4) CASH EXPENSES
         Expenses that truly reduce PHYSICAL CASH.

         EXCLUDE:
         - Rejected rows
         - system rows
         - transfer rows
         - expenses explicitly paid from bank
         - legacy bank deposit / withdraw rows
         - Budget Release - Bank
         - old legacy "budget return to bank" rows
      =========================================================
    */
    SELECT COALESCE(SUM(e.amount), 0.00)
    INTO v_cash_exp
    FROM register_expense e
    LEFT JOIN register_expensecategory c ON c.id = e.category_id
    WHERE e.church_id = target_church_id
      AND COALESCE(e.status, '') <> 'Rejected'
      AND COALESCE(c.is_system, 0) = 0
      AND COALESCE(c.is_transfer, 0) = 0
      AND NOT EXISTS (
          SELECT 1
          FROM register_cashbankmovement m
          WHERE m.church_id = target_church_id
            AND m.status = 'CONFIRMED'
            AND m.source_type = 'EXPENSE'
            AND m.source_id = e.id
            AND m.direction = 'BANK_PAID_EXPENSE'
      )
      AND NOT (
            LOWER(TRIM(COALESCE(c.name, ''))) LIKE 'bank deposit%'
         OR LOWER(TRIM(COALESCE(c.name, ''))) LIKE 'bank withdraw%'
         OR LOWER(TRIM(COALESCE(c.name, ''))) LIKE 'bank withdrawal%'
         OR LOWER(TRIM(COALESCE(e.description, ''))) LIKE 'bank deposit%'
         OR LOWER(TRIM(COALESCE(e.description, ''))) LIKE 'bank withdraw%'
         OR LOWER(TRIM(COALESCE(e.description, ''))) LIKE 'bank withdrawal%'
         OR LOWER(TRIM(COALESCE(c.name, ''))) = 'budget release - bank'
         OR LOWER(TRIM(COALESCE(e.description, ''))) LIKE 'budget release - bank:%'
         OR LOWER(TRIM(COALESCE(e.description, ''))) LIKE 'budget return to bank%'
      );

    /*
      =========================================================
      5) FINAL PHYSICAL CASH ON HAND
      =========================================================
    */
    SELECT COALESCE(
        v_cash_income - v_cash_exp - v_deposits + v_withdrawals,
        0.00
    ) AS CashOnHand;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `CheckEmailExists`;
DELIMITER $$
CREATE PROCEDURE `CheckEmailExists`(IN input_email VARCHAR(255), OUT email_count INT)
BEGIN
    SELECT COUNT(*) INTO email_count
    FROM register_customuser
    WHERE email = input_email;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Daily_Financial_Summary`;
DELIMITER $$
CREATE PROCEDURE `Daily_Financial_Summary`(
    IN `target_church_id` INT
)
BEGIN
    SELECT
        TransactionDate,

        SUM(CASE WHEN TransactionType = 'Tithe' THEN amount ELSE 0 END) AS TotalTithes,
        SUM(CASE WHEN TransactionType = 'Offering' THEN amount ELSE 0 END) AS TotalOffering,
        SUM(CASE WHEN TransactionType = 'Donations' THEN amount ELSE 0 END) AS TotalDonations,
        SUM(CASE WHEN TransactionType = 'OtherIncome' THEN amount ELSE 0 END) AS TotalOtherIncome,

        /* Keep original summary meaning:
           real expense total = Expense + ReleasedBudget fallback */
        SUM(
            CASE
                WHEN TransactionType IN ('Expense', 'ReleasedBudget') THEN amount
                ELSE 0
            END
        ) AS TotalExpenses,

        /* Accumulated = income - real expenses only
           (Transfer is excluded, ReleasedBudget is counted as outflow) */
        (
            SUM(CASE WHEN TransactionType = 'Tithe' THEN amount ELSE 0 END) +
            SUM(CASE WHEN TransactionType = 'Offering' THEN amount ELSE 0 END) +
            SUM(CASE WHEN TransactionType = 'Donations' THEN amount ELSE 0 END) +
            SUM(CASE WHEN TransactionType = 'OtherIncome' THEN amount ELSE 0 END) -
            SUM(
                CASE
                    WHEN TransactionType IN ('Expense', 'ReleasedBudget') THEN amount
                    ELSE 0
                END
            )
        ) AS TotalAccumulated,

        /* Extra transparency columns */
        SUM(CASE WHEN TransactionType = 'Transfer' THEN amount ELSE 0 END) AS TotalTransfers,
        SUM(CASE WHEN TransactionType = 'ReleasedBudget' THEN amount ELSE 0 END) AS TotalReleasedBudget

    FROM (
        /* 1) Expenses + Transfers (same classification as Finance_SortedbyDate) */
        SELECT
            CASE
                WHEN (
                    COALESCE(ec.is_transfer, 0) = 1
                    OR LOWER(TRIM(COALESCE(ec.name, ''))) IN (
                        'bank deposit',
                        'bank withdraw',
                        'bank withdrawal'
                    )
                    OR LOWER(TRIM(COALESCE(ec.name, ''))) LIKE 'bank depos%'
                    OR LOWER(TRIM(COALESCE(ec.name, ''))) LIKE 'bank withdr%'
                    OR LOWER(TRIM(COALESCE(e.description, ''))) LIKE '%bank depos%'
                    OR LOWER(TRIM(COALESCE(e.description, ''))) LIKE '%bank withdr%'
                )
                THEN 'Transfer'
                ELSE 'Expense'
            END AS TransactionType,
            e.expense_date AS TransactionDate,
            e.amount AS amount
        FROM register_expense e
        LEFT JOIN register_expensecategory ec
               ON ec.id = e.category_id
        WHERE e.church_id = target_church_id
          AND COALESCE(e.status, '') <> 'Rejected'

        UNION ALL

        /* 2) Offerings */
        SELECT
            'Offering' AS TransactionType,
            o.date AS TransactionDate,
            o.amount AS amount
        FROM register_offering o
        WHERE o.church_id = target_church_id

        UNION ALL

        /* 3) Donations */
        SELECT
            'Donations' AS TransactionType,
            d.donations_date AS TransactionDate,
            d.amount AS amount
        FROM register_donations d
        WHERE d.church_id = target_church_id

        UNION ALL

        /* 4) Tithes */
        SELECT
            'Tithe' AS TransactionType,
            t.date AS TransactionDate,
            t.amount AS amount
        FROM register_tithe t
        WHERE t.church_id = target_church_id

        UNION ALL

        /* 5) Other Income */
        SELECT
            'OtherIncome' AS TransactionType,
            oi.date AS TransactionDate,
            oi.amount AS amount
        FROM register_otherincome oi
        WHERE oi.church_id = target_church_id

        UNION ALL

        /* 6) ReleasedBudget fallback rows
              Same fallback idea as Finance_SortedbyDate,
              but typed as ReleasedBudget instead of forcing Expense */
        SELECT
            'ReleasedBudget' AS TransactionType,
            rb.date_released AS TransactionDate,
            rb.amount AS amount
        FROM register_releasedbudget rb
        WHERE rb.church_id = target_church_id
          AND NOT EXISTS (
                SELECT 1
                FROM register_expense e2
                LEFT JOIN register_expensecategory ec2
                       ON ec2.id = e2.category_id
                WHERE e2.church_id = rb.church_id
                  AND COALESCE(e2.status, '') <> 'Rejected'
                  AND (
                        LOWER(TRIM(COALESCE(e2.description, ''))) LIKE CONCAT('%release id ', rb.id, '%')
                        OR (
                            LOWER(TRIM(COALESCE(ec2.name, ''))) IN (
                                'budget release',
                                'budget release - cash',
                                'budget release - bank'
                            )
                            AND e2.amount = rb.amount
                        )
                  )
          )
    ) AS Transactions

    GROUP BY TransactionDate
    ORDER BY TransactionDate DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Denomination_Daily_Financial_Summary`;
DELIMITER $$
CREATE PROCEDURE `Denomination_Daily_Financial_Summary`(
    IN p_denomination_id BIGINT
)
BEGIN
    /*
      Daily summary across ALL churches under a denomination.
      Output columns:
        SummaryDate, TotalTithes, TotalOffering, TotalDonations, TotalExpenses, TotalNet, TotalAccumulated
    */

    WITH daily AS (
        /* ---------------- TITHES ---------------- */
        SELECT
            t.date AS SummaryDate,
            SUM(t.amount) AS Tithes,
            0 AS Offering,
            0 AS Donations,
            0 AS Expenses
        FROM register_tithe t
        JOIN church_church c ON c.id = t.church_id
        WHERE c.denomination_id = p_denomination_id
        GROUP BY t.date

        UNION ALL

        /* --------------- OFFERING --------------- */
        SELECT
            o.date AS SummaryDate,
            0,
            SUM(o.amount),
            0,
            0
        FROM register_offering o
        JOIN church_church c ON c.id = o.church_id
        WHERE c.denomination_id = p_denomination_id
        GROUP BY o.date

        UNION ALL

        /* -------------- DONATIONS --------------- */
        SELECT
            d.donations_date AS SummaryDate,
            0,
            0,
            SUM(d.amount),
            0
        FROM register_donations d
        JOIN church_church c ON c.id = d.church_id
        WHERE c.denomination_id = p_denomination_id
        GROUP BY d.donations_date

        UNION ALL

        /* -------------- EXPENSES ---------------- */
        SELECT
            e.expense_date AS SummaryDate,
            0,
            0,
            0,
            SUM(e.amount)
        FROM register_expense e
        JOIN church_church c ON c.id = e.church_id
        WHERE c.denomination_id = p_denomination_id
        GROUP BY e.expense_date
    ),
    grouped AS (
        SELECT
            SummaryDate,
            SUM(Tithes)   AS TotalTithes,
            SUM(Offering) AS TotalOffering,
            SUM(Donations) AS TotalDonations,
            SUM(Expenses) AS TotalExpenses,
            (SUM(Tithes) + SUM(Offering) + SUM(Donations) - SUM(Expenses)) AS TotalNet
        FROM daily
        GROUP BY SummaryDate
    )
    SELECT
        SummaryDate,
        TotalTithes,
        TotalOffering,
        TotalDonations,
        TotalExpenses,
        TotalNet,
        /* Running total (accumulated) */
        SUM(TotalNet) OVER (ORDER BY SummaryDate) AS TotalAccumulated
    FROM grouped
    ORDER BY SummaryDate DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Denomination_Financial_ByChurch`;
DELIMITER $$
CREATE PROCEDURE `Denomination_Financial_ByChurch`(
    IN p_denomination_id BIGINT
)
BEGIN
    SELECT
        c.id   AS ChurchID,
        c.name AS ChurchName,

        COALESCE((SELECT SUM(t.amount)  FROM register_tithe t       WHERE t.church_id = c.id), 0) AS TotalTithes,
        COALESCE((SELECT SUM(o.amount)  FROM register_offering o    WHERE o.church_id = c.id), 0) AS TotalOffering,
        COALESCE((SELECT SUM(d.amount)  FROM register_donations d   WHERE d.church_id = c.id), 0) AS TotalDonations,
        COALESCE((SELECT SUM(oi.amount) FROM register_otherincome oi WHERE oi.church_id = c.id), 0) AS TotalOtherIncome,
        COALESCE((SELECT SUM(e.amount)  FROM register_expense e     WHERE e.church_id = c.id), 0) AS TotalExpenses,

        (
            COALESCE((SELECT SUM(t.amount)  FROM register_tithe t        WHERE t.church_id = c.id), 0) +
            COALESCE((SELECT SUM(o.amount)  FROM register_offering o     WHERE o.church_id = c.id), 0) +
            COALESCE((SELECT SUM(d.amount)  FROM register_donations d    WHERE d.church_id = c.id), 0) +
            COALESCE((SELECT SUM(oi.amount) FROM register_otherincome oi WHERE oi.church_id = c.id), 0)
        ) AS TotalIncome,

        (
            (
                COALESCE((SELECT SUM(t.amount)  FROM register_tithe t        WHERE t.church_id = c.id), 0) +
                COALESCE((SELECT SUM(o.amount)  FROM register_offering o     WHERE o.church_id = c.id), 0) +
                COALESCE((SELECT SUM(d.amount)  FROM register_donations d    WHERE d.church_id = c.id), 0) +
                COALESCE((SELECT SUM(oi.amount) FROM register_otherincome oi WHERE oi.church_id = c.id), 0)
            )
            - COALESCE((SELECT SUM(e.amount) FROM register_expense e WHERE e.church_id = c.id), 0)
        ) AS NetBalance

    FROM church_church c
    WHERE c.denomination_id = p_denomination_id
    ORDER BY c.name ASC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Denomination_Overall_Financial_Overview`;
DELIMITER $$
CREATE PROCEDURE `Denomination_Overall_Financial_Overview`(
    IN p_denomination_id BIGINT
)
BEGIN
    /*
      Overall totals for ALL churches under a denomination (all-time up to today).
      Returns 1 row.
    */

    SELECT
        /* Income */
        COALESCE((
            SELECT SUM(t.amount)
            FROM register_tithe t
            JOIN church_church c ON c.id = t.church_id
            WHERE c.denomination_id = p_denomination_id
        ), 0) AS TotalTithes,

        COALESCE((
            SELECT SUM(o.amount)
            FROM register_offering o
            JOIN church_church c ON c.id = o.church_id
            WHERE c.denomination_id = p_denomination_id
        ), 0) AS TotalOffering,

        COALESCE((
            SELECT SUM(d.amount)
            FROM register_donations d
            JOIN church_church c ON c.id = d.church_id
            WHERE c.denomination_id = p_denomination_id
        ), 0) AS TotalDonations,

        COALESCE((
            SELECT SUM(oi.amount)
            FROM register_otherincome oi
            JOIN church_church c ON c.id = oi.church_id
            WHERE c.denomination_id = p_denomination_id
        ), 0) AS TotalOtherIncome,

        /* Total income (sum of all income sources above) */
        (
            COALESCE((
                SELECT SUM(t.amount)
                FROM register_tithe t
                JOIN church_church c ON c.id = t.church_id
                WHERE c.denomination_id = p_denomination_id
            ), 0)
            +
            COALESCE((
                SELECT SUM(o.amount)
                FROM register_offering o
                JOIN church_church c ON c.id = o.church_id
                WHERE c.denomination_id = p_denomination_id
            ), 0)
            +
            COALESCE((
                SELECT SUM(d.amount)
                FROM register_donations d
                JOIN church_church c ON c.id = d.church_id
                WHERE c.denomination_id = p_denomination_id
            ), 0)
            +
            COALESCE((
                SELECT SUM(oi.amount)
                /* if you don't have otherincome, remove this block */
                FROM register_otherincome oi
                JOIN church_church c ON c.id = oi.church_id
                WHERE c.denomination_id = p_denomination_id
            ), 0)
        ) AS TotalIncome,

        /* Expenses */
        COALESCE((
            SELECT SUM(e.amount)
            FROM register_expense e
            JOIN church_church c ON c.id = e.church_id
            WHERE c.denomination_id = p_denomination_id
        ), 0) AS TotalExpenses,

        /* Net */
        (
            (
                COALESCE((SELECT SUM(t.amount) FROM register_tithe t JOIN church_church c ON c.id=t.church_id WHERE c.denomination_id=p_denomination_id),0)
                +
                COALESCE((SELECT SUM(o.amount) FROM register_offering o JOIN church_church c ON c.id=o.church_id WHERE c.denomination_id=p_denomination_id),0)
                +
                COALESCE((SELECT SUM(d.amount) FROM register_donations d JOIN church_church c ON c.id=d.church_id WHERE c.denomination_id=p_denomination_id),0)
                +
                COALESCE((SELECT SUM(oi.amount) FROM register_otherincome oi JOIN church_church c ON c.id=oi.church_id WHERE c.denomination_id=p_denomination_id),0)
            )
            -
            COALESCE((SELECT SUM(e.amount) FROM register_expense e JOIN church_church c ON c.id=e.church_id WHERE c.denomination_id=p_denomination_id),0)
        ) AS NetBalance,

        /* last transaction date across all types (optional but useful) */
        (
            SELECT MAX(last_dt)
            FROM (
                SELECT MAX(t.date) AS last_dt
                FROM register_tithe t JOIN church_church c ON c.id=t.church_id
                WHERE c.denomination_id = p_denomination_id

                UNION ALL
                SELECT MAX(o.date)
                FROM register_offering o JOIN church_church c ON c.id=o.church_id
                WHERE c.denomination_id = p_denomination_id

                UNION ALL
                SELECT MAX(d.donations_date)
                FROM register_donations d JOIN church_church c ON c.id=d.church_id
                WHERE c.denomination_id = p_denomination_id

                UNION ALL
                SELECT MAX(oi.date)
                FROM register_otherincome oi JOIN church_church c ON c.id=oi.church_id
                WHERE c.denomination_id = p_denomination_id

                UNION ALL
                SELECT MAX(e.expense_date)
                FROM register_expense e JOIN church_church c ON c.id=e.church_id
                WHERE c.denomination_id = p_denomination_id
            ) x
        ) AS LastTxnDate;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Filtered_Financial_Summary`;
DELIMITER $$
CREATE PROCEDURE `Filtered_Financial_Summary`(
    IN `chosen_date` DATE,
    IN `target_church_id` INT
)
BEGIN
    SELECT
        TransactionDate,
        SUM(CASE WHEN TransactionType = 'Tithe' THEN amount ELSE 0 END) AS TotalTithes,
        SUM(CASE WHEN TransactionType = 'Offering' THEN amount ELSE 0 END) AS TotalOffering,
        SUM(CASE WHEN TransactionType = 'Donations' THEN amount ELSE 0 END) AS TotalDonations,
        SUM(CASE WHEN TransactionType = 'OtherIncome' THEN amount ELSE 0 END) AS TotalOtherIncome,
        SUM(CASE WHEN TransactionType = 'Expense' THEN amount ELSE 0 END) AS TotalExpenses,
        (
            SUM(CASE WHEN TransactionType = 'Tithe' THEN amount ELSE 0 END) +
            SUM(CASE WHEN TransactionType = 'Offering' THEN amount ELSE 0 END) +
            SUM(CASE WHEN TransactionType = 'Donations' THEN amount ELSE 0 END) +
            SUM(CASE WHEN TransactionType = 'OtherIncome' THEN amount ELSE 0 END) -
            SUM(CASE WHEN TransactionType = 'Expense' THEN amount ELSE 0 END)
        ) AS TotalAccumulated
    FROM (
        /* 1) EXPENSES (exclude only transfers) */
        SELECT 'Expense' AS TransactionType, e.expense_date AS TransactionDate, e.amount
        FROM register_expense e
        LEFT JOIN register_expensecategory ec ON ec.id = e.category_id
        WHERE e.church_id = target_church_id
          AND COALESCE(e.status,'') <> 'Rejected'
          AND NOT (
                COALESCE(ec.is_transfer,0)=1
             OR LOWER(TRIM(COALESCE(ec.name,''))) IN ('bank deposit','bank withdraw','bank withdrawal')
             OR LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank depos%'
             OR LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank withdr%'
             OR LOWER(TRIM(COALESCE(e.description,''))) LIKE '%bank depos%'
             OR LOWER(TRIM(COALESCE(e.description,''))) LIKE '%bank withdr%'
          )

        UNION ALL

        /* 2) OFFERINGS */
        SELECT 'Offering', o.date, o.amount
        FROM register_offering o
        WHERE o.church_id = target_church_id

        UNION ALL

        /* 3) DONATIONS */
        SELECT 'Donations', d.donations_date, d.amount
        FROM register_donations d
        WHERE d.church_id = target_church_id

        UNION ALL

        /* 4) TITHES */
        SELECT 'Tithe', t.date, t.amount
        FROM register_tithe t
        WHERE t.church_id = target_church_id

        UNION ALL

        /* 5) OTHER INCOME */
        SELECT 'OtherIncome', oi.date, oi.amount
        FROM register_otherincome oi
        WHERE oi.church_id = target_church_id

    ) AS Transactions
    WHERE TransactionDate = chosen_date
    GROUP BY TransactionDate
    ORDER BY TransactionDate DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Filter_Monthly_Summary`;
DELIMITER $$
CREATE PROCEDURE `Filter_Monthly_Summary`(
    IN `filter_date` DATE,
    IN `target_church_id` INT
)
BEGIN
    SELECT
        YEAR(TransactionDate) AS Year,
        MONTH(TransactionDate) AS Month,
        SUM(CASE WHEN TransactionType = 'Tithe' THEN amount ELSE 0 END) AS TotalTithes,
        SUM(CASE WHEN TransactionType = 'Offering' THEN amount ELSE 0 END) AS TotalOffering,
        SUM(CASE WHEN TransactionType = 'Donations' THEN amount ELSE 0 END) AS TotalDonations,
        SUM(CASE WHEN TransactionType = 'OtherIncome' THEN amount ELSE 0 END) AS TotalOtherIncome,
        SUM(CASE WHEN TransactionType = 'Expense' THEN amount ELSE 0 END) AS TotalExpenses,
        (
            SUM(CASE WHEN TransactionType = 'Tithe' THEN amount ELSE 0 END) +
            SUM(CASE WHEN TransactionType = 'Offering' THEN amount ELSE 0 END) +
            SUM(CASE WHEN TransactionType = 'Donations' THEN amount ELSE 0 END) +
            SUM(CASE WHEN TransactionType = 'OtherIncome' THEN amount ELSE 0 END) -
            SUM(CASE WHEN TransactionType = 'Expense' THEN amount ELSE 0 END)
        ) AS TotalAccumulated
    FROM (
        /* 1) EXPENSES (exclude only transfers) */
        SELECT 'Expense' AS TransactionType, e.expense_date AS TransactionDate, e.amount
        FROM register_expense e
        LEFT JOIN register_expensecategory ec ON ec.id = e.category_id
        WHERE e.church_id = target_church_id
          AND COALESCE(e.status,'') <> 'Rejected'
          AND NOT (
                COALESCE(ec.is_transfer,0)=1
             OR LOWER(TRIM(COALESCE(ec.name,''))) IN ('bank deposit','bank withdraw','bank withdrawal')
             OR LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank depos%'
             OR LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank withdr%'
             OR LOWER(TRIM(COALESCE(e.description,''))) LIKE '%bank depos%'
             OR LOWER(TRIM(COALESCE(e.description,''))) LIKE '%bank withdr%'
          )

        UNION ALL

        /* 2) OFFERINGS */
        SELECT 'Offering', o.date, o.amount
        FROM register_offering o
        WHERE o.church_id = target_church_id

        UNION ALL

        /* 3) DONATIONS */
        SELECT 'Donations', d.donations_date, d.amount
        FROM register_donations d
        WHERE d.church_id = target_church_id

        UNION ALL

        /* 4) TITHES */
        SELECT 'Tithe', t.date, t.amount
        FROM register_tithe t
        WHERE t.church_id = target_church_id

        UNION ALL

        /* 5) OTHER INCOME */
        SELECT 'OtherIncome', oi.date, oi.amount
        FROM register_otherincome oi
        WHERE oi.church_id = target_church_id

    ) AS Transactions
    WHERE DATE_FORMAT(TransactionDate, '%Y-%m') = DATE_FORMAT(filter_date, '%Y-%m')
    GROUP BY YEAR(TransactionDate), MONTH(TransactionDate)
    ORDER BY Year DESC, Month DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_BankCashFlow_ByPeriod`;
DELIMITER $$
CREATE PROCEDURE `Finance_BankCashFlow_ByPeriod`(
    IN target_church_id BIGINT,
    IN report_type VARCHAR(20)   -- 'weekly','monthly','yearly'
)
BEGIN
    SET report_type = LOWER(TRIM(report_type));

    SELECT
        x.SortKey,
        x.DisplayLabel,
        COALESCE(SUM(x.DepositAmount), 0) AS Deposits,
        COALESCE(SUM(x.WithdrawalAmount), 0) AS Withdrawals
    FROM (
        SELECT
            CAST(
                CASE
                    WHEN report_type = 'weekly'  THEN YEARWEEK(m.date, 1)
                    WHEN report_type = 'monthly' THEN DATE_FORMAT(m.date, '%Y-%m')
                    ELSE DATE_FORMAT(m.date, '%Y')
                END AS CHAR
            ) AS SortKey,

            CASE
                WHEN report_type = 'weekly'  THEN DATE_FORMAT(m.date, '%x-%v')
                WHEN report_type = 'monthly' THEN DATE_FORMAT(m.date, '%M %Y')
                ELSE DATE_FORMAT(m.date, '%Y')
            END AS DisplayLabel,

            CASE
                WHEN UPPER(TRIM(COALESCE(m.direction, ''))) = 'CASH_TO_BANK'
                THEN m.amount
                ELSE 0
            END AS DepositAmount,

            CASE
                WHEN UPPER(TRIM(COALESCE(m.direction, ''))) = 'BANK_TO_CASH'
                THEN m.amount
                ELSE 0
            END AS WithdrawalAmount
        FROM register_cashbankmovement m
        WHERE m.church_id = target_church_id
          AND UPPER(TRIM(COALESCE(m.status, ''))) = 'CONFIRMED'
          AND UPPER(TRIM(COALESCE(m.direction, ''))) IN ('CASH_TO_BANK', 'BANK_TO_CASH')
    ) x
    GROUP BY x.SortKey, x.DisplayLabel
    ORDER BY x.SortKey DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_BankTransferTotals`;
DELIMITER $$
CREATE PROCEDURE `Finance_BankTransferTotals`(
    IN target_church_id BIGINT
)
BEGIN
    DECLARE v_deposits DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_withdrawals DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_bank_balance DECIMAL(18,2) DEFAULT 0.00;

    /* Deposits */
    SELECT COALESCE(SUM(e.amount),0)
    INTO v_deposits
    FROM register_expense e
    LEFT JOIN register_expensecategory ec ON ec.id = e.category_id
    WHERE e.church_id = target_church_id
      AND COALESCE(e.status,'') <> 'Rejected'
      AND (
            /* preferred: flagged transfer deposit category */
            (COALESCE(ec.is_transfer,0)=1 AND LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank depos%')
            /* fallback: category name */
         OR LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank depos%'
            /* fallback: expense description */
         OR LOWER(TRIM(COALESCE(e.description,''))) LIKE '%bank depos%'
      );

    /* Withdrawals */
    SELECT COALESCE(SUM(e.amount),0)
    INTO v_withdrawals
    FROM register_expense e
    LEFT JOIN register_expensecategory ec ON ec.id = e.category_id
    WHERE e.church_id = target_church_id
      AND COALESCE(e.status,'') <> 'Rejected'
      AND (
            (COALESCE(ec.is_transfer,0)=1 AND LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank withdr%')
         OR LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank withdr%'
         OR LOWER(TRIM(COALESCE(e.description,''))) LIKE '%bank withdr%'
      );

    /* Stored bank balance (change table name if yours differs) */
    SELECT COALESCE((
        SELECT b.current_balance
        FROM register_bankaccount b
        WHERE b.church_id = target_church_id
        LIMIT 1
    ),0.00)
    INTO v_bank_balance;

    SELECT
        v_deposits AS TotalDeposits,
        v_withdrawals AS TotalWithdrawals,
        (v_deposits - v_withdrawals) AS NetTransfers,
        v_bank_balance AS BankBalanceStored,
        (v_bank_balance - (v_deposits - v_withdrawals)) AS ImpliedStartingOrAdjustments;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_CashPositionTotals`;
DELIMITER $$
CREATE PROCEDURE `Finance_CashPositionTotals`(
    IN target_church_id BIGINT
)
BEGIN
    DECLARE v_unres_income DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_res_income   DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_total_income DECIMAL(18,2) DEFAULT 0.00;

    DECLARE v_unres_oper_exp DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_res_oper_exp   DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_oper_exp       DECIMAL(18,2) DEFAULT 0.00;

    DECLARE v_deposits   DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_withdrawals DECIMAL(18,2) DEFAULT 0.00;

    DECLARE v_physical_cash DECIMAL(18,2) DEFAULT 0.00;

    DECLARE v_bank_stored DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_bank_flow   DECIMAL(18,2) DEFAULT 0.00; -- deposits - withdrawals
    DECLARE v_bank_opening_or_adjustment DECIMAL(18,2) DEFAULT 0.00;

    DECLARE v_unres_balance DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_res_balance   DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_total_fund_balance DECIMAL(18,2) DEFAULT 0.00;

    DECLARE v_total_cash_position DECIMAL(18,2) DEFAULT 0.00;

    /* =========================
       1) INCOME (split unres/res)
       ========================= */
    -- Unrestricted income = tithes + offerings + unrestricted donations + unrestricted other income
    SELECT
      COALESCE((SELECT SUM(amount) FROM register_tithe WHERE church_id = target_church_id),0)
    + COALESCE((SELECT SUM(amount) FROM register_offering WHERE church_id = target_church_id),0)
    + COALESCE((
        SELECT SUM(d.amount)
        FROM register_donations d
        JOIN register_donationcategory dc ON dc.id=d.donations_type_id
        WHERE d.church_id=target_church_id AND COALESCE(dc.is_restricted,0)=0
      ),0)
    + COALESCE((
        SELECT SUM(oi.amount)
        FROM register_otherincome oi
        JOIN register_otherincomecategory oic ON oic.id=oi.income_type_id
        WHERE oi.church_id=target_church_id AND COALESCE(oic.is_restricted,0)=0
      ),0)
    INTO v_unres_income;

    -- Restricted income = restricted donations + restricted other income
    SELECT
      COALESCE((
        SELECT SUM(d.amount)
        FROM register_donations d
        JOIN register_donationcategory dc ON dc.id=d.donations_type_id
        WHERE d.church_id=target_church_id AND COALESCE(dc.is_restricted,0)=1
      ),0)
    + COALESCE((
        SELECT SUM(oi.amount)
        FROM register_otherincome oi
        JOIN register_otherincomecategory oic ON oic.id=oi.income_type_id
        WHERE oi.church_id=target_church_id AND COALESCE(oic.is_restricted,0)=1
      ),0)
    INTO v_res_income;

    SET v_total_income = v_unres_income + v_res_income;

    /* =========================
       2) OPERATING EXPENSES ONLY
          (exclude transfer/system/rejected)
       ========================= */
    -- Unrestricted operating expenses = not restricted markers
    SELECT COALESCE(SUM(e.amount),0)
    INTO v_unres_oper_exp
    FROM register_expense e
    LEFT JOIN register_expensecategory ec ON ec.id=e.category_id
    WHERE e.church_id=target_church_id
      AND COALESCE(e.status,'') <> 'Rejected'
      AND COALESCE(ec.is_transfer,0)=0
      AND COALESCE(ec.is_system,0)=0
      AND NOT (
          COALESCE(ec.description,'') LIKE '%Synced Restricted Donation%'
          OR COALESCE(ec.description,'') LIKE '%Auto-generated restricted fund%'
          OR COALESCE(ec.description,'') LIKE '%Synced Restricted Income%'
      );

    -- Restricted operating expenses = restricted markers
    SELECT COALESCE(SUM(e.amount),0)
    INTO v_res_oper_exp
    FROM register_expense e
    LEFT JOIN register_expensecategory ec ON ec.id=e.category_id
    WHERE e.church_id=target_church_id
      AND COALESCE(e.status,'') <> 'Rejected'
      AND COALESCE(ec.is_transfer,0)=0
      AND COALESCE(ec.is_system,0)=0
      AND (
          COALESCE(ec.description,'') LIKE '%Synced Restricted Donation%'
          OR COALESCE(ec.description,'') LIKE '%Auto-generated restricted fund%'
          OR COALESCE(ec.description,'') LIKE '%Synced Restricted Income%'
      );

    SET v_oper_exp = v_unres_oper_exp + v_res_oper_exp;

    /* =========================
       3) TRANSFERS (Deposits/Withdrawals)
       ========================= */
    SELECT COALESCE(SUM(e.amount),0)
    INTO v_deposits
    FROM register_expense e
    JOIN register_expensecategory ec ON ec.id=e.category_id
    WHERE e.church_id=target_church_id
      AND COALESCE(e.status,'') <> 'Rejected'
      AND COALESCE(ec.is_transfer,0)=1
      AND LOWER(TRIM(COALESCE(ec.name,'')))='bank deposit';

    SELECT COALESCE(SUM(e.amount),0)
    INTO v_withdrawals
    FROM register_expense e
    JOIN register_expensecategory ec ON ec.id=e.category_id
    WHERE e.church_id=target_church_id
      AND COALESCE(e.status,'') <> 'Rejected'
      AND COALESCE(ec.is_transfer,0)=1
      AND LOWER(TRIM(COALESCE(ec.name,''))) IN ('bank withdraw','bank withdrawal');

    SET v_bank_flow = v_deposits - v_withdrawals;

    /* =========================
       4) PHYSICAL CASH (computed)
       PhysicalCash = TotalIncome - OperatingExpenses - Deposits + Withdrawals
       ========================= */
    SET v_physical_cash = v_total_income - v_oper_exp - v_deposits + v_withdrawals;

    /* =========================
       5) BANK BALANCE (stored)
       ========================= */
    SELECT COALESCE((
        SELECT b.current_balance
        FROM register_bankaccount b
        WHERE b.church_id = target_church_id
        LIMIT 1
    ), 0.00) INTO v_bank_stored;

    -- This tells you how much of bank_stored is "not explained" by deposits/withdrawals
    -- (opening balance, manual overrides, adjustments)
    SET v_bank_opening_or_adjustment = v_bank_stored - v_bank_flow;

    /* =========================
       6) FUND BALANCES
       ========================= */
    SET v_unres_balance = v_unres_income - v_unres_oper_exp;
    SET v_res_balance   = v_res_income - v_res_oper_exp;
    SET v_total_fund_balance = v_unres_balance + v_res_balance;

    /* =========================
       7) TOTAL CASH POSITION
       ========================= */
    SET v_total_cash_position = v_physical_cash + v_bank_stored;

    SELECT
        v_total_income AS TotalIncome,
        v_oper_exp     AS OperatingExpenses,
        v_deposits     AS TotalDeposits,
        v_withdrawals  AS TotalWithdrawals,

        v_physical_cash AS PhysicalCash,

        v_bank_stored AS BankBalanceStored,
        v_bank_flow   AS BankBalanceFromTransfers,
        v_bank_opening_or_adjustment AS BankOpeningOrManualAdjustments,

        v_unres_income AS UnrestrictedIncome,
        v_unres_oper_exp AS UnrestrictedExpenses,
        v_unres_balance AS UnrestrictedBalance,

        v_res_income AS RestrictedIncome,
        v_res_oper_exp AS RestrictedExpenses,
        v_res_balance AS RestrictedBalance,

        v_total_fund_balance AS TotalFundBalance,
        v_total_cash_position AS TotalCashPosition;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_FilterByDate`;
DELIMITER $$
CREATE PROCEDURE `Finance_FilterByDate`(
        IN `target_date` DATE,
        IN `target_church_id` BIGINT
    )
BEGIN
        /* 1) Expenses + Transfers */
        SELECT
            CASE
                WHEN (
                    COALESCE(cat.is_transfer,0)=1
                    OR LOWER(TRIM(COALESCE(cat.name,''))) IN (
                        'bank deposit',
                        'bank withdraw',
                        'bank withdrawal'
                    )
                    OR LOWER(TRIM(COALESCE(cat.name,''))) LIKE 'bank depos%'
                    OR LOWER(TRIM(COALESCE(cat.name,''))) LIKE 'bank withdr%'
                    OR LOWER(TRIM(COALESCE(re.description,''))) LIKE '%bank depos%'
                    OR LOWER(TRIM(COALESCE(re.description,''))) LIKE '%bank withdr%'
                )
                THEN 'Transfer'
                ELSE 'Expense'
            END AS TransactionType,
            re.id AS TransactionID,
            re.expense_date AS TransactionDate,
            COALESCE(cat.name, 'Uncategorized') AS Typeof,
            re.description AS TypeOthers,
            re.amount AS amount,
            created_by.id AS UserID,
            created_by.first_name AS CreatedByName,
            edited_by.id AS EditedByID,
            edited_by.first_name AS EditedByName,
            NULL AS donor,
            re.vendor AS vendor,
            re.file AS file,
            cbm.id AS MovementID,
            cbm.direction AS MovementDirection,
            cbm.status AS MovementStatus,
            cbm.memo AS MovementMemo,
            cbm.reference_no AS MovementReferenceNo,
            cbm.proof_file AS MovementProofFile,
            cbm.date AS MovementDate,
            cbm.amount AS MovementAmount
        FROM register_expense re
        LEFT JOIN register_expensecategory AS cat ON re.category_id = cat.id
        LEFT JOIN register_customuser AS created_by ON re.created_by_id = created_by.id
        LEFT JOIN register_customuser AS edited_by ON re.edited_by_id = edited_by.id
        LEFT JOIN register_cashbankmovement AS cbm
               ON cbm.church_id = re.church_id
              AND cbm.source_type = 'EXPENSE'
              AND cbm.source_id = re.id
        WHERE re.church_id = target_church_id
          AND DATE(re.expense_date) = target_date
          AND COALESCE(re.status,'') <> 'Rejected'

        UNION ALL

        /* 2) Offerings */
        SELECT
            'Offering' AS TransactionType,
            ro.id AS TransactionID,
            ro.date AS TransactionDate,
            'Offering' AS Typeof,
            COALESCE(ro.description, '') AS TypeOthers,
            ro.amount AS amount,
            created_by.id AS UserID,
            created_by.first_name AS CreatedByName,
            edited_by.id AS EditedByID,
            edited_by.first_name AS EditedByName,
            NULL AS donor,
            NULL AS vendor,
            ro.proof_document AS file,
            cbm.id AS MovementID,
            cbm.direction AS MovementDirection,
            cbm.status AS MovementStatus,
            cbm.memo AS MovementMemo,
            cbm.reference_no AS MovementReferenceNo,
            cbm.proof_file AS MovementProofFile,
            cbm.date AS MovementDate,
            cbm.amount AS MovementAmount
        FROM register_offering ro
        LEFT JOIN register_customuser AS created_by ON ro.created_by_id = created_by.id
        LEFT JOIN register_customuser AS edited_by ON ro.edited_by_id = edited_by.id
        LEFT JOIN register_cashbankmovement AS cbm
               ON cbm.church_id = ro.church_id
              AND cbm.source_type = 'OFFERING'
              AND cbm.source_id = ro.id
        WHERE ro.church_id = target_church_id
          AND DATE(ro.date) = target_date

        UNION ALL

        /* 3) Donations */
        SELECT
            'Donations' AS TransactionType,
            rd.id AS TransactionID,
            rd.donations_date AS TransactionDate,
            COALESCE(cat.name, 'Uncategorized') AS Typeof,
            rd.other_donations_type AS TypeOthers,
            rd.amount AS amount,
            created_by.id AS UserID,
            created_by.first_name AS CreatedByName,
            edited_by.id AS EditedByID,
            edited_by.first_name AS EditedByName,
            rd.donor AS donor,
            NULL AS vendor,
            rd.receipt_image AS file,
            cbm.id AS MovementID,
            cbm.direction AS MovementDirection,
            cbm.status AS MovementStatus,
            cbm.memo AS MovementMemo,
            cbm.reference_no AS MovementReferenceNo,
            cbm.proof_file AS MovementProofFile,
            cbm.date AS MovementDate,
            cbm.amount AS MovementAmount
        FROM register_donations rd
        LEFT JOIN register_donationcategory AS cat ON rd.donations_type_id = cat.id
        LEFT JOIN register_customuser AS created_by ON rd.created_by_id = created_by.id
        LEFT JOIN register_customuser AS edited_by ON rd.edited_by_id = edited_by.id
        LEFT JOIN register_cashbankmovement AS cbm
               ON cbm.church_id = rd.church_id
              AND cbm.source_type = 'DONATION'
              AND cbm.source_id = rd.id
        WHERE rd.church_id = target_church_id
          AND DATE(rd.donations_date) = target_date

        UNION ALL

        /* 4) Tithes */
        SELECT
            'Tithe' AS TransactionType,
            rt.id AS TransactionID,
            rt.date AS TransactionDate,
            'Tithe' AS Typeof,
            COALESCE(rt.description, '') AS TypeOthers,
            rt.amount AS amount,
            created_by.id AS UserID,
            created_by.first_name AS CreatedByName,
            edited_by.id AS EditedByID,
            edited_by.first_name AS EditedByName,
            NULL AS donor,
            NULL AS vendor,
            rt.file AS file,
            cbm.id AS MovementID,
            cbm.direction AS MovementDirection,
            cbm.status AS MovementStatus,
            cbm.memo AS MovementMemo,
            cbm.reference_no AS MovementReferenceNo,
            cbm.proof_file AS MovementProofFile,
            cbm.date AS MovementDate,
            cbm.amount AS MovementAmount
        FROM register_tithe rt
        LEFT JOIN register_customuser AS created_by ON rt.created_by_id = created_by.id
        LEFT JOIN register_customuser AS edited_by ON rt.edited_by_id = edited_by.id
        LEFT JOIN register_cashbankmovement AS cbm
               ON cbm.church_id = rt.church_id
              AND cbm.source_type = 'TITHE'
              AND cbm.source_id = rt.id
        WHERE rt.church_id = target_church_id
          AND DATE(rt.date) = target_date

        UNION ALL

        /* 5) Other Income */
        SELECT
            'OtherIncome' AS TransactionType,
            roi.id AS TransactionID,
            roi.date AS TransactionDate,
            COALESCE(roic.name, 'Uncategorized') AS Typeof,
            roi.description AS TypeOthers,
            roi.amount AS amount,
            created_by.id AS UserID,
            created_by.first_name AS CreatedByName,
            edited_by.id AS EditedByID,
            edited_by.first_name AS EditedByName,
            NULL AS donor,
            NULL AS vendor,
            roi.file AS file,
            cbm.id AS MovementID,
            cbm.direction AS MovementDirection,
            cbm.status AS MovementStatus,
            cbm.memo AS MovementMemo,
            cbm.reference_no AS MovementReferenceNo,
            cbm.proof_file AS MovementProofFile,
            cbm.date AS MovementDate,
            cbm.amount AS MovementAmount
        FROM register_otherincome roi
        LEFT JOIN register_otherincomecategory AS roic ON roi.income_type_id = roic.id
        LEFT JOIN register_customuser AS created_by ON roi.created_by_id = created_by.id
        LEFT JOIN register_customuser AS edited_by ON roi.edited_by_id = edited_by.id
        LEFT JOIN register_cashbankmovement AS cbm
               ON cbm.church_id = roi.church_id
              AND cbm.source_type = 'OTHER_INCOME'
              AND cbm.source_id = roi.id
        WHERE roi.church_id = target_church_id
          AND DATE(roi.date) = target_date

        ORDER BY TransactionDate DESC, TransactionID DESC;
    END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_FundBalancesTotal`;
DELIMITER $$
CREATE PROCEDURE `Finance_FundBalancesTotal`(
    IN target_church_id BIGINT
)
BEGIN
    DECLARE unres_income            DECIMAL(18,2) DEFAULT 0.00;
    DECLARE res_income              DECIMAL(18,2) DEFAULT 0.00;

    DECLARE unres_exp               DECIMAL(18,2) DEFAULT 0.00;
    DECLARE res_exp                 DECIMAL(18,2) DEFAULT 0.00;

    DECLARE unres_bal               DECIMAL(18,2) DEFAULT 0.00;
    DECLARE res_bal                 DECIMAL(18,2) DEFAULT 0.00;

    DECLARE v_tithes                DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_offerings             DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_unres_don             DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_unres_other           DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_budget_return_unres   DECIMAL(18,2) DEFAULT 0.00;

    /* =========================
       1A) UNRESTRICTED INCOME PARTS
       Match Finance_UnrestrictedNet logic
       ========================= */

    SELECT COALESCE(SUM(t.amount), 0)
    INTO v_tithes
    FROM register_tithe t
    WHERE t.church_id = target_church_id;

    SELECT COALESCE(SUM(o.amount), 0)
    INTO v_offerings
    FROM register_offering o
    WHERE o.church_id = target_church_id;

    SELECT COALESCE(SUM(d.amount), 0)
    INTO v_unres_don
    FROM register_donations d
    JOIN register_donationcategory dc
      ON dc.id = d.donations_type_id
    WHERE d.church_id = target_church_id
      AND COALESCE(dc.is_restricted, 0) = 0;

    /*
      Unrestricted Other Income
      Exclude Budget Return income linked from register_releasedbudget
      because returns are computed directly below from register_releasedbudget.
    */
    SELECT COALESCE(SUM(oi.amount), 0)
    INTO v_unres_other
    FROM register_otherincome oi
    JOIN register_otherincomecategory oic
      ON oic.id = oi.income_type_id
    WHERE oi.church_id = target_church_id
      AND COALESCE(oic.is_restricted, 0) = 0
      AND NOT EXISTS (
          SELECT 1
          FROM register_releasedbudget rb
          WHERE rb.church_id = target_church_id
            AND rb.budget_return_income_id = oi.id
      );

    /*
      Budget Return restored to unrestricted
      Include both cash and bank returns.
    */
    SELECT COALESCE(SUM(rb.amount_returned), 0)
    INTO v_budget_return_unres
    FROM register_releasedbudget rb
    WHERE rb.church_id = target_church_id
      AND COALESCE(rb.is_liquidated, 0) = 1
      AND COALESCE(rb.amount_returned, 0) > 0;

    SET unres_income =
          v_tithes
        + v_offerings
        + v_unres_don
        + v_unres_other
        + v_budget_return_unres;

    /* =========================
       1B) RESTRICTED INCOME
       ========================= */
    SELECT
        COALESCE((
            SELECT SUM(d.amount)
            FROM register_donations d
            JOIN register_donationcategory dc
              ON dc.id = d.donations_type_id
            WHERE d.church_id = target_church_id
              AND COALESCE(dc.is_restricted, 0) = 1
        ), 0)
      + COALESCE((
            SELECT SUM(oi.amount)
            FROM register_otherincome oi
            JOIN register_otherincomecategory oic
              ON oic.id = oi.income_type_id
            WHERE oi.church_id = target_church_id
              AND COALESCE(oic.is_restricted, 0) = 1
        ), 0)
    INTO res_income;

    /* =========================
       2A) UNRESTRICTED EXPENSES
       Match Finance_UnrestrictedNet logic
       EXCLUDE:
       - rejected
       - system
       - transfers
       - Budget Return Deposit rows
       ========================= */
    SELECT COALESCE(SUM(e.amount), 0)
    INTO unres_exp
    FROM register_expense e
    LEFT JOIN register_expensecategory ec
      ON ec.id = e.category_id
    WHERE e.church_id = target_church_id
      AND COALESCE(e.status, '') <> 'Rejected'
      AND COALESCE(ec.is_system, 0) = 0
      AND COALESCE(ec.is_transfer, 0) = 0
      AND (ec.id IS NULL OR COALESCE(ec.is_restricted, 0) = 0)
      AND LOWER(TRIM(COALESCE(e.description, ''))) NOT LIKE 'budget return deposit%'
      AND NOT (
            LOWER(TRIM(COALESCE(ec.name, ''))) LIKE 'bank depos%'
         OR LOWER(TRIM(COALESCE(ec.name, ''))) LIKE 'bank withdr%'
         OR LOWER(TRIM(COALESCE(e.description, ''))) LIKE '%bank depos%'
         OR LOWER(TRIM(COALESCE(e.description, ''))) LIKE '%bank withdr%'
      );

    /* =========================
       2B) RESTRICTED EXPENSES
       EXCLUDE:
       - rejected
       - system
       - transfers
       - Budget Return Deposit rows
       ========================= */
    SELECT COALESCE(SUM(e.amount), 0)
    INTO res_exp
    FROM register_expense e
    JOIN register_expensecategory ec
      ON ec.id = e.category_id
    WHERE e.church_id = target_church_id
      AND COALESCE(e.status, '') <> 'Rejected'
      AND COALESCE(ec.is_system, 0) = 0
      AND COALESCE(ec.is_transfer, 0) = 0
      AND COALESCE(ec.is_restricted, 0) = 1
      AND LOWER(TRIM(COALESCE(e.description, ''))) NOT LIKE 'budget return deposit%'
      AND NOT (
            LOWER(TRIM(COALESCE(ec.name, ''))) LIKE 'bank depos%'
         OR LOWER(TRIM(COALESCE(ec.name, ''))) LIKE 'bank withdr%'
         OR LOWER(TRIM(COALESCE(e.description, ''))) LIKE '%bank depos%'
         OR LOWER(TRIM(COALESCE(e.description, ''))) LIKE '%bank withdr%'
      );

    /* =========================
       3) BALANCES
       ========================= */
    SET unres_bal = unres_income - unres_exp;
    SET res_bal   = res_income   - res_exp;

    SELECT
        unres_income AS UnrestrictedIncome,
        unres_exp    AS UnrestrictedExpenses,
        unres_bal    AS UnrestrictedBalance,

        res_income   AS RestrictedIncome,
        res_exp      AS RestrictedExpenses,
        res_bal      AS RestrictedBalance,

        (unres_bal + res_bal) AS TotalFundBalance;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_MonthlyDetailedReport`;
DELIMITER $$
CREATE PROCEDURE `Finance_MonthlyDetailedReport`(
    IN target_church_id INT
)
BEGIN
    SELECT
        DATE_FORMAT(txn_date, '%Y-%m') AS SortKey,
        DATE_FORMAT(txn_date, '%Y-%m') AS DisplayLabel,
        txn_type,
        category_name,
        SUM(amount) AS total_amount
    FROM (
        /* 1) Tithes */
        SELECT
            t.date AS txn_date,
            'Tithe' AS txn_type,
            'Tithes' AS category_name,
            t.amount AS amount
        FROM register_tithe t
        WHERE t.church_id = target_church_id

        UNION ALL

        /* 2) Offerings */
        SELECT
            o.date AS txn_date,
            'Offering' AS txn_type,
            'Loose Offering' AS category_name,
            o.amount AS amount
        FROM register_offering o
        WHERE o.church_id = target_church_id

        UNION ALL

        /* 3) Donations */
        SELECT
            rd.donations_date AS txn_date,
            CASE
                WHEN COALESCE(dc.is_restricted, 0) = 1 THEN 'Res_Donation'
                ELSE 'Unres_Donation'
            END AS txn_type,
            COALESCE(dc.name, 'Uncategorized Donation') AS category_name,
            rd.amount AS amount
        FROM register_donations rd
        LEFT JOIN register_donationcategory dc
               ON rd.donations_type_id = dc.id
        WHERE rd.church_id = target_church_id

        UNION ALL

        /* 4) Other Income */
        SELECT
            roi.date AS txn_date,

            CASE
                /* Budget Return belongs to General Income (Unrestricted) */
                WHEN LOWER(TRIM(COALESCE(oic.name,''))) LIKE 'budget return%'
                  OR LOWER(TRIM(COALESCE(roi.description,''))) LIKE 'budget return%'
                    THEN 'Unres_Other'

                WHEN COALESCE(oic.is_restricted, 0) = 1 THEN 'Res_Other'
                ELSE 'Unres_Other'
            END AS txn_type,

            CASE
                /* Budget Return - Bank */
                WHEN LOWER(TRIM(COALESCE(oic.name,''))) LIKE 'budget return - bank%'
                  OR LOWER(TRIM(COALESCE(roi.description,''))) LIKE 'budget return - bank%'
                  OR UPPER(COALESCE(cbm_oi.direction,'')) LIKE '%BANK%'
                THEN CONCAT(
                    'Bank:Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(roi.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return'
                    )
                )

                /* Budget Return - Cash */
                WHEN LOWER(TRIM(COALESCE(oic.name,''))) LIKE 'budget return - cash%'
                  OR LOWER(TRIM(COALESCE(roi.description,''))) LIKE 'budget return - cash%'
                  OR UPPER(COALESCE(cbm_oi.direction,'')) LIKE '%CASH%'
                THEN CONCAT(
                    'Cash:Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(roi.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return'
                    )
                )

                /* Other Budget Return */
                WHEN LOWER(TRIM(COALESCE(oic.name,''))) LIKE 'budget return%'
                  OR LOWER(TRIM(COALESCE(roi.description,''))) LIKE 'budget return%'
                THEN CONCAT(
                    'Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(roi.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return'
                    )
                )

                ELSE COALESCE(oic.name, 'Uncategorized Other Income')
            END AS category_name,

            roi.amount AS amount
        FROM register_otherincome roi
        LEFT JOIN register_otherincomecategory oic
               ON roi.income_type_id = oic.id
        LEFT JOIN (
            SELECT
                church_id,
                source_id,
                MAX(direction) AS direction
            FROM register_cashbankmovement
            WHERE source_type = 'OTHER_INCOME'
            GROUP BY church_id, source_id
        ) cbm_oi
               ON cbm_oi.church_id = roi.church_id
              AND cbm_oi.source_id = roi.id
        WHERE roi.church_id = target_church_id

        UNION ALL

        /* 5) Expenses */
        SELECT
            re.expense_date AS txn_date,

            CASE
                /* Transfers (hidden by Python) */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'bank deposit'
                    THEN 'Transfer_Deposit'
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) IN ('bank withdraw', 'bank withdrawal')
                    THEN 'Transfer_Withdraw'
                WHEN COALESCE(ec.is_transfer, 0) = 1
                    THEN 'Transfer_Deposit'
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank depos%'
                    THEN 'Transfer_Deposit'
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank withdr%'
                    THEN 'Transfer_Withdraw'
                WHEN LOWER(TRIM(COALESCE(re.description,''))) LIKE '%bank depos%'
                    THEN 'Transfer_Deposit'
                WHEN LOWER(TRIM(COALESCE(re.description,''))) LIKE '%bank withdr%'
                    THEN 'Transfer_Withdraw'

                /* Internal hidden budget release */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'budget release'
                    THEN 'System_BudgetRelease'

                /* Visible budget releases remain expenses */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) IN (
                    'budget release - bank',
                    'budget release - cash',
                    'budget release (unposted)'
                )
                    THEN 'Res_Expense'

                /* Budget Return belongs to General Income (Unrestricted) */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'budget return%'
                    THEN 'Unres_Other'

                /* Restricted synced expenses */
                WHEN COALESCE(ec.description,'') LIKE '%Synced Restricted Donation%'
                  OR COALESCE(ec.description,'') LIKE '%Auto-generated restricted fund%'
                  OR COALESCE(ec.description,'') LIKE '%Synced Restricted Income%'
                    THEN 'Res_Expense'

                ELSE 'Gen_Expense'
            END AS txn_type,

            CASE
                /* Budget Release - Bank */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'budget release - bank'
                THEN CONCAT(
                    'Bank:Budget Release: ',
                    COALESCE(
                        NULLIF(TRIM(re.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(re.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Release - Bank'
                    )
                )

                /* Budget Release - Cash */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'budget release - cash'
                THEN CONCAT(
                    'Cash:Budget Release: ',
                    COALESCE(
                        NULLIF(TRIM(re.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(re.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Release - Cash'
                    )
                )

                /* Budget Release - Unposted */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'budget release (unposted)'
                THEN CONCAT(
                    'Unposted:Budget Release: ',
                    COALESCE(
                        NULLIF(TRIM(re.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(re.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Release'
                    )
                )

                /* Budget Return - Bank */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'budget return - bank%'
                THEN CONCAT(
                    'Bank:Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(re.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(re.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return - Bank'
                    )
                )

                /* Budget Return - Cash */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'budget return - cash%'
                THEN CONCAT(
                    'Cash:Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(re.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(re.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return - Cash'
                    )
                )

                /* Other Budget Return */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'budget return%'
                THEN CONCAT(
                    CASE
                        WHEN UPPER(COALESCE(cbm.direction,'')) LIKE '%BANK%' THEN 'Bank:'
                        WHEN UPPER(COALESCE(cbm.direction,'')) LIKE '%CASH%' THEN 'Cash:'
                        ELSE ''
                    END,
                    'Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(re.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(re.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return'
                    )
                )

                /* Normal expenses: prefix only when source is known */
                ELSE CONCAT(
                    CASE
                        WHEN UPPER(COALESCE(cbm.direction,'')) LIKE '%BANK%' THEN 'Bank:'
                        WHEN UPPER(COALESCE(cbm.direction,'')) LIKE '%CASH%' THEN 'Cash:'
                        ELSE ''
                    END,
                    COALESCE(ec.name, 'Uncategorized')
                )
            END AS category_name,

            re.amount AS amount
        FROM register_expense re
        LEFT JOIN register_expensecategory ec
               ON re.category_id = ec.id
        LEFT JOIN (
            SELECT
                church_id,
                source_id,
                MAX(direction) AS direction
            FROM register_cashbankmovement
            WHERE source_type = 'EXPENSE'
            GROUP BY church_id, source_id
        ) cbm
               ON cbm.church_id = re.church_id
              AND cbm.source_id = re.id
        WHERE re.church_id = target_church_id
          AND COALESCE(re.status, '') <> 'Rejected'

        UNION ALL

        /* 6) ReleasedBudget fallback (no matching expense yet) */
        SELECT
            rb.date_released AS txn_date,
            'Res_Expense' AS txn_type,
            CONCAT(
                CASE
                    WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) IN ('bank', 'bank balance') THEN 'Bank:'
                    WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) IN ('cash', 'physical cash', 'ministry wallet') THEN 'Cash:'
                    ELSE ''
                END,
                'Budget Release: ',
                COALESCE(
                    NULLIF(TRIM(rb.remarks), ''),
                    CASE
                        WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) IN ('bank', 'bank balance')
                            THEN 'Budget Release - Bank'
                        WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) IN ('cash', 'physical cash', 'ministry wallet')
                            THEN 'Budget Release - Cash'
                        ELSE 'Budget Release'
                    END
                )
            ) AS category_name,
            rb.amount AS amount
        FROM register_releasedbudget rb
        WHERE rb.church_id = target_church_id
          AND NOT EXISTS (
                SELECT 1
                FROM register_expense e2
                LEFT JOIN register_expensecategory ec2
                       ON ec2.id = e2.category_id
                WHERE e2.church_id = rb.church_id
                  AND COALESCE(e2.status, '') <> 'Rejected'
                  AND (
                        LOWER(TRIM(COALESCE(e2.description, '')))
                            LIKE CONCAT('%release id ', rb.id, '%')
                        OR (
                            LOWER(TRIM(COALESCE(ec2.name, ''))) IN (
                                'budget release',
                                'budget release - cash',
                                'budget release - bank'
                            )
                            AND e2.amount = rb.amount
                        )
                  )
          )

    ) AS temp_table
    GROUP BY
        SortKey,
        DisplayLabel,
        txn_type,
        category_name
    ORDER BY
        SortKey DESC,
        txn_type ASC,
        category_name ASC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_MonthlySummary_WithNet`;
DELIMITER $$
CREATE PROCEDURE `Finance_MonthlySummary_WithNet`(
    IN `target_church_id` INT
)
BEGIN
    SELECT
        -- 1. Group by Month (YYYY-MM)
        MonthYear,

        -- 2. Category Type (Income or Expense)
        txn_type,

        -- 3. Specific Category Name
        category_name,

        -- 4. Total Amount (Expenses will be negative)
        SUM(amount) as total_amount

    FROM (
        -- === INCOME SECTIONS (Positive Amounts) ===
        SELECT DATE_FORMAT(date, '%Y-%m') as MonthYear, 'Income' as txn_type, 'Tithes' as category_name, amount FROM register_tithe WHERE church_id = target_church_id
        UNION ALL
        SELECT DATE_FORMAT(date, '%Y-%m'), 'Income', 'Offering', amount FROM register_offering WHERE church_id = target_church_id
        UNION ALL
        SELECT DATE_FORMAT(rd.donations_date, '%Y-%m'), 'Income', dc.name, rd.amount FROM register_donations rd JOIN register_donationcategory dc ON rd.donations_type_id = dc.id WHERE rd.church_id = target_church_id
        UNION ALL
        SELECT DATE_FORMAT(roi.date, '%Y-%m'), 'Income', oic.name, roi.amount FROM register_otherincome roi JOIN register_otherincomecategory oic ON roi.income_type_id = oic.id WHERE roi.church_id = target_church_id

        UNION ALL

        -- === EXPENSE SECTION (Negative Amounts) ===
        SELECT
            DATE_FORMAT(re.expense_date, '%Y-%m'),
            'Expense',
            COALESCE(ec.name, 'Uncategorized Expense'),
            -re.amount  -- MAKE NEGATIVE TO DEDUCT
        FROM register_expense re
        LEFT JOIN register_expensecategory ec ON re.category_id = ec.id
        WHERE re.church_id = target_church_id

    ) AS AllTxns

    GROUP BY MonthYear, txn_type, category_name
    ORDER BY MonthYear DESC, txn_type DESC; -- Income first, then Expense
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_MonthlyTransactions`;
DELIMITER $$
CREATE PROCEDURE `Finance_MonthlyTransactions`(
        IN `month_start_date` DATE,
        IN `target_church_id` BIGINT
    )
BEGIN
        DECLARE month_end_date DATE;
        SET month_end_date = LAST_DAY(month_start_date);

        /* 1) Expenses + Transfers */
        SELECT
            CASE
                WHEN (
                    COALESCE(cat.is_transfer,0)=1
                    OR LOWER(TRIM(COALESCE(cat.name,''))) IN (
                        'bank deposit',
                        'bank withdraw',
                        'bank withdrawal'
                    )
                    OR LOWER(TRIM(COALESCE(cat.name,''))) LIKE 'bank depos%'
                    OR LOWER(TRIM(COALESCE(cat.name,''))) LIKE 'bank withdr%'
                    OR LOWER(TRIM(COALESCE(re.description,''))) LIKE '%bank depos%'
                    OR LOWER(TRIM(COALESCE(re.description,''))) LIKE '%bank withdr%'
                )
                THEN 'Transfer'
                ELSE 'Expense'
            END AS TransactionType,
            re.id AS TransactionID,
            re.expense_date AS TransactionDate,
            COALESCE(cat.name, 'Uncategorized') AS Typeof,
            re.description AS TypeOthers,
            re.amount AS amount,
            created_by.id AS UserID,
            created_by.first_name AS CreatedByName,
            edited_by.id AS EditedByID,
            edited_by.first_name AS EditedByName,
            NULL AS donor,
            re.vendor AS vendor,
            re.file AS file,
            cbm.id AS MovementID,
            cbm.direction AS MovementDirection,
            cbm.status AS MovementStatus,
            cbm.memo AS MovementMemo,
            cbm.reference_no AS MovementReferenceNo,
            cbm.proof_file AS MovementProofFile,
            cbm.date AS MovementDate,
            cbm.amount AS MovementAmount
        FROM register_expense re
        LEFT JOIN register_expensecategory AS cat ON re.category_id = cat.id
        LEFT JOIN register_customuser AS created_by ON re.created_by_id = created_by.id
        LEFT JOIN register_customuser AS edited_by ON re.edited_by_id = edited_by.id
        LEFT JOIN register_cashbankmovement AS cbm
               ON cbm.church_id = re.church_id
              AND cbm.source_type = 'EXPENSE'
              AND cbm.source_id = re.id
        WHERE re.church_id = target_church_id
          AND re.expense_date BETWEEN month_start_date AND month_end_date
          AND COALESCE(re.status,'') <> 'Rejected'

        UNION ALL

        /* 2) Offerings */
        SELECT
            'Offering' AS TransactionType,
            ro.id AS TransactionID,
            ro.date AS TransactionDate,
            'Offering' AS Typeof,
            COALESCE(ro.description, '') AS TypeOthers,
            ro.amount AS amount,
            created_by.id AS UserID,
            created_by.first_name AS CreatedByName,
            edited_by.id AS EditedByID,
            edited_by.first_name AS EditedByName,
            NULL AS donor,
            NULL AS vendor,
            ro.proof_document AS file,
            cbm.id AS MovementID,
            cbm.direction AS MovementDirection,
            cbm.status AS MovementStatus,
            cbm.memo AS MovementMemo,
            cbm.reference_no AS MovementReferenceNo,
            cbm.proof_file AS MovementProofFile,
            cbm.date AS MovementDate,
            cbm.amount AS MovementAmount
        FROM register_offering ro
        LEFT JOIN register_customuser AS created_by ON ro.created_by_id = created_by.id
        LEFT JOIN register_customuser AS edited_by ON ro.edited_by_id = edited_by.id
        LEFT JOIN register_cashbankmovement AS cbm
               ON cbm.church_id = ro.church_id
              AND cbm.source_type = 'OFFERING'
              AND cbm.source_id = ro.id
        WHERE ro.church_id = target_church_id
          AND ro.date BETWEEN month_start_date AND month_end_date

        UNION ALL

        /* 3) Donations */
        SELECT
            'Donations' AS TransactionType,
            rd.id AS TransactionID,
            rd.donations_date AS TransactionDate,
            COALESCE(cat.name, 'Uncategorized') AS Typeof,
            rd.other_donations_type AS TypeOthers,
            rd.amount AS amount,
            created_by.id AS UserID,
            created_by.first_name AS CreatedByName,
            edited_by.id AS EditedByID,
            edited_by.first_name AS EditedByName,
            rd.donor AS donor,
            NULL AS vendor,
            rd.receipt_image AS file,
            cbm.id AS MovementID,
            cbm.direction AS MovementDirection,
            cbm.status AS MovementStatus,
            cbm.memo AS MovementMemo,
            cbm.reference_no AS MovementReferenceNo,
            cbm.proof_file AS MovementProofFile,
            cbm.date AS MovementDate,
            cbm.amount AS MovementAmount
        FROM register_donations rd
        LEFT JOIN register_donationcategory AS cat ON rd.donations_type_id = cat.id
        LEFT JOIN register_customuser AS created_by ON rd.created_by_id = created_by.id
        LEFT JOIN register_customuser AS edited_by ON rd.edited_by_id = edited_by.id
        LEFT JOIN register_cashbankmovement AS cbm
               ON cbm.church_id = rd.church_id
              AND cbm.source_type = 'DONATION'
              AND cbm.source_id = rd.id
        WHERE rd.church_id = target_church_id
          AND rd.donations_date BETWEEN month_start_date AND month_end_date

        UNION ALL

        /* 4) Tithes */
        SELECT
            'Tithe' AS TransactionType,
            rt.id AS TransactionID,
            rt.date AS TransactionDate,
            'Tithe' AS Typeof,
            COALESCE(rt.description, '') AS TypeOthers,
            rt.amount AS amount,
            created_by.id AS UserID,
            created_by.first_name AS CreatedByName,
            edited_by.id AS EditedByID,
            edited_by.first_name AS EditedByName,
            NULL AS donor,
            NULL AS vendor,
            rt.file AS file,
            cbm.id AS MovementID,
            cbm.direction AS MovementDirection,
            cbm.status AS MovementStatus,
            cbm.memo AS MovementMemo,
            cbm.reference_no AS MovementReferenceNo,
            cbm.proof_file AS MovementProofFile,
            cbm.date AS MovementDate,
            cbm.amount AS MovementAmount
        FROM register_tithe rt
        LEFT JOIN register_customuser AS created_by ON rt.created_by_id = created_by.id
        LEFT JOIN register_customuser AS edited_by ON rt.edited_by_id = edited_by.id
        LEFT JOIN register_cashbankmovement AS cbm
               ON cbm.church_id = rt.church_id
              AND cbm.source_type = 'TITHE'
              AND cbm.source_id = rt.id
        WHERE rt.church_id = target_church_id
          AND rt.date BETWEEN month_start_date AND month_end_date

        UNION ALL

        /* 5) Other Income */
        SELECT
            'OtherIncome' AS TransactionType,
            roi.id AS TransactionID,
            roi.date AS TransactionDate,
            COALESCE(roic.name, 'Uncategorized') AS Typeof,
            roi.description AS TypeOthers,
            roi.amount AS amount,
            created_by.id AS UserID,
            created_by.first_name AS CreatedByName,
            edited_by.id AS EditedByID,
            edited_by.first_name AS EditedByName,
            NULL AS donor,
            NULL AS vendor,
            roi.file AS file,
            cbm.id AS MovementID,
            cbm.direction AS MovementDirection,
            cbm.status AS MovementStatus,
            cbm.memo AS MovementMemo,
            cbm.reference_no AS MovementReferenceNo,
            cbm.proof_file AS MovementProofFile,
            cbm.date AS MovementDate,
            cbm.amount AS MovementAmount
        FROM register_otherincome roi
        LEFT JOIN register_otherincomecategory AS roic ON roi.income_type_id = roic.id
        LEFT JOIN register_customuser AS created_by ON roi.created_by_id = created_by.id
        LEFT JOIN register_customuser AS edited_by ON roi.edited_by_id = edited_by.id
        LEFT JOIN register_cashbankmovement AS cbm
               ON cbm.church_id = roi.church_id
              AND cbm.source_type = 'OTHER_INCOME'
              AND cbm.source_id = roi.id
        WHERE roi.church_id = target_church_id
          AND roi.date BETWEEN month_start_date AND month_end_date

        ORDER BY TransactionDate DESC, TransactionID DESC;
    END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_PeriodBalancesSummary`;
DELIMITER $$
CREATE PROCEDURE `Finance_PeriodBalancesSummary`(
    IN target_church_id BIGINT,
    IN report_type VARCHAR(20)   -- 'weekly','monthly','yearly'
)
BEGIN
    -- Normalize input
    SET report_type = LOWER(TRIM(report_type));

    SELECT
        -- 1) SortKey (string; must match detailed report keys)
        CAST(
            CASE
                WHEN report_type = 'weekly'  THEN YEARWEEK(AllTxn.txn_date, 1)
                WHEN report_type = 'monthly' THEN DATE_FORMAT(AllTxn.txn_date, '%Y-%m')
                ELSE DATE_FORMAT(AllTxn.txn_date, '%Y')
            END
        AS CHAR) AS SortKey,

        -- 2) DisplayLabel (must match detailed report)
        CASE
            WHEN report_type = 'weekly'  THEN DATE_FORMAT(AllTxn.txn_date, '%x-%v')
            WHEN report_type = 'monthly' THEN DATE_FORMAT(AllTxn.txn_date, '%M %Y')
            ELSE DATE_FORMAT(AllTxn.txn_date, '%Y')
        END AS DisplayLabel,

        -- 3) UNRESTRICTED FUNDS
        SUM(CASE WHEN AllTxn.is_restricted = 0 AND AllTxn.type = 'income'  THEN AllTxn.amount ELSE 0 END) AS UnrestrictedIncome,
        SUM(CASE WHEN AllTxn.is_restricted = 0 AND AllTxn.type = 'expense' THEN AllTxn.amount ELSE 0 END) AS UnrestrictedExpenses,
        (
            SUM(CASE WHEN AllTxn.is_restricted = 0 AND AllTxn.type = 'income'  THEN AllTxn.amount ELSE 0 END) -
            SUM(CASE WHEN AllTxn.is_restricted = 0 AND AllTxn.type = 'expense' THEN AllTxn.amount ELSE 0 END)
        ) AS UnrestrictedBalance,

        -- 4) RESTRICTED FUNDS
        SUM(CASE WHEN AllTxn.is_restricted = 1 AND AllTxn.type = 'income'  THEN AllTxn.amount ELSE 0 END) AS RestrictedIncome,
        SUM(CASE WHEN AllTxn.is_restricted = 1 AND AllTxn.type = 'expense' THEN AllTxn.amount ELSE 0 END) AS RestrictedExpenses,
        (
            SUM(CASE WHEN AllTxn.is_restricted = 1 AND AllTxn.type = 'income'  THEN AllTxn.amount ELSE 0 END) -
            SUM(CASE WHEN AllTxn.is_restricted = 1 AND AllTxn.type = 'expense' THEN AllTxn.amount ELSE 0 END)
        ) AS RestrictedTotalBalance,

        -- 5) OVERALL (verification)
        SUM(CASE WHEN AllTxn.type = 'income'  THEN AllTxn.amount ELSE 0 END) AS OverallIncome,
        SUM(CASE WHEN AllTxn.type = 'expense' THEN AllTxn.amount ELSE 0 END) AS OverallExpenses,
        (
            SUM(CASE WHEN AllTxn.type = 'income'  THEN AllTxn.amount ELSE 0 END) -
            SUM(CASE WHEN AllTxn.type = 'expense' THEN AllTxn.amount ELSE 0 END)
        ) AS OverallBalance

    FROM (
        -- A) TITHES (always unrestricted income)
        SELECT t.date AS txn_date, t.amount AS amount, 'income' AS type, 0 AS is_restricted
        FROM register_tithe t
        WHERE t.church_id = target_church_id

        UNION ALL

        -- B) OFFERINGS (always unrestricted income)
        SELECT o.date AS txn_date, o.amount AS amount, 'income' AS type, 0 AS is_restricted
        FROM register_offering o
        WHERE o.church_id = target_church_id

        UNION ALL

        -- C) DONATIONS (restricted flag from donation category)
        SELECT rd.donations_date AS txn_date, rd.amount AS amount, 'income' AS type, dc.is_restricted AS is_restricted
        FROM register_donations rd
        JOIN register_donationcategory dc ON rd.donations_type_id = dc.id
        WHERE rd.church_id = target_church_id

        UNION ALL

        -- D) OTHER INCOME (restricted flag from other-income category)
        SELECT roi.date AS txn_date, roi.amount AS amount, 'income' AS type, oic.is_restricted AS is_restricted
        FROM register_otherincome roi
        JOIN register_otherincomecategory oic ON roi.income_type_id = oic.id
        WHERE roi.church_id = target_church_id

        UNION ALL

        -- E) OPERATING EXPENSES ONLY (exclude transfers + system/internal + bank deposit/withdraw)
        SELECT
            re.expense_date AS txn_date,
            re.amount AS amount,
            'expense' AS type,
            CASE
                WHEN COALESCE(ec.description,'') LIKE '%Synced Restricted Donation%'
                  OR COALESCE(ec.description,'') LIKE '%Auto-generated restricted fund%'
                  OR COALESCE(ec.description,'') LIKE '%Synced Restricted Income%'
                THEN 1
                ELSE 0
            END AS is_restricted
        FROM register_expense re
        LEFT JOIN register_expensecategory ec ON re.category_id = ec.id
        WHERE re.church_id = target_church_id
          AND COALESCE(ec.is_transfer, 0) = 0
          AND COALESCE(ec.is_system, 0) = 0
          AND LOWER(TRIM(COALESCE(ec.name, ''))) NOT IN ('bank withdraw', 'bank deposit')

    ) AS AllTxn

    GROUP BY SortKey, DisplayLabel
    ORDER BY SortKey DESC;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_PeriodFundSummary`;
DELIMITER $$
CREATE PROCEDURE `Finance_PeriodFundSummary`(
    IN `target_church_id` INT,
    IN `report_type` VARCHAR(20) -- 'weekly', 'monthly', 'yearly'
)
BEGIN
    SELECT
        /* 1) PERIOD GROUPING */
        CASE
            WHEN report_type = 'weekly'  THEN DATE_FORMAT(txn_date, '%Y-%u')
            WHEN report_type = 'monthly' THEN DATE_FORMAT(txn_date, '%Y-%m')
            WHEN report_type = 'yearly'  THEN DATE_FORMAT(txn_date, '%Y')
            ELSE DATE_FORMAT(txn_date, '%Y-%m')
        END AS SortKey,

        CASE
            WHEN report_type = 'weekly'  THEN CONCAT('Week ', DATE_FORMAT(txn_date, '%u %Y'))
            WHEN report_type = 'monthly' THEN DATE_FORMAT(txn_date, '%M %Y')
            WHEN report_type = 'yearly'  THEN DATE_FORMAT(txn_date, '%Y')
            ELSE DATE_FORMAT(txn_date, '%M %Y')
        END AS DisplayLabel,

        /* 2) FUND (CATEGORY) */
        CASE
            WHEN is_restricted = 1 THEN category_name
            ELSE 'General Operating Fund'
        END AS Final_Category,

        /* 3) FUND TYPE */
        CASE
            WHEN is_restricted = 1 THEN 'Restricted'
            ELSE 'Unrestricted'
        END AS Fund_Type,

        /* 4) INCOME / EXPENSES / BALANCE */
        SUM(income_amount)  AS Income,
        SUM(expense_amount) AS Expenses,
        (SUM(income_amount) - SUM(expense_amount)) AS Balance

    FROM (
        /* ==================================================
           A) UNRESTRICTED INCOME (Tithes & Offering)
           ================================================== */
        SELECT t.date AS txn_date, 'Tithes' AS category_name, 0 AS is_restricted,
               t.amount AS income_amount, 0 AS expense_amount
        FROM register_tithe t
        WHERE t.church_id = target_church_id

        UNION ALL

        SELECT o.date AS txn_date, 'Offering' AS category_name, 0 AS is_restricted,
               o.amount AS income_amount, 0 AS expense_amount
        FROM register_offering o
        WHERE o.church_id = target_church_id

        UNION ALL

        /* ==================================================
           B) DONATIONS (Restricted vs Unrestricted)
           ================================================== */
        SELECT rd.donations_date AS txn_date, dc.name AS category_name, dc.is_restricted AS is_restricted,
               rd.amount AS income_amount, 0 AS expense_amount
        FROM register_donations rd
        JOIN register_donationcategory dc ON rd.donations_type_id = dc.id
        WHERE rd.church_id = target_church_id

        UNION ALL

        /* ==================================================
           C) OTHER INCOME (Restricted vs Unrestricted)
           ================================================== */
        SELECT roi.date AS txn_date, oic.name AS category_name, oic.is_restricted AS is_restricted,
               roi.amount AS income_amount, 0 AS expense_amount
        FROM register_otherincome roi
        JOIN register_otherincomecategory oic ON roi.income_type_id = oic.id
        WHERE roi.church_id = target_church_id

        UNION ALL

        /* ==================================================
           D) EXPENSES (classified restricted/unrestricted)
           ================================================== */
        SELECT
            re.expense_date AS txn_date,
            COALESCE(ec.name, 'Uncategorized') AS category_name,

            /* RESTRICTED RULE:
               - If ec.description is NOT empty => restricted
               - ELSE fallback to name-matching restricted categories (for old data)
            */
            CASE
                WHEN ec.id IS NULL THEN 0
                WHEN COALESCE(NULLIF(TRIM(ec.description), ''), '') <> '' THEN 1
                WHEN EXISTS (
                    SELECT 1
                    FROM register_donationcategory dc2
                    WHERE dc2.church_id = target_church_id
                      AND dc2.is_restricted = 1
                      AND TRIM(dc2.name) = TRIM(ec.name)
                ) THEN 1
                WHEN EXISTS (
                    SELECT 1
                    FROM register_otherincomecategory oic2
                    WHERE oic2.church_id = target_church_id
                      AND oic2.is_restricted = 1
                      AND TRIM(oic2.name) = TRIM(ec.name)
                ) THEN 1
                ELSE 0
            END AS is_restricted,

            0 AS income_amount,
            re.amount AS expense_amount
        FROM register_expense re
        LEFT JOIN register_expensecategory ec ON re.category_id = ec.id
        WHERE re.church_id = target_church_id

    ) AS RawData

    GROUP BY SortKey, DisplayLabel, Final_Category, Fund_Type
    ORDER BY SortKey DESC, Fund_Type DESC, Final_Category ASC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_PeriodNetBalance`;
DELIMITER $$
CREATE PROCEDURE `Finance_PeriodNetBalance`(
    IN `target_church_id` INT,
    IN `report_type` VARCHAR(20) -- 'weekly', 'monthly', 'yearly'
)
BEGIN
    SELECT
        CASE
            WHEN report_type = 'weekly'  THEN DATE_FORMAT(txn_date, '%Y-%u')
            WHEN report_type = 'monthly' THEN DATE_FORMAT(txn_date, '%Y-%m')
            WHEN report_type = 'yearly'  THEN DATE_FORMAT(txn_date, '%Y')
            ELSE DATE_FORMAT(txn_date, '%Y-%m')
        END AS SortKey,

        CASE
            WHEN report_type = 'weekly'  THEN CONCAT('Week ', DATE_FORMAT(txn_date, '%u %Y'))
            WHEN report_type = 'monthly' THEN DATE_FORMAT(txn_date, '%M %Y')
            WHEN report_type = 'yearly'  THEN DATE_FORMAT(txn_date, '%Y')
            ELSE DATE_FORMAT(txn_date, '%M %Y')
        END AS DisplayLabel,

        CASE
            WHEN is_restricted = 1 THEN category_name
            ELSE 'General Operating Fund'
        END AS Final_Category,

        CASE
            WHEN is_restricted = 1 THEN 'Restricted'
            ELSE 'Unrestricted'
        END AS Fund_Type,

        SUM(amount) AS Net_Balance

    FROM (
        -- A) Tithes + Offering are always Unrestricted (General Operating Fund)
        SELECT t.date AS txn_date, 'Tithes' AS category_name, 0 AS is_restricted, t.amount AS amount
        FROM register_tithe t
        WHERE t.church_id = target_church_id

        UNION ALL

        SELECT o.date AS txn_date, 'Offering' AS category_name, 0 AS is_restricted, o.amount AS amount
        FROM register_offering o
        WHERE o.church_id = target_church_id

        UNION ALL

        -- B) Donations: use dc.is_restricted
        SELECT rd.donations_date AS txn_date, dc.name AS category_name, dc.is_restricted AS is_restricted, rd.amount AS amount
        FROM register_donations rd
        JOIN register_donationcategory dc ON rd.donations_type_id = dc.id
        WHERE rd.church_id = target_church_id

        UNION ALL

        -- C) Other income: use oic.is_restricted
        SELECT roi.date AS txn_date, oic.name AS category_name, oic.is_restricted AS is_restricted, roi.amount AS amount
        FROM register_otherincome roi
        JOIN register_otherincomecategory oic ON roi.income_type_id = oic.id
        WHERE roi.church_id = target_church_id

        UNION ALL

        -- D) Expenses: RESTRICTED if ExpenseCategory.description has text
        SELECT
            re.expense_date AS txn_date,
            COALESCE(ec.name, 'Uncategorized') AS category_name,
            CASE
                WHEN ec.id IS NULL THEN 0
                WHEN COALESCE(NULLIF(TRIM(ec.description), ''), '') <> '' THEN 1
                ELSE 0
            END AS is_restricted,
            -re.amount AS amount
        FROM register_expense re
        LEFT JOIN register_expensecategory ec ON re.category_id = ec.id
        WHERE re.church_id = target_church_id

    ) AS RawData

    GROUP BY SortKey, DisplayLabel, Final_Category, Fund_Type
    ORDER BY SortKey DESC, Fund_Type DESC, Final_Category ASC;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_RestrictedBalanceNow`;
DELIMITER $$
CREATE PROCEDURE `Finance_RestrictedBalanceNow`(
    IN target_church_id BIGINT
)
BEGIN
    DECLARE v_restricted_donations DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_restricted_other_income DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_restricted_expenses DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_restricted_balance DECIMAL(18,2) DEFAULT 0.00;

    /* Restricted Donations */
    SELECT COALESCE(SUM(d.amount), 0)
    INTO v_restricted_donations
    FROM register_donations d
    JOIN register_donationcategory dc
      ON dc.id = CAST(d.donations_type_id AS UNSIGNED)
    WHERE d.church_id = target_church_id
      AND COALESCE(dc.is_restricted, 0) = 1;

    /* Restricted Other Income */
    SELECT COALESCE(SUM(oi.amount), 0)
    INTO v_restricted_other_income
    FROM register_otherincome oi
    JOIN register_otherincomecategory oic
      ON oic.id = oi.income_type_id
    WHERE oi.church_id = target_church_id
      AND COALESCE(oic.is_restricted, 0) = 1;

    /* Restricted Expenses */
    SELECT COALESCE(SUM(e.amount), 0)
    INTO v_restricted_expenses
    FROM register_expense e
    JOIN register_expensecategory ec
      ON ec.id = e.category_id
    WHERE e.church_id = target_church_id
      AND COALESCE(e.status, '') NOT IN ('Rejected', 'Declined')
      AND COALESCE(ec.is_system, 0) = 0
      AND COALESCE(ec.is_transfer, 0) = 0
      AND COALESCE(ec.is_restricted, 0) = 1
      AND LOWER(TRIM(COALESCE(e.description, ''))) NOT LIKE 'budget return deposit%';

    SET v_restricted_balance =
          v_restricted_donations
        + v_restricted_other_income
        - v_restricted_expenses;

    IF v_restricted_balance < 0 THEN
        SET v_restricted_balance = 0.00;
    END IF;

    SELECT
        v_restricted_donations    AS TotalRestrictedDonations,
        v_restricted_other_income AS TotalRestrictedOtherIncome,
        v_restricted_expenses     AS TotalRestrictedExpenses,
        v_restricted_balance      AS RestrictedBalanceOutstanding;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_RestrictedDonationsNetBalance`;
DELIMITER $$
CREATE PROCEDURE `Finance_RestrictedDonationsNetBalance`(
    IN `target_church_id` INT
)
BEGIN
    SELECT
        AllCats.CategoryName,

        -- ==========================================================
        -- 1. TOTAL COLLECTED (Donations + Other Income)
        -- ==========================================================
        (
            -- A. Donation Sum (Matches Name)
            COALESCE(
                (
                    SELECT SUM(rd.amount)
                    FROM register_donations rd
                    JOIN register_donationcategory dc ON rd.donations_type_id = dc.id
                    WHERE dc.name = AllCats.CategoryName
                    AND rd.church_id = target_church_id
                ),
            0)
            +
            -- B. Other Income Sum (Matches Name)
            COALESCE(
                (
                    SELECT SUM(roi.amount)
                    FROM register_otherincome roi
                    JOIN register_otherincomecategory oic ON roi.income_type_id = oic.id
                    WHERE oic.name = AllCats.CategoryName
                    AND roi.church_id = target_church_id
                ),
            0)
        ) AS TotalCollected,

        -- ==========================================================
        -- 2. TOTAL SPENT (Expenses)
        -- ==========================================================
        COALESCE(
            (
                SELECT SUM(re.amount)
                FROM register_expense re
                JOIN register_expensecategory ec ON re.category_id = ec.id
                WHERE ec.name = AllCats.CategoryName
                AND re.church_id = target_church_id
            ),
        0) AS TotalSpent,

        -- ==========================================================
        -- 3. NET BALANCE (Collected - Spent)
        -- ==========================================================
        (
            (
                COALESCE(
                    (SELECT SUM(rd.amount) FROM register_donations rd JOIN register_donationcategory dc ON rd.donations_type_id = dc.id WHERE dc.name = AllCats.CategoryName AND rd.church_id = target_church_id), 0
                )
                +
                COALESCE(
                    (SELECT SUM(roi.amount) FROM register_otherincome roi JOIN register_otherincomecategory oic ON roi.income_type_id = oic.id WHERE oic.name = AllCats.CategoryName AND roi.church_id = target_church_id), 0
                )
            )
            -
            COALESCE(
                (SELECT SUM(re.amount) FROM register_expense re JOIN register_expensecategory ec ON re.category_id = ec.id WHERE ec.name = AllCats.CategoryName AND re.church_id = target_church_id), 0
            )
        ) AS CurrentBalance

    FROM
        (
            -- UNION: Combines names from both tables, removing duplicates
            SELECT name AS CategoryName
            FROM register_donationcategory
            WHERE is_restricted = 1 AND church_id = target_church_id

            UNION

            SELECT name AS CategoryName
            FROM register_otherincomecategory
            WHERE is_restricted = 1 AND church_id = target_church_id
        ) AS AllCats

    ORDER BY
        CurrentBalance DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_RestrictedDonationsSum`;
DELIMITER $$
CREATE PROCEDURE `Finance_RestrictedDonationsSum`(
    IN `target_church_id` INT
)
BEGIN
    SELECT
        cat.name AS CategoryName,
        SUM(rd.amount) AS TotalAmount
    FROM
        register_donations rd
    INNER JOIN
        register_donationcategory cat ON rd.donations_type_id = cat.id
    WHERE
        rd.church_id = target_church_id
        AND cat.is_restricted = 1  -- This ensures ONLY restricted funds are shown
    GROUP BY
        cat.id, cat.name
    ORDER BY
        TotalAmount DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_RestrictedFundsSum`;
DELIMITER $$
CREATE PROCEDURE `Finance_RestrictedFundsSum`(
    IN `target_church_id` INT
)
BEGIN
    SELECT
        -- SUM up the "CurrentBalance" calculated for each category below
        COALESCE(SUM(SubQuery.CurrentBalance), 0) AS TotalRestrictedFunds
    FROM (
        SELECT
            -- The Exact Net Balance Logic from your other procedure
            (
                -- 1. TOTAL INCOME (Donations + Other Income)
                (
                    COALESCE(
                        (SELECT SUM(rd.amount)
                         FROM register_donations rd
                         JOIN register_donationcategory dc ON rd.donations_type_id = dc.id
                         WHERE dc.name = AllCats.CategoryName AND rd.church_id = target_church_id),
                    0)
                    +
                    COALESCE(
                        (SELECT SUM(roi.amount)
                         FROM register_otherincome roi
                         JOIN register_otherincomecategory oic ON roi.income_type_id = oic.id
                         WHERE oic.name = AllCats.CategoryName AND roi.church_id = target_church_id),
                    0)
                )
                -
                -- 2. TOTAL EXPENSES
                COALESCE(
                    (SELECT SUM(re.amount)
                     FROM register_expense re
                     JOIN register_expensecategory ec ON re.category_id = ec.id
                     WHERE ec.name = AllCats.CategoryName AND re.church_id = target_church_id),
                0)
            ) AS CurrentBalance

        FROM
            (
                -- UNION: Get distinct list of Restricted Category Names
                SELECT name AS CategoryName
                FROM register_donationcategory
                WHERE is_restricted = 1 AND church_id = target_church_id

                UNION

                SELECT name AS CategoryName
                FROM register_otherincomecategory
                WHERE is_restricted = 1 AND church_id = target_church_id
            ) AS AllCats

    ) AS SubQuery;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_RestrictedFunds_ByPeriod`;
DELIMITER $$
CREATE PROCEDURE `Finance_RestrictedFunds_ByPeriod`(
    IN `target_church_id` INT,
    IN `report_type` VARCHAR(20) -- 'weekly', 'monthly', 'yearly'
)
BEGIN
    SET report_type = LOWER(TRIM(report_type));

    SELECT
        p.SortKey,
        p.CategoryName,

        -- ✅ Whole totals
        COALESCE(ct.TotalCollected, 0) AS TotalCollected,
        COALESCE(st.TotalSpent, 0)     AS TotalSpent,

        -- ✅ Correct calculation: whole collected - whole spent
        (COALESCE(ct.TotalCollected, 0) - COALESCE(st.TotalSpent, 0)) AS NetBalance

    FROM
    (
        -- This subquery only decides which periods exist per category
        -- (so your report can still show by weekly/monthly/yearly)
        SELECT
            CAST(
                CASE
                    WHEN report_type = 'weekly'  THEN YEARWEEK(TxnDate, 1)
                    WHEN report_type = 'monthly' THEN DATE_FORMAT(TxnDate, '%Y-%m')
                    ELSE DATE_FORMAT(TxnDate, '%Y')
                END AS CHAR
            ) AS SortKey,
            CategoryName
        FROM (
            -- income sources
            SELECT rd.donations_date AS TxnDate, dc.name AS CategoryName
            FROM register_donations rd
            JOIN register_donationcategory dc ON rd.donations_type_id = dc.id
            WHERE rd.church_id = target_church_id AND dc.is_restricted = 1

            UNION ALL

            SELECT roi.date AS TxnDate, oic.name AS CategoryName
            FROM register_otherincome roi
            JOIN register_otherincomecategory oic ON roi.income_type_id = oic.id
            WHERE roi.church_id = target_church_id AND oic.is_restricted = 1

            UNION ALL

            -- expense rows that match restricted names
            SELECT re.expense_date AS TxnDate, ec.name AS CategoryName
            FROM register_expense re
            JOIN register_expensecategory ec ON re.category_id = ec.id
            WHERE re.church_id = target_church_id
              AND ec.name IN (
                  SELECT name FROM register_donationcategory
                  WHERE is_restricted = 1 AND church_id = target_church_id
                  UNION
                  SELECT name FROM register_otherincomecategory
                  WHERE is_restricted = 1 AND church_id = target_church_id
              )
        ) x
        GROUP BY SortKey, CategoryName
    ) AS p

    -- ✅ Whole collected per category (all time)
    LEFT JOIN
    (
        SELECT
            CategoryName,
            SUM(IncomeAmount) AS TotalCollected
        FROM (
            SELECT dc.name AS CategoryName, rd.amount AS IncomeAmount
            FROM register_donations rd
            JOIN register_donationcategory dc ON rd.donations_type_id = dc.id
            WHERE rd.church_id = target_church_id AND dc.is_restricted = 1

            UNION ALL

            SELECT oic.name AS CategoryName, roi.amount AS IncomeAmount
            FROM register_otherincome roi
            JOIN register_otherincomecategory oic ON roi.income_type_id = oic.id
            WHERE roi.church_id = target_church_id AND oic.is_restricted = 1
        ) income_all
        GROUP BY CategoryName
    ) AS ct
      ON ct.CategoryName = p.CategoryName

    -- ✅ Whole spent per category (all time)
    LEFT JOIN
    (
        SELECT
            ec.name AS CategoryName,
            SUM(re.amount) AS TotalSpent
        FROM register_expense re
        JOIN register_expensecategory ec ON re.category_id = ec.id
        WHERE re.church_id = target_church_id
          AND ec.name IN (
              SELECT name FROM register_donationcategory
              WHERE is_restricted = 1 AND church_id = target_church_id
              UNION
              SELECT name FROM register_otherincomecategory
              WHERE is_restricted = 1 AND church_id = target_church_id
          )
        GROUP BY ec.name
    ) AS st
      ON st.CategoryName = p.CategoryName

    ORDER BY p.SortKey DESC, p.CategoryName ASC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_RestrictedNetBalance`;
DELIMITER $$
CREATE PROCEDURE `Finance_RestrictedNetBalance`(
    IN target_church_id BIGINT
)
BEGIN

    /* =========================
       Restricted Donation Funds
       ========================= */
    SELECT
        dc.name AS CategoryName,
        'DONATION' AS RestrictedSource,
        dc.id AS RestrictedCategoryId,

        COALESCE(inc.total_in, 0) AS TotalCollected,
        COALESCE(sp.total_out, 0) AS TotalSpent,
        (COALESCE(inc.total_in, 0) - COALESCE(sp.total_out, 0)) AS CurrentBalance

    FROM register_donationcategory dc

    LEFT JOIN (
        SELECT rd.donations_type_id AS fund_id, rd.church_id, SUM(rd.amount) AS total_in
        FROM register_donations rd
        WHERE rd.church_id = target_church_id
        GROUP BY rd.donations_type_id, rd.church_id
    ) inc
      ON inc.fund_id = dc.id AND inc.church_id = target_church_id

    LEFT JOIN (
        SELECT ec.restricted_category_id AS fund_id, e.church_id, SUM(e.amount) AS total_out
        FROM register_expense e
        JOIN register_expensecategory ec ON ec.id = e.category_id
        WHERE e.church_id = target_church_id
          AND COALESCE(e.status,'') <> 'Rejected'
          AND COALESCE(ec.is_system,0)=0
          AND COALESCE(ec.is_transfer,0)=0
          AND COALESCE(ec.is_restricted,0)=1
          AND ec.restricted_source='DONATION'
        GROUP BY ec.restricted_category_id, e.church_id
    ) sp
      ON sp.fund_id = dc.id AND sp.church_id = target_church_id

    WHERE dc.church_id = target_church_id
      AND COALESCE(dc.is_restricted,0)=1

    UNION ALL

    /* =============================
       Restricted Other Income Funds
       ============================= */
    SELECT
        oic.name AS CategoryName,
        'OTHER_INCOME' AS RestrictedSource,
        oic.id AS RestrictedCategoryId,

        COALESCE(inc2.total_in, 0) AS TotalCollected,
        COALESCE(sp2.total_out, 0) AS TotalSpent,
        (COALESCE(inc2.total_in, 0) - COALESCE(sp2.total_out, 0)) AS CurrentBalance

    FROM register_otherincomecategory oic

    LEFT JOIN (
        SELECT roi.income_type_id AS fund_id, roi.church_id, SUM(roi.amount) AS total_in
        FROM register_otherincome roi
        WHERE roi.church_id = target_church_id
        GROUP BY roi.income_type_id, roi.church_id
    ) inc2
      ON inc2.fund_id = oic.id AND inc2.church_id = target_church_id

    LEFT JOIN (
        SELECT ec.restricted_category_id AS fund_id, e.church_id, SUM(e.amount) AS total_out
        FROM register_expense e
        JOIN register_expensecategory ec ON ec.id = e.category_id
        WHERE e.church_id = target_church_id
          AND COALESCE(e.status,'') <> 'Rejected'
          AND COALESCE(ec.is_system,0)=0
          AND COALESCE(ec.is_transfer,0)=0
          AND COALESCE(ec.is_restricted,0)=1
          AND ec.restricted_source='OTHER_INCOME'
        GROUP BY ec.restricted_category_id, e.church_id
    ) sp2
      ON sp2.fund_id = oic.id AND sp2.church_id = target_church_id

    WHERE oic.church_id = target_church_id
      AND COALESCE(oic.is_restricted,0)=1

    ORDER BY CurrentBalance DESC;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_RestrictedOtherIncomeSum`;
DELIMITER $$
CREATE PROCEDURE `Finance_RestrictedOtherIncomeSum`(
    IN `target_church_id` INT
)
BEGIN
    SELECT
        roic.name AS CategoryName,
        SUM(roi.amount) AS TotalAmount
    FROM
        register_otherincome roi
    INNER JOIN
        register_otherincomecategory roic ON roi.income_type_id = roic.id
    WHERE
        roi.church_id = target_church_id
        AND roic.is_restricted = 1
    GROUP BY
        roic.name
    ORDER BY
        TotalAmount DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_RestrictedSums`;
DELIMITER $$
CREATE PROCEDURE `Finance_RestrictedSums`(
    IN `target_church_id` INT
)
BEGIN
    SELECT
        -- 1. Total Restricted Donations
        (SELECT COALESCE(SUM(rd.amount), 0)
         FROM register_donations rd
         JOIN register_donationcategory cat ON rd.donations_type_id = cat.id
         WHERE rd.church_id = target_church_id
         AND cat.is_restricted = 1)
         AS TotalRestrictedDonations,

        -- 2. Total Restricted Other Income
        (SELECT COALESCE(SUM(roi.amount), 0)
         FROM register_otherincome roi
         JOIN register_otherincomecategory cat ON roi.income_type_id = cat.id
         WHERE roi.church_id = target_church_id
         AND cat.is_restricted = 1)
         AS TotalRestrictedOtherIncome,

        -- 3. Grand Total Restricted (Sum of the two above)
        (
            (SELECT COALESCE(SUM(rd.amount), 0)
             FROM register_donations rd
             JOIN register_donationcategory cat ON rd.donations_type_id = cat.id
             WHERE rd.church_id = target_church_id
             AND cat.is_restricted = 1)
            +
            (SELECT COALESCE(SUM(roi.amount), 0)
             FROM register_otherincome roi
             JOIN register_otherincomecategory cat ON roi.income_type_id = cat.id
             WHERE roi.church_id = target_church_id
             AND cat.is_restricted = 1)
        )
        AS GrandTotalRestricted;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_SortedbyDate`;
DELIMITER $$
CREATE PROCEDURE `Finance_SortedbyDate`(
    IN `target_church_id` BIGINT
)
BEGIN
    /* 1) Expenses + Transfers (from register_expense) */
    SELECT
        CASE
            WHEN (
                COALESCE(cat.is_transfer,0)=1
                OR LOWER(TRIM(COALESCE(cat.name,''))) IN (
                    'bank deposit',
                    'bank withdraw',
                    'bank withdrawal'
                )
                OR LOWER(TRIM(COALESCE(cat.name,''))) LIKE 'bank depos%'
                OR LOWER(TRIM(COALESCE(cat.name,''))) LIKE 'bank withdr%'
                OR LOWER(TRIM(COALESCE(re.description,''))) LIKE '%bank depos%'
                OR LOWER(TRIM(COALESCE(re.description,''))) LIKE '%bank withdr%'
            )
            THEN 'Transfer'
            ELSE 'Expense'
        END AS TransactionType,
        re.id AS TransactionID,
        re.expense_date AS TransactionDate,
        COALESCE(cat.name, 'Uncategorized') AS Typeof,
        re.description AS TypeOthers,
        re.amount AS amount,
        created_by.id AS UserID,
        TRIM(CONCAT_WS(' ',
            NULLIF(created_by.first_name, ''),
            NULLIF(created_by.middle_name, ''),
            NULLIF(created_by.last_name, '')
        )) AS CreatedByName,
        edited_by.id AS EditedByID,
        TRIM(CONCAT_WS(' ',
            NULLIF(edited_by.first_name, ''),
            NULLIF(edited_by.middle_name, ''),
            NULLIF(edited_by.last_name, '')
        )) AS EditedByName,
        NULL AS donor,
        re.vendor AS vendor,
        re.file AS file,
        cbm.id AS MovementID,
        cbm.direction AS MovementDirection,
        cbm.status AS MovementStatus,
        cbm.memo AS MovementMemo,
        cbm.reference_no AS MovementReferenceNo,
        cbm.proof_file AS MovementProofFile,
        cbm.date AS MovementDate,
        cbm.amount AS MovementAmount
    FROM register_expense re
    LEFT JOIN register_expensecategory AS cat ON re.category_id = cat.id
    LEFT JOIN register_customuser AS created_by ON re.created_by_id = created_by.id
    LEFT JOIN register_customuser AS edited_by ON re.edited_by_id = edited_by.id
    LEFT JOIN register_cashbankmovement AS cbm
           ON cbm.church_id = re.church_id
          AND cbm.source_type = 'EXPENSE'
          AND cbm.source_id = re.id
    WHERE re.church_id = target_church_id
      AND COALESCE(re.status,'') <> 'Rejected'

    UNION ALL

    /* 2) Offerings */
    SELECT
        'Offering' AS TransactionType,
        ro.id AS TransactionID,
        ro.date AS TransactionDate,
        'Offering' AS Typeof,
        COALESCE(ro.description, '') AS TypeOthers,
        ro.amount AS amount,
        created_by.id AS UserID,
        TRIM(CONCAT_WS(' ',
            NULLIF(created_by.first_name, ''),
            NULLIF(created_by.middle_name, ''),
            NULLIF(created_by.last_name, '')
        )) AS CreatedByName,
        edited_by.id AS EditedByID,
        TRIM(CONCAT_WS(' ',
            NULLIF(edited_by.first_name, ''),
            NULLIF(edited_by.middle_name, ''),
            NULLIF(edited_by.last_name, '')
        )) AS EditedByName,
        NULL AS donor,
        NULL AS vendor,
        ro.proof_document AS file,
        cbm.id AS MovementID,
        cbm.direction AS MovementDirection,
        cbm.status AS MovementStatus,
        cbm.memo AS MovementMemo,
        cbm.reference_no AS MovementReferenceNo,
        cbm.proof_file AS MovementProofFile,
        cbm.date AS MovementDate,
        cbm.amount AS MovementAmount
    FROM register_offering ro
    LEFT JOIN register_customuser AS created_by ON ro.created_by_id = created_by.id
    LEFT JOIN register_customuser AS edited_by ON ro.edited_by_id = edited_by.id
    LEFT JOIN register_cashbankmovement AS cbm
           ON cbm.church_id = ro.church_id
          AND cbm.source_type = 'OFFERING'
          AND cbm.source_id = ro.id
    WHERE ro.church_id = target_church_id

    UNION ALL

    /* 3) Donations */
    SELECT
        'Donations' AS TransactionType,
        rd.id AS TransactionID,
        rd.donations_date AS TransactionDate,
        COALESCE(cat.name, 'Uncategorized') AS Typeof,
        rd.other_donations_type AS TypeOthers,
        rd.amount AS amount,
        created_by.id AS UserID,
        TRIM(CONCAT_WS(' ',
            NULLIF(created_by.first_name, ''),
            NULLIF(created_by.middle_name, ''),
            NULLIF(created_by.last_name, '')
        )) AS CreatedByName,
        edited_by.id AS EditedByID,
        TRIM(CONCAT_WS(' ',
            NULLIF(edited_by.first_name, ''),
            NULLIF(edited_by.middle_name, ''),
            NULLIF(edited_by.last_name, '')
        )) AS EditedByName,
        rd.donor AS donor,
        NULL AS vendor,
        rd.receipt_image AS file,
        cbm.id AS MovementID,
        cbm.direction AS MovementDirection,
        cbm.status AS MovementStatus,
        cbm.memo AS MovementMemo,
        cbm.reference_no AS MovementReferenceNo,
        cbm.proof_file AS MovementProofFile,
        cbm.date AS MovementDate,
        cbm.amount AS MovementAmount
    FROM register_donations rd
    LEFT JOIN register_donationcategory AS cat ON rd.donations_type_id = cat.id
    LEFT JOIN register_customuser AS created_by ON rd.created_by_id = created_by.id
    LEFT JOIN register_customuser AS edited_by ON rd.edited_by_id = edited_by.id
    LEFT JOIN register_cashbankmovement AS cbm
           ON cbm.church_id = rd.church_id
          AND cbm.source_type = 'DONATION'
          AND cbm.source_id = rd.id
    WHERE rd.church_id = target_church_id

    UNION ALL

    /* 4) Tithes */
    SELECT
        'Tithe' AS TransactionType,
        rt.id AS TransactionID,
        rt.date AS TransactionDate,
        'Tithe' AS Typeof,
        COALESCE(rt.description, '') AS TypeOthers,
        rt.amount AS amount,
        created_by.id AS UserID,
        TRIM(CONCAT_WS(' ',
            NULLIF(created_by.first_name, ''),
            NULLIF(created_by.middle_name, ''),
            NULLIF(created_by.last_name, '')
        )) AS CreatedByName,
        edited_by.id AS EditedByID,
        TRIM(CONCAT_WS(' ',
            NULLIF(edited_by.first_name, ''),
            NULLIF(edited_by.middle_name, ''),
            NULLIF(edited_by.last_name, '')
        )) AS EditedByName,
        NULL AS donor,
        NULL AS vendor,
        rt.file AS file,
        cbm.id AS MovementID,
        cbm.direction AS MovementDirection,
        cbm.status AS MovementStatus,
        cbm.memo AS MovementMemo,
        cbm.reference_no AS MovementReferenceNo,
        cbm.proof_file AS MovementProofFile,
        cbm.date AS MovementDate,
        cbm.amount AS MovementAmount
    FROM register_tithe rt
    LEFT JOIN register_customuser AS created_by ON rt.created_by_id = created_by.id
    LEFT JOIN register_customuser AS edited_by ON rt.edited_by_id = edited_by.id
    LEFT JOIN register_cashbankmovement AS cbm
           ON cbm.church_id = rt.church_id
          AND cbm.source_type = 'TITHE'
          AND cbm.source_id = rt.id
    WHERE rt.church_id = target_church_id

    UNION ALL

    /* 5) Other Income */
    SELECT
        'OtherIncome' AS TransactionType,
        roi.id AS TransactionID,
        roi.date AS TransactionDate,
        COALESCE(roic.name, 'Uncategorized') AS Typeof,
        roi.description AS TypeOthers,
        roi.amount AS amount,
        created_by.id AS UserID,
        TRIM(CONCAT_WS(' ',
            NULLIF(created_by.first_name, ''),
            NULLIF(created_by.middle_name, ''),
            NULLIF(created_by.last_name, '')
        )) AS CreatedByName,
        edited_by.id AS EditedByID,
        TRIM(CONCAT_WS(' ',
            NULLIF(edited_by.first_name, ''),
            NULLIF(edited_by.middle_name, ''),
            NULLIF(edited_by.last_name, '')
        )) AS EditedByName,
        NULL AS donor,
        NULL AS vendor,
        roi.file AS file,
        cbm.id AS MovementID,
        cbm.direction AS MovementDirection,
        cbm.status AS MovementStatus,
        cbm.memo AS MovementMemo,
        cbm.reference_no AS MovementReferenceNo,
        cbm.proof_file AS MovementProofFile,
        cbm.date AS MovementDate,
        cbm.amount AS MovementAmount
    FROM register_otherincome roi
    LEFT JOIN register_otherincomecategory AS roic ON roi.income_type_id = roic.id
    LEFT JOIN register_customuser AS created_by ON roi.created_by_id = created_by.id
    LEFT JOIN register_customuser AS edited_by ON roi.edited_by_id = edited_by.id
    LEFT JOIN register_cashbankmovement AS cbm
           ON cbm.church_id = roi.church_id
          AND cbm.source_type = 'OTHER_INCOME'
          AND cbm.source_id = roi.id
    WHERE roi.church_id = target_church_id

    UNION ALL

    /* 6) ReleasedBudget fallback rows */
    SELECT
        'ReleasedBudget' AS TransactionType,
        rb.id AS TransactionID,
        rb.date_released AS TransactionDate,
        CASE
            WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) = 'bank' THEN 'Budget Release - Bank'
            ELSE 'Budget Release - Cash'
        END AS Typeof,
        COALESCE(rb.remarks, '') AS TypeOthers,
        rb.amount AS amount,
        released_by.id AS UserID,
        TRIM(CONCAT_WS(' ',
            NULLIF(released_by.first_name, ''),
            NULLIF(released_by.middle_name, ''),
            NULLIF(released_by.last_name, '')
        )) AS CreatedByName,
        NULL AS EditedByID,
        NULL AS EditedByName,
        NULL AS donor,
        NULL AS vendor,
        NULL AS file,
        NULL AS MovementID,
        NULL AS MovementDirection,
        NULL AS MovementStatus,
        NULL AS MovementMemo,
        NULL AS MovementReferenceNo,
        NULL AS MovementProofFile,
        NULL AS MovementDate,
        NULL AS MovementAmount
    FROM register_releasedbudget rb
    LEFT JOIN register_customuser AS released_by ON rb.released_by_id = released_by.id
    WHERE rb.church_id = target_church_id
      AND NOT EXISTS (
            SELECT 1
            FROM register_expense e
            LEFT JOIN register_expensecategory ec ON ec.id = e.category_id
            WHERE e.church_id = rb.church_id
              AND COALESCE(e.status,'') <> 'Rejected'
              AND (
                    LOWER(TRIM(COALESCE(e.description,''))) LIKE CONCAT('%release id ', rb.id, '%')
                    OR (
                        LOWER(TRIM(COALESCE(ec.name,''))) IN (
                            'budget release',
                            'budget release - cash',
                            'budget release - bank'
                        )
                        AND e.amount = rb.amount
                    )
                )
      )

    ORDER BY TransactionDate DESC, TransactionID DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_SortedbyDate_Filtered`;
DELIMITER $$
CREATE PROCEDURE `Finance_SortedbyDate_Filtered`(IN `filter_date` DATE)
BEGIN
    SELECT 'Expense' AS TransactionType,
           id AS TransactionID,
           expense_date AS TransactionDate,
           expense_type AS Typeof,
           other_expense_type AS TypeOthers,
           amount
    FROM register_expense
    WHERE expense_date = filter_date

    UNION ALL

    SELECT 'Offering' AS TransactionType,
           id AS TransactionID,
           date AS TransactionDate,
           '' AS Typeof,
           '' AS TypeOthers,
           amount
    FROM register_offering
    WHERE date = filter_date

    UNION ALL

    SELECT 'Donations' AS TransactionType,
           id AS TransactionID,
           donations_date AS TransactionDate,
           donations_type AS Typeof,
           other_donations_type AS TypeOthers,
           amount
    FROM register_donations
    WHERE donations_date = filter_date

    UNION ALL

    SELECT 'Tithe' AS TransactionType,
           id AS TransactionID,
           date AS TransactionDate,
           '' AS Typeof,
           '' AS TypeOthers,
           amount
    FROM register_tithe
    WHERE date = filter_date

    ORDER BY TransactionDate DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_UnrestrictedIncomeByYear`;
DELIMITER $$
CREATE PROCEDURE `Finance_UnrestrictedIncomeByYear`(
    IN target_church_id BIGINT
)
BEGIN
    SELECT
        y.`year` AS `Year`,

        COALESCE(t.TotalTithes, 0) AS TotalTithes,
        COALESCE(o.TotalOfferings, 0) AS TotalOfferings,
        COALESCE(d.TotalUnrestrictedDonations, 0) AS TotalUnrestrictedDonations,
        COALESCE(oi.TotalUnrestrictedOtherIncome, 0) AS TotalUnrestrictedOtherIncome,

        /* Keep this in column #6 for Python compatibility (r[5]) */
        (
            COALESCE(t.TotalTithes, 0)
          + COALESCE(o.TotalOfferings, 0)
          + COALESCE(d.TotalUnrestrictedDonations, 0)
          + COALESCE(oi.TotalUnrestrictedOtherIncome, 0)
          + COALESCE(br.TotalBudgetReturnsToUnrestricted, 0)
        ) AS GrandTotalUnrestricted,

        COALESCE(br.TotalBudgetReturnsToUnrestricted, 0) AS TotalBudgetReturnsToUnrestricted,
        COALESCE(ue.TotalUnrestrictedExpenses, 0) AS TotalUnrestrictedExpenses,

        (
            (
                COALESCE(t.TotalTithes, 0)
              + COALESCE(o.TotalOfferings, 0)
              + COALESCE(d.TotalUnrestrictedDonations, 0)
              + COALESCE(oi.TotalUnrestrictedOtherIncome, 0)
              + COALESCE(br.TotalBudgetReturnsToUnrestricted, 0)
            )
            - COALESCE(ue.TotalUnrestrictedExpenses, 0)
        ) AS NetGrandTotalUnrestricted,

        COALESCE(re.TotalRealExpensesAll, 0) AS TotalRealExpensesAll,
        COALESCE(rx.TotalRestrictedExpenses, 0) AS TotalRestrictedExpenses

    FROM
    (
        /* Year set across all relevant unrestricted-income and expense sources */
        SELECT DISTINCT YEAR(dt) AS `year`
        FROM (
            /* Tithes */
            SELECT tt.`date` AS dt
            FROM register_tithe tt
            WHERE tt.church_id = target_church_id
              AND tt.`date` IS NOT NULL

            UNION ALL

            /* Offerings */
            SELECT oo.`date` AS dt
            FROM register_offering oo
            WHERE oo.church_id = target_church_id
              AND oo.`date` IS NOT NULL

            UNION ALL

            /* Unrestricted Donations only */
            SELECT dd.`donations_date` AS dt
            FROM register_donations dd
            JOIN register_donationcategory dc
              ON dc.id = CAST(dd.donations_type_id AS UNSIGNED)
            WHERE dd.church_id = target_church_id
              AND dd.`donations_date` IS NOT NULL
              AND COALESCE(dc.is_restricted, 0) = 0

            UNION ALL

            /* Unrestricted Other Income only, excluding budget-return-linked rows */
            SELECT oi.`date` AS dt
            FROM register_otherincome oi
            JOIN register_otherincomecategory oic
              ON oic.id = oi.income_type_id
            WHERE oi.church_id = target_church_id
              AND oi.`date` IS NOT NULL
              AND COALESCE(oic.is_restricted, 0) = 0
              AND NOT EXISTS (
                    SELECT 1
                    FROM register_releasedbudget rb
                    WHERE rb.church_id = target_church_id
                      AND rb.budget_return_income_id = oi.id
              )

            UNION ALL

            /* Budget returns restored to unrestricted */
            SELECT rb.`liquidated_date` AS dt
            FROM register_releasedbudget rb
            WHERE rb.church_id = target_church_id
              AND COALESCE(rb.is_liquidated, 0) = 1
              AND COALESCE(rb.amount_returned, 0) > 0
              AND rb.`liquidated_date` IS NOT NULL

            UNION ALL

            /* Valid real expenses */
            SELECT e.`expense_date` AS dt
            FROM register_expense e
            LEFT JOIN register_expensecategory ec
              ON ec.id = e.category_id
            WHERE e.church_id = target_church_id
              AND e.`expense_date` IS NOT NULL
              AND COALESCE(e.status, '') <> 'Rejected'
              AND COALESCE(ec.is_system, 0) = 0
              AND COALESCE(ec.is_transfer, 0) = 0
              AND LOWER(TRIM(COALESCE(ec.name, ''))) NOT IN ('bank withdraw', 'bank deposit')
              AND LOWER(TRIM(COALESCE(e.description, ''))) NOT LIKE 'budget return deposit%'
        ) x
    ) y

    /* Tithes by year */
    LEFT JOIN (
        SELECT
            YEAR(tt.`date`) AS `year`,
            COALESCE(SUM(tt.amount), 0) AS TotalTithes
        FROM register_tithe tt
        WHERE tt.church_id = target_church_id
          AND tt.`date` IS NOT NULL
        GROUP BY YEAR(tt.`date`)
    ) t ON t.`year` = y.`year`

    /* Offerings by year */
    LEFT JOIN (
        SELECT
            YEAR(oo.`date`) AS `year`,
            COALESCE(SUM(oo.amount), 0) AS TotalOfferings
        FROM register_offering oo
        WHERE oo.church_id = target_church_id
          AND oo.`date` IS NOT NULL
        GROUP BY YEAR(oo.`date`)
    ) o ON o.`year` = y.`year`

    /* Unrestricted Donations by year */
    LEFT JOIN (
        SELECT
            YEAR(dd.`donations_date`) AS `year`,
            COALESCE(SUM(dd.amount), 0) AS TotalUnrestrictedDonations
        FROM register_donations dd
        JOIN register_donationcategory dc
          ON dc.id = CAST(dd.donations_type_id AS UNSIGNED)
        WHERE dd.church_id = target_church_id
          AND dd.`donations_date` IS NOT NULL
          AND COALESCE(dc.is_restricted, 0) = 0
        GROUP BY YEAR(dd.`donations_date`)
    ) d ON d.`year` = y.`year`

    /* Unrestricted Other Income by year */
    LEFT JOIN (
        SELECT
            YEAR(oi.`date`) AS `year`,
            COALESCE(SUM(oi.amount), 0) AS TotalUnrestrictedOtherIncome
        FROM register_otherincome oi
        JOIN register_otherincomecategory oic
          ON oic.id = oi.income_type_id
        WHERE oi.church_id = target_church_id
          AND oi.`date` IS NOT NULL
          AND COALESCE(oic.is_restricted, 0) = 0
          AND NOT EXISTS (
                SELECT 1
                FROM register_releasedbudget rb
                WHERE rb.church_id = target_church_id
                  AND rb.budget_return_income_id = oi.id
          )
        GROUP BY YEAR(oi.`date`)
    ) oi ON oi.`year` = y.`year`

    /* Budget returns restored to unrestricted by year */
    LEFT JOIN (
        SELECT
            YEAR(rb.`liquidated_date`) AS `year`,
            COALESCE(SUM(rb.amount_returned), 0) AS TotalBudgetReturnsToUnrestricted
        FROM register_releasedbudget rb
        WHERE rb.church_id = target_church_id
          AND COALESCE(rb.is_liquidated, 0) = 1
          AND COALESCE(rb.amount_returned, 0) > 0
          AND rb.`liquidated_date` IS NOT NULL
        GROUP BY YEAR(rb.`liquidated_date`)
    ) br ON br.`year` = y.`year`

    /* Total unrestricted expenses by year */
    LEFT JOIN (
        SELECT
            YEAR(e.`expense_date`) AS `year`,
            COALESCE(SUM(e.amount), 0) AS TotalUnrestrictedExpenses
        FROM register_expense e
        LEFT JOIN register_expensecategory ec
          ON ec.id = e.category_id
        WHERE e.church_id = target_church_id
          AND e.`expense_date` IS NOT NULL
          AND COALESCE(e.status, '') <> 'Rejected'
          AND COALESCE(ec.is_system, 0) = 0
          AND COALESCE(ec.is_transfer, 0) = 0
          AND (ec.id IS NULL OR COALESCE(ec.is_restricted, 0) = 0)
          AND LOWER(TRIM(COALESCE(ec.name, ''))) NOT IN ('bank withdraw', 'bank deposit')
          AND LOWER(TRIM(COALESCE(e.description, ''))) NOT LIKE 'budget return deposit%'
        GROUP BY YEAR(e.`expense_date`)
    ) ue ON ue.`year` = y.`year`

    /* Total real expenses all by year */
    LEFT JOIN (
        SELECT
            YEAR(e.`expense_date`) AS `year`,
            COALESCE(SUM(e.amount), 0) AS TotalRealExpensesAll
        FROM register_expense e
        LEFT JOIN register_expensecategory ec
          ON ec.id = e.category_id
        WHERE e.church_id = target_church_id
          AND e.`expense_date` IS NOT NULL
          AND COALESCE(e.status, '') <> 'Rejected'
          AND COALESCE(ec.is_system, 0) = 0
          AND COALESCE(ec.is_transfer, 0) = 0
          AND LOWER(TRIM(COALESCE(ec.name, ''))) NOT IN ('bank withdraw', 'bank deposit')
          AND LOWER(TRIM(COALESCE(e.description, ''))) NOT LIKE 'budget return deposit%'
        GROUP BY YEAR(e.`expense_date`)
    ) re ON re.`year` = y.`year`

    /* Total restricted expenses by year */
    LEFT JOIN (
        SELECT
            YEAR(e.`expense_date`) AS `year`,
            COALESCE(SUM(e.amount), 0) AS TotalRestrictedExpenses
        FROM register_expense e
        JOIN register_expensecategory ec
          ON ec.id = e.category_id
        WHERE e.church_id = target_church_id
          AND e.`expense_date` IS NOT NULL
          AND COALESCE(e.status, '') <> 'Rejected'
          AND COALESCE(ec.is_system, 0) = 0
          AND COALESCE(ec.is_transfer, 0) = 0
          AND COALESCE(ec.is_restricted, 0) = 1
          AND LOWER(TRIM(COALESCE(e.description, ''))) NOT LIKE 'budget return deposit%'
        GROUP BY YEAR(e.`expense_date`)
    ) rx ON rx.`year` = y.`year`

    ORDER BY y.`year` DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_UnrestrictedNet`;
DELIMITER $$
CREATE PROCEDURE `Finance_UnrestrictedNet`(
    IN target_church_id BIGINT
)
BEGIN
    DECLARE v_tithes               DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_offerings            DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_unres_don            DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_unres_other          DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_budget_return_unres  DECIMAL(18,2) DEFAULT 0.00;

    DECLARE v_unres_income DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_unres_exp    DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_unres_net    DECIMAL(18,2) DEFAULT 0.00;

    DECLARE v_real_exp_all DECIMAL(18,2) DEFAULT 0.00;
    DECLARE v_res_exp      DECIMAL(18,2) DEFAULT 0.00;

    /* 1A) Tithes */
    SELECT COALESCE(SUM(t.amount), 0)
    INTO v_tithes
    FROM register_tithe t
    WHERE t.church_id = target_church_id;

    /* 1B) Offerings */
    SELECT COALESCE(SUM(o.amount), 0)
    INTO v_offerings
    FROM register_offering o
    WHERE o.church_id = target_church_id;

    /* 1C) Unrestricted Donations */
    SELECT COALESCE(SUM(d.amount), 0)
    INTO v_unres_don
    FROM register_donations d
    JOIN register_donationcategory dc
      ON dc.id = d.donations_type_id
    WHERE d.church_id = target_church_id
      AND COALESCE(dc.is_restricted, 0) = 0;

    /*
      1D) Unrestricted Other Income
      Exclude budget-return OtherIncome linked from ReleasedBudget
      to avoid double counting.
    */
    SELECT COALESCE(SUM(oi.amount), 0)
    INTO v_unres_other
    FROM register_otherincome oi
    JOIN register_otherincomecategory oic
      ON oic.id = oi.income_type_id
    WHERE oi.church_id = target_church_id
      AND COALESCE(oic.is_restricted, 0) = 0
      AND NOT EXISTS (
          SELECT 1
          FROM register_releasedbudget rb
          WHERE rb.church_id = target_church_id
            AND rb.budget_return_income_id = oi.id
      );

    /*
      1E) Budget Return restored to unrestricted
      Include BOTH return_to='cash' and return_to='bank'
      because both restore unrestricted funds.
    */
    SELECT COALESCE(SUM(rb.amount_returned), 0)
    INTO v_budget_return_unres
    FROM register_releasedbudget rb
    WHERE rb.church_id = target_church_id
      AND COALESCE(rb.is_liquidated, 0) = 1
      AND COALESCE(rb.amount_returned, 0) > 0;

    SET v_unres_income =
          v_tithes
        + v_offerings
        + v_unres_don
        + v_unres_other
        + v_budget_return_unres;

    /*
      2A) TotalRealExpensesAll
      Exclude:
        - rejected
        - system
        - transfer
        - Budget Return Deposit bank-transfer rows
        - Bank Deposit / Bank Withdraw / Bank Withdrawal
    */
    SELECT COALESCE(SUM(e.amount), 0)
    INTO v_real_exp_all
    FROM register_expense e
    LEFT JOIN register_expensecategory ec
      ON ec.id = e.category_id
    WHERE e.church_id = target_church_id
      AND COALESCE(e.status, '') <> 'Rejected'
      AND COALESCE(ec.is_system, 0) = 0
      AND COALESCE(ec.is_transfer, 0) = 0
      AND LOWER(TRIM(COALESCE(e.description, ''))) NOT LIKE 'budget return deposit%'
      AND LOWER(TRIM(COALESCE(ec.name, ''))) NOT IN ('bank deposit', 'bank withdraw', 'bank withdrawal');

    /*
      2B) TotalUnrestrictedExpenses
      Exclude:
        - Budget Return Deposit bank-transfer rows
        - Bank Deposit / Bank Withdraw / Bank Withdrawal
    */
    SELECT COALESCE(SUM(e.amount), 0)
    INTO v_unres_exp
    FROM register_expense e
    LEFT JOIN register_expensecategory ec
      ON ec.id = e.category_id
    WHERE e.church_id = target_church_id
      AND COALESCE(e.status, '') <> 'Rejected'
      AND COALESCE(ec.is_system, 0) = 0
      AND COALESCE(ec.is_transfer, 0) = 0
      AND (ec.id IS NULL OR COALESCE(ec.is_restricted, 0) = 0)
      AND LOWER(TRIM(COALESCE(e.description, ''))) NOT LIKE 'budget return deposit%'
      AND LOWER(TRIM(COALESCE(ec.name, ''))) NOT IN ('bank deposit', 'bank withdraw', 'bank withdrawal');

    /*
      2C) TotalRestrictedExpenses
      Exclude:
        - Budget Return Deposit bank-transfer rows
        - Bank Deposit / Bank Withdraw / Bank Withdrawal
    */
    SELECT COALESCE(SUM(e.amount), 0)
    INTO v_res_exp
    FROM register_expense e
    JOIN register_expensecategory ec
      ON ec.id = e.category_id
    WHERE e.church_id = target_church_id
      AND COALESCE(e.status, '') <> 'Rejected'
      AND COALESCE(ec.is_system, 0) = 0
      AND COALESCE(ec.is_transfer, 0) = 0
      AND COALESCE(ec.is_restricted, 0) = 1
      AND LOWER(TRIM(COALESCE(e.description, ''))) NOT LIKE 'budget return deposit%'
      AND LOWER(TRIM(COALESCE(ec.name, ''))) NOT IN ('bank deposit', 'bank withdraw', 'bank withdrawal');

    SET v_unres_net = v_unres_income - v_unres_exp;

    SELECT
        v_tithes               AS TotalTithes,
        v_offerings            AS TotalOfferings,
        v_unres_don            AS TotalUnrestrictedDonations,
        v_unres_other          AS TotalUnrestrictedOtherIncome,
        v_budget_return_unres  AS TotalBudgetReturnsToUnrestricted,
        v_unres_income         AS GrandTotalUnrestricted,
        v_unres_exp            AS TotalUnrestrictedExpenses,
        v_unres_net            AS NetGrandTotalUnrestricted,
        v_real_exp_all         AS TotalRealExpensesAll,
        v_res_exp              AS TotalRestrictedExpenses;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_UnrestrictedSums`;
DELIMITER $$
CREATE PROCEDURE `Finance_UnrestrictedSums`(
    IN `target_church_id` INT
)
BEGIN
    -- We select all sums as subqueries to get a single row result
    SELECT
        -- 1. Total Tithes
        (SELECT COALESCE(SUM(amount), 0)
         FROM register_tithe
         WHERE church_id = target_church_id)
         AS TotalTithes,

        -- 2. Total Offerings
        (SELECT COALESCE(SUM(amount), 0)
         FROM register_offering
         WHERE church_id = target_church_id)
         AS TotalOfferings,

        -- 3. Total Unrestricted Donations (is_restricted = 0)
        (SELECT COALESCE(SUM(rd.amount), 0)
         FROM register_donations rd
         JOIN register_donationcategory cat ON rd.donations_type_id = cat.id
         WHERE rd.church_id = target_church_id
         AND cat.is_restricted = 0)
         AS TotalUnrestrictedDonations,

        -- 4. Total Unrestricted Other Income (is_restricted = 0)
        (SELECT COALESCE(SUM(roi.amount), 0)
         FROM register_otherincome roi
         JOIN register_otherincomecategory cat ON roi.income_type_id = cat.id
         WHERE roi.church_id = target_church_id
         AND cat.is_restricted = 0)
         AS TotalUnrestrictedOtherIncome,

        -- 5. GRAND TOTAL (Sum of all the above)
        (
            (SELECT COALESCE(SUM(amount), 0) FROM register_tithe WHERE church_id = target_church_id) +
            (SELECT COALESCE(SUM(amount), 0) FROM register_offering WHERE church_id = target_church_id) +
            (SELECT COALESCE(SUM(rd.amount), 0) FROM register_donations rd JOIN register_donationcategory cat ON rd.donations_type_id = cat.id WHERE rd.church_id = target_church_id AND cat.is_restricted = 0) +
            (SELECT COALESCE(SUM(roi.amount), 0) FROM register_otherincome roi JOIN register_otherincomecategory cat ON roi.income_type_id = cat.id WHERE roi.church_id = target_church_id AND cat.is_restricted = 0)
        )
        AS GrandTotalUnrestricted;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_WeeklyDetailedReport`;
DELIMITER $$
CREATE PROCEDURE `Finance_WeeklyDetailedReport`(
    IN target_church_id INT
)
BEGIN
    SELECT
        YEARWEEK(txn_date, 1) AS SortWeek,
        DATE_FORMAT(txn_date, '%x-%v') AS DisplayWeek,
        txn_type,
        category_name,
        SUM(amount) AS total_amount
    FROM (
        /* 1) Tithes */
        SELECT
            t.date AS txn_date,
            'Tithe' AS txn_type,
            'Tithes' AS category_name,
            t.amount AS amount
        FROM register_tithe t
        WHERE t.church_id = target_church_id

        UNION ALL

        /* 2) Offerings */
        SELECT
            o.date AS txn_date,
            'Offering' AS txn_type,
            'Loose Offering' AS category_name,
            o.amount AS amount
        FROM register_offering o
        WHERE o.church_id = target_church_id

        UNION ALL

        /* 3) Donations */
        SELECT
            d.donations_date AS txn_date,
            CASE
                WHEN COALESCE(dc.is_restricted, 0) = 1 THEN 'Res_Donation'
                ELSE 'Unres_Donation'
            END AS txn_type,
            COALESCE(dc.name, 'Uncategorized Donation') AS category_name,
            d.amount AS amount
        FROM register_donations d
        LEFT JOIN register_donationcategory dc
               ON dc.id = d.donations_type_id
        WHERE d.church_id = target_church_id

        UNION ALL

        /* 4) Other Income */
        SELECT
            oi.date AS txn_date,

            CASE
                /* Budget Return saved as Other Income should behave like budget expense */
                WHEN LOWER(TRIM(COALESCE(oic.name,''))) LIKE 'budget return%'
                     OR LOWER(TRIM(COALESCE(oi.description,''))) LIKE 'budget return%'
                    THEN 'Res_Expense'

                WHEN COALESCE(oic.is_restricted, 0) = 1 THEN 'Res_Other'
                ELSE 'Unres_Other'
            END AS txn_type,

            CASE
                /* Budget Return - Bank */
                WHEN LOWER(TRIM(COALESCE(oic.name,''))) LIKE 'budget return - bank%'
                  OR LOWER(TRIM(COALESCE(oi.description,''))) LIKE 'budget return - bank%'
                  OR UPPER(COALESCE(cbm_oi.direction,'')) LIKE '%BANK%'
                THEN CONCAT(
                    'Bank:Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(oi.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return'
                    )
                )

                /* Budget Return - Cash */
                WHEN LOWER(TRIM(COALESCE(oic.name,''))) LIKE 'budget return - cash%'
                  OR LOWER(TRIM(COALESCE(oi.description,''))) LIKE 'budget return - cash%'
                  OR UPPER(COALESCE(cbm_oi.direction,'')) LIKE '%CASH%'
                THEN CONCAT(
                    'Cash:Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(oi.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return'
                    )
                )

                /* Other Budget Return -> same style, no Unknown */
                WHEN LOWER(TRIM(COALESCE(oic.name,''))) LIKE 'budget return%'
                  OR LOWER(TRIM(COALESCE(oi.description,''))) LIKE 'budget return%'
                THEN CONCAT(
                    'Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(oi.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return'
                    )
                )

                ELSE COALESCE(oic.name, 'Uncategorized Other Income')
            END AS category_name,

            oi.amount AS amount
        FROM register_otherincome oi
        LEFT JOIN register_otherincomecategory oic
               ON oic.id = oi.income_type_id
        LEFT JOIN (
            SELECT
                church_id,
                source_id,
                MAX(direction) AS direction
            FROM register_cashbankmovement
            WHERE source_type = 'OTHER_INCOME'
            GROUP BY church_id, source_id
        ) cbm_oi
               ON cbm_oi.church_id = oi.church_id
              AND cbm_oi.source_id = oi.id
        WHERE oi.church_id = target_church_id

        UNION ALL

        /* 5) Expenses */
        SELECT
            e.expense_date AS txn_date,

            CASE
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'bank deposit'
                    THEN 'Transfer_Deposit'
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) IN ('bank withdraw', 'bank withdrawal')
                    THEN 'Transfer_Withdraw'
                WHEN COALESCE(ec.is_transfer, 0) = 1
                    THEN 'Transfer_Deposit'
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank depos%'
                    THEN 'Transfer_Deposit'
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank withdr%'
                    THEN 'Transfer_Withdraw'
                WHEN LOWER(TRIM(COALESCE(e.description,''))) LIKE '%bank depos%'
                    THEN 'Transfer_Deposit'
                WHEN LOWER(TRIM(COALESCE(e.description,''))) LIKE '%bank withdr%'
                    THEN 'Transfer_Withdraw'

                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'budget release'
                    THEN 'System_BudgetRelease'

                WHEN LOWER(TRIM(COALESCE(ec.name,''))) IN (
                    'budget release - bank',
                    'budget release - cash',
                    'budget release (unposted)'
                )
                    THEN 'Res_Expense'
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'budget return%'
                    THEN 'Res_Expense'
                WHEN COALESCE(ec.description,'') LIKE '%Synced Restricted Donation%'
                  OR COALESCE(ec.description,'') LIKE '%Auto-generated restricted fund%'
                  OR COALESCE(ec.description,'') LIKE '%Synced Restricted Income%'
                    THEN 'Res_Expense'
                ELSE 'Gen_Expense'
            END AS txn_type,

            CASE
                /* Budget Release - Bank */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'budget release - bank'
                THEN CONCAT(
                    'Bank:Budget Release: ',
                    COALESCE(
                        NULLIF(TRIM(e.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(e.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Release - Bank'
                    )
                )

                /* Budget Release - Cash */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'budget release - cash'
                THEN CONCAT(
                    'Cash:Budget Release: ',
                    COALESCE(
                        NULLIF(TRIM(e.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(e.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Release - Cash'
                    )
                )

                /* Budget Release - Unposted */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'budget release (unposted)'
                THEN CONCAT(
                    'Unposted:Budget Release: ',
                    COALESCE(
                        NULLIF(TRIM(e.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(e.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Release'
                    )
                )

                /* Budget Return - Bank */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'budget return - bank%'
                THEN CONCAT(
                    'Bank:Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(e.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(e.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return - Bank'
                    )
                )

                /* Budget Return - Cash */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'budget return - cash%'
                THEN CONCAT(
                    'Cash:Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(e.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(e.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return - Cash'
                    )
                )

                /* Other budget return */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'budget return%'
                THEN CONCAT(
                    CASE
                        WHEN UPPER(COALESCE(cbm.direction,'')) LIKE '%BANK%' THEN 'Bank:'
                        WHEN UPPER(COALESCE(cbm.direction,'')) LIKE '%CASH%' THEN 'Cash:'
                        ELSE ''
                    END,
                    'Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(e.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(e.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return'
                    )
                )

                /* Normal expenses */
                ELSE CONCAT(
                    CASE
                        WHEN UPPER(COALESCE(cbm.direction,'')) LIKE '%BANK%' THEN 'Bank:'
                        WHEN UPPER(COALESCE(cbm.direction,'')) LIKE '%CASH%' THEN 'Cash:'
                        ELSE ''
                    END,
                    COALESCE(ec.name, 'Uncategorized Expense')
                )
            END AS category_name,

            e.amount AS amount
        FROM register_expense e
        LEFT JOIN register_expensecategory ec
               ON ec.id = e.category_id
        LEFT JOIN (
            SELECT
                church_id,
                source_id,
                MAX(direction) AS direction
            FROM register_cashbankmovement
            WHERE source_type = 'EXPENSE'
            GROUP BY church_id, source_id
        ) cbm
               ON cbm.church_id = e.church_id
              AND cbm.source_id = e.id
        WHERE e.church_id = target_church_id
          AND COALESCE(e.status, '') <> 'Rejected'

        UNION ALL

        /* 6) ReleasedBudget fallback */
        SELECT
            rb.date_released AS txn_date,
            'Res_Expense' AS txn_type,
            CONCAT(
                CASE
                    WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) IN ('bank', 'bank balance') THEN 'Bank:'
                    WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) IN ('cash', 'physical cash', 'ministry wallet') THEN 'Cash:'
                    ELSE ''
                END,
                'Budget Release: ',
                COALESCE(
                    NULLIF(TRIM(rb.remarks), ''),
                    CASE
                        WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) IN ('bank', 'bank balance')
                            THEN 'Budget Release - Bank'
                        WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) IN ('cash', 'physical cash', 'ministry wallet')
                            THEN 'Budget Release - Cash'
                        ELSE 'Budget Release'
                    END
                )
            ) AS category_name,
            rb.amount AS amount
        FROM register_releasedbudget rb
        WHERE rb.church_id = target_church_id
          AND NOT EXISTS (
                SELECT 1
                FROM register_expense e2
                LEFT JOIN register_expensecategory ec2
                       ON ec2.id = e2.category_id
                WHERE e2.church_id = rb.church_id
                  AND COALESCE(e2.status, '') <> 'Rejected'
                  AND (
                        LOWER(TRIM(COALESCE(e2.description, '')))
                            LIKE CONCAT('%release id ', rb.id, '%')
                        OR (
                            LOWER(TRIM(COALESCE(ec2.name, ''))) IN (
                                'budget release',
                                'budget release - cash',
                                'budget release - bank'
                            )
                            AND e2.amount = rb.amount
                        )
                  )
          )

    ) AS RawData
    GROUP BY
        YEARWEEK(txn_date, 1),
        DATE_FORMAT(txn_date, '%x-%v'),
        txn_type,
        category_name
    ORDER BY
        SortWeek DESC,
        txn_type ASC,
        category_name ASC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_WeeklyReport`;
DELIMITER $$
CREATE PROCEDURE `Finance_WeeklyReport`(
    IN `target_church_id` INT
)
BEGIN
    SELECT
        -- Display Week (e.g., "2024-42")
        DisplayWeek,

        -- =============================================
        -- 1. GENERAL INCOME
        -- =============================================
        SUM(Gen_Tithes) AS Total_Tithes,
        SUM(Gen_Offerings) AS Total_Offerings,
        SUM(Gen_Unrestricted_OtherIncome) AS Unrestricted_OtherIncome,
        SUM(Gen_Unrestricted_Donations) AS Unrestricted_Donations,

        (SUM(Gen_Tithes) + SUM(Gen_Offerings) + SUM(Gen_Unrestricted_OtherIncome) + SUM(Gen_Unrestricted_Donations)) AS TOTAL_GENERAL_INCOME,

        -- =============================================
        -- 2. RESTRICTED INCOME
        -- =============================================
        SUM(Res_OtherIncome) AS Restricted_OtherIncome,
        SUM(Res_Donations) AS Restricted_Donations,

        (SUM(Res_OtherIncome) + SUM(Res_Donations)) AS TOTAL_RESTRICTED_INCOME,

        -- =============================================
        -- 3. EXPENSES (Restricted vs General)
        -- =============================================
        SUM(Res_Expenses) AS Restricted_Expenses,
        SUM(Gen_Expenses) AS General_Expenses,

        (SUM(Res_Expenses) + SUM(Gen_Expenses)) AS TOTAL_EXPENSES,

        -- =============================================
        -- 4. NET TOTAL
        -- =============================================
        (
            (SUM(Gen_Tithes) + SUM(Gen_Offerings) + SUM(Gen_Unrestricted_OtherIncome) + SUM(Gen_Unrestricted_Donations) + SUM(Res_OtherIncome) + SUM(Res_Donations))
            -
            (SUM(Res_Expenses) + SUM(Gen_Expenses))
        ) AS WEEKLY_NET_BALANCE

    FROM (
        -- [A-D Sections remain the same: Tithes, Offerings, Donations, Other Income]

        -- A. TITHES
        SELECT
            YEARWEEK(date, 1) as WeekVal, DATE_FORMAT(date, '%x-%v') as DisplayWeek,
            amount as Gen_Tithes, 0 as Gen_Offerings, 0 as Gen_Unrestricted_OtherIncome, 0 as Gen_Unrestricted_Donations,
            0 as Res_OtherIncome, 0 as Res_Donations,
            0 as Res_Expenses, 0 as Gen_Expenses
        FROM register_tithe WHERE church_id = target_church_id

        UNION ALL

        -- B. OFFERINGS
        SELECT
            YEARWEEK(date, 1), DATE_FORMAT(date, '%x-%v'),
            0, amount, 0, 0,
            0, 0,
            0, 0
        FROM register_offering WHERE church_id = target_church_id

        UNION ALL

        -- C. DONATIONS
        SELECT
            YEARWEEK(rd.donations_date, 1), DATE_FORMAT(rd.donations_date, '%x-%v'),
            0, 0,
            CASE WHEN dc.is_restricted = 0 THEN rd.amount ELSE 0 END,
            0, 0,
            CASE WHEN dc.is_restricted = 1 THEN rd.amount ELSE 0 END,
            0, 0
        FROM register_donations rd
        JOIN register_donationcategory dc ON rd.donations_type_id = dc.id
        WHERE rd.church_id = target_church_id

        UNION ALL

        -- D. OTHER INCOME
        SELECT
            YEARWEEK(roi.date, 1), DATE_FORMAT(roi.date, '%x-%v'),
            0, 0,
            0,
            CASE WHEN oic.is_restricted = 0 THEN roi.amount ELSE 0 END,
            CASE WHEN oic.is_restricted = 1 THEN roi.amount ELSE 0 END,
            0,
            0, 0
        FROM register_otherincome roi
        JOIN register_otherincomecategory oic ON roi.income_type_id = oic.id
        WHERE roi.church_id = target_church_id

        UNION ALL

        -- ---------------------------------------------
        -- E. EXPENSES (UPDATED LOGIC)
        -- ---------------------------------------------
        SELECT
            YEARWEEK(re.expense_date, 1),
            DATE_FORMAT(re.expense_date, '%x-%v'),
            0, 0, 0, 0, 0, 0,

            -- RESTRICTED EXPENSES: Only if category exists AND matches magic words
            CASE
                WHEN ec.description IS NOT NULL AND (
                     ec.description LIKE '%Synced Restricted Donation%'
                  OR ec.description LIKE '%Auto-generated restricted fund%'
                  OR ec.description LIKE '%Synced Restricted Income%'
                )
                THEN re.amount ELSE 0
            END,

            -- GENERAL EXPENSES: Anything else (NULL category, normal category, etc.)
            CASE
                WHEN ec.description IS NULL -- No category assigned
                  OR (
                     ec.description NOT LIKE '%Synced Restricted Donation%'
                     AND ec.description NOT LIKE '%Auto-generated restricted fund%'
                     AND ec.description NOT LIKE '%Synced Restricted Income%'
                  )
                THEN re.amount ELSE 0
            END

        FROM register_expense re
        -- Changed JOIN to LEFT JOIN to include expenses without valid categories
        LEFT JOIN register_expensecategory ec ON re.category_id = ec.id
        WHERE re.church_id = target_church_id

    ) AS UnifiedData

    GROUP BY WeekVal, DisplayWeek
    ORDER BY WeekVal DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_WeeklyTransactions`;
DELIMITER $$
CREATE PROCEDURE `Finance_WeeklyTransactions`(IN week_date DATE)
BEGIN
    SELECT
        'Expense' AS TransactionType,
        register_expense.id AS TransactionID,
        register_expense.expense_date AS TransactionDate,
        register_expense.expense_type AS Typeof,
        register_expense.other_expense_type AS TypeOthers,
        register_expense.amount AS amount,
        created_by.id AS UserID,
        created_by.first_name,
        edited_by.id AS EditedByID,
        edited_by.first_name AS EditedByName
    FROM
        register_expense
    LEFT JOIN
        register_customuser AS created_by ON register_expense.created_by_id = created_by.id
    LEFT JOIN
        register_customuser AS edited_by ON register_expense.edited_by_id = edited_by.id
    WHERE
        register_expense.expense_date BETWEEN week_date AND DATE_ADD(week_date, INTERVAL 7 DAY)
    UNION ALL

    SELECT
        'Offering' AS TransactionType,
        register_offering.id AS TransactionID,
        register_offering.date AS TransactionDate,
        '' AS Typeof,
        '' AS TypeOthers,
        register_offering.amount AS amount,
        created_by.id AS UserID,
        created_by.first_name,
        edited_by.id AS EditedByID,
        edited_by.first_name AS EditedByName
    FROM
        register_offering
    LEFT JOIN
        register_customuser AS created_by ON register_offering.created_by_id = created_by.id
    LEFT JOIN
        register_customuser AS edited_by ON register_offering.edited_by_id = edited_by.id
    WHERE
        register_offering.date BETWEEN week_date AND DATE_ADD(week_date, INTERVAL 7 DAY)

    UNION ALL

    SELECT
        'Donations' AS TransactionType,
        register_donations.id AS TransactionID,
        register_donations.donations_date AS TransactionDate,
        register_donations.donations_type AS Typeof,
        register_donations.other_donations_type AS TypeOthers,
        register_donations.amount AS amount,
        created_by.id AS UserID,
        created_by.first_name,
        edited_by.id AS EditedByID,
        edited_by.first_name AS EditedByName
    FROM
        register_donations
    LEFT JOIN
        register_customuser AS created_by ON register_donations.created_by_id = created_by.id
    LEFT JOIN
        register_customuser AS edited_by ON register_donations.edited_by_id = edited_by.id
    WHERE
        register_donations.donations_date BETWEEN week_date AND DATE_ADD(week_date, INTERVAL 7 DAY)

    UNION ALL

    SELECT
        'Tithe' AS TransactionType,
        register_tithe.id AS TransactionID,
        register_tithe.date AS TransactionDate,
        '' AS Typeof,
        '' AS TypeOthers,
        register_tithe.amount AS amount,
        created_by.id AS UserID,
        created_by.first_name,
        edited_by.id AS EditedByID,
        edited_by.first_name AS EditedByName
    FROM
        register_tithe
    LEFT JOIN
        register_customuser AS created_by ON register_tithe.created_by_id = created_by.id
    LEFT JOIN
        register_customuser AS edited_by ON register_tithe.edited_by_id = edited_by.id
    WHERE
        register_tithe.date BETWEEN week_date AND DATE_ADD(week_date, INTERVAL 7 DAY)

    ORDER BY
        TransactionDate DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_YearlyDetailedReport`;
DELIMITER $$
CREATE PROCEDURE `Finance_YearlyDetailedReport`(
    IN target_church_id INT
)
BEGIN
    SELECT
        DATE_FORMAT(txn_date, '%Y') AS SortKey,
        DATE_FORMAT(txn_date, '%Y') AS DisplayLabel,
        txn_type,
        category_name,
        SUM(amount) AS total_amount
    FROM (
        /* 1) Tithes */
        SELECT
            t.date AS txn_date,
            'Tithe' AS txn_type,
            'Tithes' AS category_name,
            t.amount AS amount
        FROM register_tithe t
        WHERE t.church_id = target_church_id

        UNION ALL

        /* 2) Offerings */
        SELECT
            o.date AS txn_date,
            'Offering' AS txn_type,
            'Loose Offering' AS category_name,
            o.amount AS amount
        FROM register_offering o
        WHERE o.church_id = target_church_id

        UNION ALL

        /* 3) Donations */
        SELECT
            rd.donations_date AS txn_date,
            CASE
                WHEN COALESCE(dc.is_restricted, 0) = 1 THEN 'Res_Donation'
                ELSE 'Unres_Donation'
            END AS txn_type,
            COALESCE(dc.name, 'Uncategorized Donation') AS category_name,
            rd.amount AS amount
        FROM register_donations rd
        LEFT JOIN register_donationcategory dc
               ON rd.donations_type_id = dc.id
        WHERE rd.church_id = target_church_id

        UNION ALL

        /* 4) Other Income */
        SELECT
            roi.date AS txn_date,

            CASE
                /* Budget Return belongs to General Income (Unrestricted) */
                WHEN LOWER(TRIM(COALESCE(oic.name,''))) LIKE 'budget return%'
                  OR LOWER(TRIM(COALESCE(roi.description,''))) LIKE 'budget return%'
                    THEN 'Unres_Other'

                WHEN COALESCE(oic.is_restricted, 0) = 1 THEN 'Res_Other'
                ELSE 'Unres_Other'
            END AS txn_type,

            CASE
                /* Budget Return - Bank */
                WHEN LOWER(TRIM(COALESCE(oic.name,''))) LIKE 'budget return - bank%'
                  OR LOWER(TRIM(COALESCE(roi.description,''))) LIKE 'budget return - bank%'
                  OR UPPER(COALESCE(cbm_oi.direction,'')) LIKE '%BANK%'
                THEN CONCAT(
                    'Bank:Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(roi.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return'
                    )
                )

                /* Budget Return - Cash */
                WHEN LOWER(TRIM(COALESCE(oic.name,''))) LIKE 'budget return - cash%'
                  OR LOWER(TRIM(COALESCE(roi.description,''))) LIKE 'budget return - cash%'
                  OR UPPER(COALESCE(cbm_oi.direction,'')) LIKE '%CASH%'
                THEN CONCAT(
                    'Cash:Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(roi.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return'
                    )
                )

                /* Other Budget Return */
                WHEN LOWER(TRIM(COALESCE(oic.name,''))) LIKE 'budget return%'
                  OR LOWER(TRIM(COALESCE(roi.description,''))) LIKE 'budget return%'
                THEN CONCAT(
                    'Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(roi.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return'
                    )
                )

                ELSE COALESCE(oic.name, 'Uncategorized Other Income')
            END AS category_name,

            roi.amount AS amount
        FROM register_otherincome roi
        LEFT JOIN register_otherincomecategory oic
               ON roi.income_type_id = oic.id
        LEFT JOIN (
            SELECT
                church_id,
                source_id,
                MAX(direction) AS direction
            FROM register_cashbankmovement
            WHERE source_type = 'OTHER_INCOME'
            GROUP BY church_id, source_id
        ) cbm_oi
               ON cbm_oi.church_id = roi.church_id
              AND cbm_oi.source_id = roi.id
        WHERE roi.church_id = target_church_id

        UNION ALL

        /* 5) Expenses */
        SELECT
            re.expense_date AS txn_date,

            CASE
                /* Transfers (hidden by Python) */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'bank deposit'
                    THEN 'Transfer_Deposit'
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) IN ('bank withdraw', 'bank withdrawal')
                    THEN 'Transfer_Withdraw'
                WHEN COALESCE(ec.is_transfer, 0) = 1
                    THEN 'Transfer_Deposit'
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank depos%'
                    THEN 'Transfer_Deposit'
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'bank withdr%'
                    THEN 'Transfer_Withdraw'
                WHEN LOWER(TRIM(COALESCE(re.description,''))) LIKE '%bank depos%'
                    THEN 'Transfer_Deposit'
                WHEN LOWER(TRIM(COALESCE(re.description,''))) LIKE '%bank withdr%'
                    THEN 'Transfer_Withdraw'

                /* Internal hidden budget release */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'budget release'
                    THEN 'System_BudgetRelease'

                /* Visible budget releases remain expenses */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) IN (
                    'budget release - bank',
                    'budget release - cash',
                    'budget release (unposted)'
                )
                    THEN 'Res_Expense'

                /* Budget Return belongs to General Income (Unrestricted) */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'budget return%'
                    THEN 'Unres_Other'

                /* Restricted synced expenses */
                WHEN COALESCE(ec.description,'') LIKE '%Synced Restricted Donation%'
                  OR COALESCE(ec.description,'') LIKE '%Auto-generated restricted fund%'
                  OR COALESCE(ec.description,'') LIKE '%Synced Restricted Income%'
                    THEN 'Res_Expense'

                ELSE 'Gen_Expense'
            END AS txn_type,

            CASE
                /* Budget Release - Bank */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'budget release - bank'
                THEN CONCAT(
                    'Bank:Budget Release: ',
                    COALESCE(
                        NULLIF(TRIM(re.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(re.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Release - Bank'
                    )
                )

                /* Budget Release - Cash */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'budget release - cash'
                THEN CONCAT(
                    'Cash:Budget Release: ',
                    COALESCE(
                        NULLIF(TRIM(re.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(re.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Release - Cash'
                    )
                )

                /* Budget Release - Unposted */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) = 'budget release (unposted)'
                THEN CONCAT(
                    'Unposted:Budget Release: ',
                    COALESCE(
                        NULLIF(TRIM(re.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(re.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Release'
                    )
                )

                /* Budget Return - Bank */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'budget return - bank%'
                THEN CONCAT(
                    'Bank:Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(re.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(re.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return - Bank'
                    )
                )

                /* Budget Return - Cash */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'budget return - cash%'
                THEN CONCAT(
                    'Cash:Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(re.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(re.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return - Cash'
                    )
                )

                /* Other Budget Return */
                WHEN LOWER(TRIM(COALESCE(ec.name,''))) LIKE 'budget return%'
                THEN CONCAT(
                    CASE
                        WHEN UPPER(COALESCE(cbm.direction,'')) LIKE '%BANK%' THEN 'Bank:'
                        WHEN UPPER(COALESCE(cbm.direction,'')) LIKE '%CASH%' THEN 'Cash:'
                        ELSE ''
                    END,
                    'Budget Return: ',
                    COALESCE(
                        NULLIF(TRIM(re.vendor), ''),
                        NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(TRIM(COALESCE(re.description,'')), ' | ', 1), ':', -1)), ''),
                        'Budget Return'
                    )
                )

                /* Normal expenses: prefix only when source is known */
                ELSE CONCAT(
                    CASE
                        WHEN UPPER(COALESCE(cbm.direction,'')) LIKE '%BANK%' THEN 'Bank:'
                        WHEN UPPER(COALESCE(cbm.direction,'')) LIKE '%CASH%' THEN 'Cash:'
                        ELSE ''
                    END,
                    COALESCE(ec.name, 'Uncategorized')
                )
            END AS category_name,

            re.amount AS amount
        FROM register_expense re
        LEFT JOIN register_expensecategory ec
               ON re.category_id = ec.id
        LEFT JOIN (
            SELECT
                church_id,
                source_id,
                MAX(direction) AS direction
            FROM register_cashbankmovement
            WHERE source_type = 'EXPENSE'
            GROUP BY church_id, source_id
        ) cbm
               ON cbm.church_id = re.church_id
              AND cbm.source_id = re.id
        WHERE re.church_id = target_church_id
          AND COALESCE(re.status, '') <> 'Rejected'

        UNION ALL

        /* 6) ReleasedBudget fallback (no matching expense yet) */
        SELECT
            rb.date_released AS txn_date,
            'Res_Expense' AS txn_type,
            CONCAT(
                CASE
                    WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) IN ('bank', 'bank balance') THEN 'Bank:'
                    WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) IN ('cash', 'physical cash', 'ministry wallet') THEN 'Cash:'
                    ELSE ''
                END,
                'Budget Release: ',
                COALESCE(
                    NULLIF(TRIM(rb.remarks), ''),
                    CASE
                        WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) IN ('bank', 'bank balance')
                            THEN 'Budget Release - Bank'
                        WHEN LOWER(TRIM(COALESCE(rb.deduct_from,''))) IN ('cash', 'physical cash', 'ministry wallet')
                            THEN 'Budget Release - Cash'
                        ELSE 'Budget Release'
                    END
                )
            ) AS category_name,
            rb.amount AS amount
        FROM register_releasedbudget rb
        WHERE rb.church_id = target_church_id
          AND NOT EXISTS (
                SELECT 1
                FROM register_expense e2
                LEFT JOIN register_expensecategory ec2
                       ON ec2.id = e2.category_id
                WHERE e2.church_id = rb.church_id
                  AND COALESCE(e2.status, '') <> 'Rejected'
                  AND (
                        LOWER(TRIM(COALESCE(e2.description, ''))) LIKE CONCAT('%release id ', rb.id, '%')
                        OR (
                            LOWER(TRIM(COALESCE(ec2.name, ''))) IN (
                                'budget release',
                                'budget release - cash',
                                'budget release - bank'
                            )
                            AND e2.amount = rb.amount
                        )
                  )
          )

    ) AS RawData
    GROUP BY
        SortKey,
        DisplayLabel,
        txn_type,
        category_name
    ORDER BY
        SortKey DESC,
        txn_type ASC,
        category_name ASC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Finance_YearlySummary_WithNet`;
DELIMITER $$
CREATE PROCEDURE `Finance_YearlySummary_WithNet`(
    IN `target_church_id` INT
)
BEGIN
    SELECT
        -- 1. Group by Year (YYYY)
        YearVal,
        txn_type,
        category_name,
        SUM(amount) as total_amount

    FROM (
        -- === INCOME ===
        SELECT YEAR(date) as YearVal, 'Income' as txn_type, 'Tithes' as category_name, amount FROM register_tithe WHERE church_id = target_church_id
        UNION ALL
        SELECT YEAR(date), 'Income', 'Offering', amount FROM register_offering WHERE church_id = target_church_id
        UNION ALL
        SELECT YEAR(rd.donations_date), 'Income', dc.name, rd.amount FROM register_donations rd JOIN register_donationcategory dc ON rd.donations_type_id = dc.id WHERE rd.church_id = target_church_id
        UNION ALL
        SELECT YEAR(roi.date), 'Income', oic.name, roi.amount FROM register_otherincome roi JOIN register_otherincomecategory oic ON roi.income_type_id = oic.id WHERE roi.church_id = target_church_id

        UNION ALL

        -- === EXPENSES (Negative) ===
        SELECT
            YEAR(re.expense_date),
            'Expense',
            COALESCE(ec.name, 'General Expense'),
            -re.amount
        FROM register_expense re
        LEFT JOIN register_expensecategory ec ON re.category_id = ec.id
        WHERE re.church_id = target_church_id

    ) AS AllTxns

    GROUP BY YearVal, txn_type, category_name
    ORDER BY YearVal DESC, txn_type DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `GetDonationsByChurch`;
DELIMITER $$

CREATE PROCEDURE `GetDonationsByChurch`(
    IN target_church_id BIGINT
)
BEGIN
    SELECT
        d.id,
        d.church_id,
        d.user_id,
        d.donor_type,
        d.donor,
        d.amount,
        d.donations_date,
        d.other_donations_type,
        c.name AS category_name,

        u.username AS user_name,
        TRIM(
            CONCAT_WS(
                ' ',
                NULLIF(u.first_name, ''),
                NULLIF(u.middle_name, ''),
                NULLIF(u.last_name, '')
            )
        ) AS full_name,

        CASE
            WHEN d.donor_type = 'member' THEN
                COALESCE(
                    NULLIF(TRIM(d.donor), ''),
                    NULLIF(
                        TRIM(
                            CONCAT_WS(
                                ' ',
                                NULLIF(u.first_name, ''),
                                NULLIF(u.middle_name, ''),
                                NULLIF(u.last_name, '')
                            )
                        ),
                        ''
                    ),
                    NULLIF(TRIM(u.username), ''),
                    'Member'
                )

            WHEN d.donor_type = 'non_member' THEN
                COALESCE(
                    NULLIF(TRIM(d.donor), ''),
                    'Non-member'
                )

            WHEN d.donor_type = 'anonymous' THEN
                'Anonymous'

            ELSE
                COALESCE(
                    NULLIF(TRIM(d.donor), ''),
                    'Unknown Donor'
                )
        END AS donor_display

    FROM register_donations d
    LEFT JOIN register_donationcategory c
        ON d.donations_type_id = c.id
    LEFT JOIN register_customuser u
        ON d.user_id = u.id
    WHERE d.church_id = target_church_id
    ORDER BY d.donations_date DESC, d.id DESC;
END $$

DELIMITER ;

DROP PROCEDURE IF EXISTS `GetRestrictedIncomeTotal`;
DELIMITER $$
CREATE PROCEDURE `GetRestrictedIncomeTotal`(IN target_church_id BIGINT)
BEGIN
    -- Declare variables to store the partial sums
    DECLARE donation_total DECIMAL(12,2) DEFAULT 0.00;
    DECLARE other_income_total DECIMAL(12,2) DEFAULT 0.00;

    -- 1. Sum Restricted Donations
    -- We join 'register_donations' with 'register_donationcategory'
    -- We filter where is_restricted = 1 (True)
    SELECT COALESCE(SUM(d.amount), 0.00) INTO donation_total
    FROM register_donations d
    JOIN register_donationcategory dc ON d.donations_type_id = dc.id
    WHERE d.church_id = target_church_id
      AND dc.is_restricted = 1;

    -- 2. Sum Restricted Other Income
    -- We join 'register_otherincome' with 'register_otherincomecategory'
    SELECT COALESCE(SUM(oi.amount), 0.00) INTO other_income_total
    FROM register_otherincome oi
    JOIN register_otherincomecategory oic ON oi.income_type_id = oic.id
    WHERE oi.church_id = target_church_id
      AND oic.is_restricted = 1;

    -- 3. Return the Grand Total
    SELECT (donation_total + other_income_total) AS total_restricted_income;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `GroupDonationsPerChurch`;
DELIMITER $$
CREATE PROCEDURE `GroupDonationsPerChurch`()
BEGIN
    SELECT
        church_id,
        COUNT(id) AS total_donations_count,
        SUM(amount) AS total_amount_collected
    FROM
        register_donations
    GROUP BY
        church_id;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Member_Summary`;
DELIMITER $$
CREATE PROCEDURE `Member_Summary`(
    IN `target_church_id` INT
)
BEGIN
    /*
      Summary of all users whose user_type = 'Member' AND belong to the specific church
    */

    SELECT
        cu.id,
        cu.username,
        cu.email,
        cu.first_name,
        cu.middle_name,
        cu.last_name,
        cu.province,
        cu.municipality_or_city,
        cu.barangay,
        cu.purok,
        cu.birthdate,
        cu.user_type,
        cu.year_term,
        cu.organization,
        cu.date_joined,
        cu.is_active,
        cu.status,             -- ADDED: Your custom status column
        cu.profile_picture,    -- ADDED: So member avatars load properly in HTML
        cu.is_staff,
        cu.is_superuser,
        cu.last_login,
        cu.created_by_id,
        creator.username AS created_by_username,
        creator.first_name AS created_by_first_name,
        creator.last_name AS created_by_last_name
    FROM
        register_customuser AS cu
        LEFT JOIN register_customuser AS creator
            ON cu.created_by_id = creator.id
    WHERE
        cu.user_type = 'Member'
        AND cu.church_id = target_church_id; -- Filter by Church ID
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Monthly_Financial_Summary`;
DELIMITER $$
CREATE PROCEDURE `Monthly_Financial_Summary`()
BEGIN
    SELECT
        YEAR(TransactionDate) AS Year,
        MONTH(TransactionDate) AS Month,
        SUM(CASE WHEN TransactionType = 'Tithe' THEN amount ELSE 0 END) AS TotalTithes,
        SUM(CASE WHEN TransactionType = 'Offering' THEN amount ELSE 0 END) AS TotalOffering,
        SUM(CASE WHEN TransactionType = 'Donations' THEN amount ELSE 0 END) AS TotalDonations,
        SUM(CASE WHEN TransactionType = 'Expense' THEN amount ELSE 0 END) AS TotalExpenses,
        (SUM(CASE WHEN TransactionType = 'Tithe' THEN amount ELSE 0 END) +
         SUM(CASE WHEN TransactionType = 'Offering' THEN amount ELSE 0 END) +
         SUM(CASE WHEN TransactionType = 'Donations' THEN amount ELSE 0 END) -
         SUM(CASE WHEN TransactionType = 'Expense' THEN amount ELSE 0 END)) AS TotalAccumulated
    FROM (
        SELECT 'Expense' AS TransactionType, expense_date AS TransactionDate, amount
        FROM register_expense

        UNION ALL

        SELECT 'Offering' AS TransactionType, date AS TransactionDate, amount
        FROM register_offering

        UNION ALL

        SELECT 'Donations' AS TransactionType, donations_date AS TransactionDate, amount
        FROM register_donations

        UNION ALL

        SELECT 'Tithe' AS TransactionType, date AS TransactionDate, amount
        FROM register_tithe
    ) AS Transactions
    GROUP BY YEAR(TransactionDate), MONTH(TransactionDate)
    ORDER BY Year DESC, Month DESC;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `RecomputeMinistryMonthlyLedger`;
DELIMITER $$
CREATE PROCEDURE `RecomputeMinistryMonthlyLedger`(
  IN p_church_id BIGINT,
  IN p_year INT,
  IN p_month INT
)
BEGIN
  DECLARE d_start DATE;
  DECLARE d_end DATE;

  SET d_start = STR_TO_DATE(CONCAT(p_year,'-',LPAD(p_month,2,'0'),'-01'), '%Y-%m-%d');
  SET d_end   = DATE_ADD(d_start, INTERVAL 1 MONTH);

  /*
    Build a unified dataset of:
    - releases from register_expense  (Budget Release: <ministry> | ...)
    - returns  from register_otherincome (Budget return from <ministry> | ...)
    Then aggregate per ministry.
  */

  INSERT INTO ministry_monthly_ledger (
    church_id, ministry_name, year, month,
    total_released, total_returned, net_outflow
  )
  SELECT
    p_church_id AS church_id,
    ministry_name,
    p_year AS year,
    p_month AS month,
    SUM(released_amt) AS total_released,
    SUM(returned_amt) AS total_returned,
    SUM(released_amt) - SUM(returned_amt) AS net_outflow
  FROM (
      /* Releases (cash outflow) */
      SELECT
        TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(e.description, '|', 1), 'Budget Release:', -1)) AS ministry_name,
        e.amount AS released_amt,
        0.00 AS returned_amt
      FROM register_expense e
      WHERE e.church_id = p_church_id
        AND e.status = 'Approved'
        AND e.description LIKE 'Budget Release:%'
        AND e.expense_date >= d_start
        AND e.expense_date <  d_end

      UNION ALL

      /* Returns (cash inflow) */
      SELECT
        TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(oi.description, '|', 1), 'Budget return from', -1)) AS ministry_name,
        0.00 AS released_amt,
        oi.amount AS returned_amt
      FROM register_otherincome oi
      WHERE oi.church_id = p_church_id
        AND oi.description LIKE 'Budget return from %'
        AND oi.date >= d_start
        AND oi.date <  d_end
  ) x
  GROUP BY ministry_name
  ON DUPLICATE KEY UPDATE
    total_released = VALUES(total_released),
    total_returned = VALUES(total_returned),
    net_outflow    = VALUES(net_outflow),
    updated_at     = CURRENT_TIMESTAMP;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `sp_DeleteMinistry`;
DELIMITER $$
CREATE PROCEDURE `sp_DeleteMinistry`(
    IN input_ministry_id BIGINT,
    IN input_church_id BIGINT
)
BEGIN
    DECLARE budget_count INT;

    -- 1. Check if this ministry has any budget history
    SELECT COUNT(*) INTO budget_count
    FROM register_ministrybudget
    WHERE ministry_id = input_ministry_id;

    -- 2. If it has history, STOP and throw an error
    IF budget_count > 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Cannot delete: This ministry has financial records. Please Deactivate it instead.';
    ELSE
        -- 3. If no history, it is safe to delete
        DELETE FROM register_ministry
        WHERE id = input_ministry_id AND church_id = input_church_id;
    END IF;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `sp_GetMinistryDetails`;
DELIMITER $$
CREATE PROCEDURE `sp_GetMinistryDetails`(
    IN input_church_id BIGINT
)
BEGIN
    SELECT
        id,
        name,
        code,
        description,
        -- Convert tinyint to a readable status for reports
        CASE
            WHEN is_active = 1 THEN 'Active'
            ELSE 'Inactive'
        END AS status,
        created_at,
        created_by_id,
        edited_by_id,
        church_id
    FROM
        register_ministry
    WHERE
        -- Filter by church if ID is provided, otherwise show all
        (input_church_id IS NULL OR church_id = input_church_id)
        -- Filter by active status if provided, otherwise show all
        AND (input_is_active IS NULL OR is_active = input_is_active)
    ORDER BY
        church_id,
        name;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `sp_GetMinistryDetailsByChurch`;
DELIMITER $$
CREATE PROCEDURE `sp_GetMinistryDetailsByChurch`(
    IN input_church_id BIGINT
)
BEGIN
    SELECT
        id,
        name,
        code,
        description,
        is_active,
        created_at,
        created_by_id,
        edited_by_id,
        church_id
    FROM
        register_ministry
    WHERE
        church_id = input_church_id
    ORDER BY
        is_active DESC,  -- 1 (Active) comes first, 0 (Inactive) goes last
        name ASC;        -- Then sort alphabetically

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `sp_recalculate_bank_balance`;
DELIMITER $$
CREATE PROCEDURE `sp_recalculate_bank_balance`(
    IN p_church_id BIGINT
)
BEGIN
    DECLARE v_new_balance DECIMAL(12,2) DEFAULT 0.00;

    SELECT COALESCE(SUM(
        CASE
            WHEN direction = 'CASH_TO_BANK' THEN amount
            WHEN direction = 'DIRECT_BANK_RECEIPT' THEN amount
            WHEN direction = 'BANK_TO_BANK'
                 AND source_type IN ('TITHE', 'OFFERING', 'DONATION', 'OTHER_INCOME')
                THEN amount
            WHEN direction = 'BANK_TO_CASH' THEN -amount
            WHEN direction = 'BANK_PAID_EXPENSE' THEN -amount
            ELSE 0
        END
    ), 0.00)
    INTO v_new_balance
    FROM register_cashbankmovement
    WHERE church_id = p_church_id
      AND status = 'CONFIRMED';

    UPDATE register_bankaccount
    SET current_balance = v_new_balance,
        last_updated = NOW(6)
    WHERE church_id = p_church_id;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `sp_SummarizeMinistriesByChurch`;
DELIMITER $$
CREATE PROCEDURE `sp_SummarizeMinistriesByChurch`(
    IN input_church_id BIGINT
)
BEGIN
    -- If input_church_id is NULL, it returns a summary for all churches.
    -- If input_church_id is provided, it filters for that specific church.
    SELECT
        church_id,
        COUNT(id) AS total_ministries,
        SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active_ministries,
        SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END) AS inactive_ministries,
        MAX(created_at) AS last_ministry_added_at
    FROM
        register_ministry
    WHERE
        (input_church_id IS NULL OR church_id = input_church_id)
    GROUP BY
        church_id;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `sp_SummarizeMinistryBudgetByChurch`;
DELIMITER $$
CREATE PROCEDURE `sp_SummarizeMinistryBudgetByChurch`(
    IN input_church_id BIGINT,
    IN input_year INT
)
BEGIN
    -- Logic:
    -- 1. If input_church_id is NULL, it returns stats for all churches.
    -- 2. If input_year is NULL, it sums up the budget across all years.

    SELECT
        church_id,
        -- If a specific year was requested, display it; otherwise label as 'All Years'
        IFNULL(input_year, 'All Years') AS fiscal_year,
        COUNT(id) AS total_budget_entries,
        SUM(amount_allocated) AS total_allocated_amount,
        AVG(amount_allocated) AS avg_monthly_allocation,
        MAX(created_at) AS last_updated_at
    FROM
        register_ministrybudget
    WHERE
        (input_church_id IS NULL OR church_id = input_church_id)
        AND (input_year IS NULL OR year = input_year)
    GROUP BY
        church_id;

END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `sp_UpdateMinistry`;
DELIMITER $$
CREATE PROCEDURE `sp_UpdateMinistry`(
    IN p_id BIGINT,
    IN p_name VARCHAR(80),
    IN p_code VARCHAR(50),
    IN p_description VARCHAR(255),
    IN p_church_id BIGINT,
    IN p_edited_by_id BIGINT
)
BEGIN
    UPDATE register_ministry
    SET
        name = p_name,
        code = p_code,
        description = p_description,
        edited_by_id = p_edited_by_id
    WHERE
        id = p_id AND church_id = p_church_id;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Summarize_Pastor`;
DELIMITER $$
CREATE PROCEDURE `Summarize_Pastor`(
    IN `target_church_id` INT
)
BEGIN
    /*
      Summary of all users whose user_type = 'Pastor' AND belong to the specific church
    */

    SELECT
        cu.id,
        cu.username,
        cu.email,
        cu.first_name,
        cu.middle_name,
        cu.last_name,
        cu.province,
        cu.municipality_or_city,
        cu.barangay,
        cu.purok,
        cu.birthdate,
        cu.user_type,
        cu.year_term,
        cu.organization,
        cu.date_joined,
        cu.is_active,
        cu.is_staff,
        cu.is_superuser,
        cu.last_login,
        cu.created_by_id,
        creator.username AS created_by_username,
        creator.first_name AS created_by_first_name,
        creator.last_name AS created_by_last_name
    FROM
        register_customuser AS cu
        LEFT JOIN register_customuser AS creator
            ON cu.created_by_id = creator.id
    WHERE
        cu.user_type = 'Pastor'
        AND cu.church_id = target_church_id;
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `Summarize_Treasurer`;
DELIMITER $$
CREATE PROCEDURE `Summarize_Treasurer`(
    IN `target_church_id` INT
)
BEGIN
    /*
      Summary of all users whose user_type = 'Treasurer' AND belong to the specific church
    */

    SELECT
        cu.id,
        cu.username,
        cu.email,
        cu.first_name,
        cu.middle_name,
        cu.last_name,
        cu.province,
        cu.municipality_or_city,
        cu.barangay,
        cu.purok,
        cu.birthdate,
        cu.user_type,
        cu.year_term,
        cu.organization,
        cu.date_joined,
        cu.is_active,
        cu.is_staff,
        cu.is_superuser,
        cu.last_login,
        cu.created_by_id,
        creator.username AS created_by_username,
        creator.first_name AS created_by_first_name,
        creator.last_name AS created_by_last_name
    FROM
        register_customuser AS cu
        LEFT JOIN register_customuser AS creator
            ON cu.created_by_id = creator.id
    WHERE
        cu.user_type = 'Treasurer'
        AND cu.church_id = target_church_id; -- Filter by Church ID
END $$
DELIMITER ;

DROP PROCEDURE IF EXISTS `ViewDonationsGroupedByChurch`;
DELIMITER $$
CREATE PROCEDURE `ViewDonationsGroupedByChurch`()
BEGIN
    SELECT
        id,
        church_id,
        donor,
        amount,
        donations_type_id,
        donations_date,
        gcash_reference_number
    FROM
        register_donations
    ORDER BY
        church_id ASC,     -- Groups the rows by Church ID
        donations_date DESC; -- Shows the newest donations first within that group
END $$
DELIMITER ;
