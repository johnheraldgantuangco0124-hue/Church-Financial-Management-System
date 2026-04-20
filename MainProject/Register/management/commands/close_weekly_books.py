from django.core.management.base import BaseCommand
from django.utils import timezone
from Church.models import Church
import datetime

class Command(BaseCommand):
    help = "Automatically locks financial records for the previous week (sets lock date to last Sunday)."

    def handle(self, *args, **kwargs):
        self.stdout.write("--- Starting Weekly Book Closing ---")

        today = timezone.localdate()

        # weekday(): Monday=0 ... Sunday=6
        days_to_subtract = today.weekday() + 1
        last_sunday = today - datetime.timedelta(days=days_to_subtract)

        self.stdout.write(f"Today is: {today}")
        self.stdout.write(f"Closing books up to: {last_sunday}")

        target_churches = Church.objects.filter(auto_lock_enabled=True)

        if not target_churches.exists():
            self.stdout.write(self.style.WARNING("No churches found with Auto-Lock enabled."))
            return

        count = 0
        for church in target_churches:
            try:
                # ✅ Ensure settings row exists
                settings = getattr(church, "accounting_settings", None)
                if settings is None:
                    # If your AccountingSettings model is in Register app, import it accordingly:
                    # from Register.models import AccountingSettings
                    from Register.models import AccountingSettings
                    settings = AccountingSettings.objects.create(church=church)

                settings.lock_date = last_sunday
                settings.save(update_fields=["lock_date"])

                count += 1
                self.stdout.write(f"Locked: {church.name} (lock_date={last_sunday})")

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to update {church.name}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Successfully closed books for {count} churches."))
