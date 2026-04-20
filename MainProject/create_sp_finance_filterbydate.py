#!/usr/bin/env python
"""
Create Finance_FilterByDate stored procedure
This SP is used for filtering transactions by exact date
"""

import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MainProject.settings')
django.setup()

from django.db import connection

def create_finance_filterbydate_sp():
    """Create the Finance_FilterByDate stored procedure"""
    
    sp_sql = """
    CREATE DEFINER=`root`@`localhost` PROCEDURE `Finance_FilterByDate`(
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
    END
    """
    
    try:
        with connection.cursor() as cursor:
            # Drop existing procedure if it exists
            cursor.execute("DROP PROCEDURE IF EXISTS Finance_FilterByDate")
            print("✓ Dropped existing Finance_FilterByDate procedure (if any)")
            
            # Create the new procedure
            cursor.execute(sp_sql)
            print("✓ Successfully created Finance_FilterByDate stored procedure")
            
        connection.close()
        return True
    except Exception as e:
        print(f"✗ Error creating stored procedure: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = create_finance_filterbydate_sp()
    sys.exit(0 if success else 1)

