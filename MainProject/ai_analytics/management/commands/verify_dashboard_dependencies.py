from django.core.management.base import BaseCommand
from django.db import connection
from django.contrib.auth import get_user_model

from Church.models import Church
from Register.models import (
    BankAccount,
    Tithe,
    Offering,
    Donations,
    OtherIncome,
    BudgetReleaseRequest,
    ApprovedReleaseRequest,
    ReleasedBudget,
)


class Command(BaseCommand):
    help = "Verify dashboard dependencies in production DB"

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("=== VERIFY DASHBOARD DEPENDENCIES ==="))

        # 1) Check stored procedures
        with connection.cursor() as cursor:
            cursor.execute("SHOW PROCEDURE STATUS WHERE Db = DATABASE()")
            rows = cursor.fetchall()

        procedure_names = sorted({row[1] for row in rows})
        self.stdout.write(f"Total procedures found: {len(procedure_names)}")

        required_proc = "Calculate_CashOnHand"
        if required_proc in procedure_names:
            self.stdout.write(self.style.SUCCESS(f"FOUND procedure: {required_proc}"))
        else:
            self.stdout.write(self.style.ERROR(f"MISSING procedure: {required_proc}"))
            return

        # 2) Get a church to test against
        church = Church.objects.order_by("id").first()
        if not church:
            self.stdout.write(self.style.ERROR("No Church record found in production database."))
            return

        self.stdout.write(self.style.WARNING(f"Testing with church_id={church.id} | church_name={church.name}"))

        # 3) Test exact stored procedure call used by /home/
        try:
            with connection.cursor() as cursor:
                cursor.callproc(required_proc, [church.id])
                row = cursor.fetchone()

                try:
                    cursor.fetchall()
                except Exception:
                    pass

                while cursor.nextset():
                    try:
                        cursor.fetchall()
                    except Exception:
                        pass

            self.stdout.write(self.style.SUCCESS(f"{required_proc}({church.id}) returned: {row}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Procedure call failed: {e}"))
            raise

        # 4) Test core dashboard queries
        try:
            User = get_user_model()

            self.stdout.write(f"Users for church: {User.objects.filter(church=church).count()}")
            self.stdout.write(f"Bank accounts: {BankAccount.objects.filter(church=church).count()}")
            self.stdout.write(f"Tithes: {Tithe.objects.filter(church=church).count()}")
            self.stdout.write(f"Offerings: {Offering.objects.filter(church=church).count()}")
            self.stdout.write(f"Donations: {Donations.objects.filter(church=church).count()}")
            self.stdout.write(f"Other income: {OtherIncome.objects.filter(church=church).count()}")
            self.stdout.write(f"Budget requests: {BudgetReleaseRequest.objects.filter(church=church).count()}")
            self.stdout.write(f"Approved releases: {ApprovedReleaseRequest.objects.filter(church=church).count()}")
            self.stdout.write(f"Released budgets: {ReleasedBudget.objects.filter(church=church).count()}")

            self.stdout.write(self.style.SUCCESS("Core dashboard model queries succeeded."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Dashboard model query failed: {e}"))
            raise

        self.stdout.write(self.style.SUCCESS("=== VERIFY DASHBOARD DEPENDENCIES PASSED ==="))