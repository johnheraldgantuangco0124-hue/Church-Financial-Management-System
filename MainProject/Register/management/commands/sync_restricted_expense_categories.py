from django.core.management.base import BaseCommand
from Register.models import ExpenseCategory, DonationCategory, OtherIncomeCategory

class Command(BaseCommand):
    help = "Sync restricted Donation/OtherIncome funds into ExpenseCategory (restricted + linked)."

    def handle(self, *args, **options):
        updated = 0
        created = 0

        # 1) Donation restricted funds -> ExpenseCategory
        for dc in DonationCategory.objects.filter(is_restricted=True):
            ec, was_created = ExpenseCategory.objects.update_or_create(
                church=dc.church,
                name=dc.name,
                defaults={
                    "is_restricted": True,
                    "restricted_source": "DONATION",
                    "restricted_category_id": dc.id,
                    "is_system": True,   # lock as system-managed
                    "description": f"Auto-generated restricted fund from Donation: {dc.name}",
                }
            )
            created += int(was_created)
            updated += int(not was_created)

        # 2) OtherIncome restricted funds -> ExpenseCategory
        for oic in OtherIncomeCategory.objects.filter(is_restricted=True):
            ec, was_created = ExpenseCategory.objects.update_or_create(
                church=oic.church,
                name=oic.name,
                defaults={
                    "is_restricted": True,
                    "restricted_source": "OTHER_INCOME",
                    "restricted_category_id": oic.id,
                    "is_system": True,
                    "description": f"Auto-generated restricted fund from Other Income: {oic.name}",
                }
            )
            created += int(was_created)
            updated += int(not was_created)

        self.stdout.write(self.style.SUCCESS(
            f"Sync complete. Created: {created}, Updated: {updated}"
        ))