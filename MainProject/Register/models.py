# myapp/models.py

from django.contrib.auth.models import AbstractUser
from django.utils import timezone
# Import Church from the 'Church' app specifically
from Church.models import Church
from django.db.models import Sum
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator
from django.apps import apps
from django.db.models import Q, Sum
from django.db import models, transaction
from django.conf import settings
from django.db.models import Sum
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, FileExtensionValidator
from django.db import models
from datetime import timedelta


class CustomUser(AbstractUser):
    # ——— Choices defined as Classes ———
    class UserType(models.TextChoices):
        ADMIN = 'Admin', 'Admin'
        DENOMINATION_ADMIN = 'DenominationAdmin', 'DenominationAdmin'
        CHURCH_ADMIN = 'ChurchAdmin', 'ChurchAdmin'
        TREASURER = 'Treasurer', 'Treasurer'
        PASTOR = 'Pastor', 'Pastor'
        MEMBER = 'Member', 'Member'

    class Organization(models.TextChoices):
        MENS = 'Mens', "Men's Ministry"
        WOMENS = 'Womens', "Women's Ministry"
        YOUNG_PEOPLE = 'YoungPeople', 'Young People'

    class YearTerm(models.TextChoices):
        ONE_YEAR = '1', '1 Year'
        TWO_YEARS = '2', '2 Years'

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    # ——— Person info ———
    middle_name = models.CharField(max_length=30, blank=True, default='')

    # Address
    province = models.CharField(max_length=100, blank=True, default='')
    municipality_or_city = models.CharField(max_length=100, blank=True, default='')
    barangay = models.CharField(max_length=100, blank=True, default='')
    purok = models.CharField(max_length=100, blank=True, default='')

    # Dates
    birthdate = models.DateField(blank=True, null=True, default=None)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    # ——— Role & org meta ———
    user_type = models.CharField(max_length=20, choices=UserType.choices)
    year_term = models.CharField(max_length=1, choices=YearTerm.choices, blank=True, null=True)
    organization = models.CharField(max_length=20, choices=Organization.choices, blank=True, null=True)

    # Account status
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE
    )

    # Used to reset the inactivity counter when admin re-enables the account
    inactivity_reset_at = models.DateTimeField(null=True, blank=True)

    # Optional audit helpers
    disabled_at = models.DateTimeField(null=True, blank=True)
    disabled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='disabled_users'
    )

    # ——— Multi-tenant links ———
    church = models.ForeignKey(
        'Church.Church',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users'
    )
    denomination = models.ForeignKey(
        'Church.Denomination',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users'
    )

    # ——— Audit ———
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_users'
    )

    # ——— Calculated Properties ———
    @property
    def age(self):
        if not self.birthdate:
            return 0
        today = timezone.now().date()
        return today.year - self.birthdate.year - (
            (today.month, today.day) < (self.birthdate.month, self.birthdate.day)
        )

    @property
    def inactivity_anchor(self):
        """
        Base datetime used for inactivity counting.
        Priority is the latest of:
        - last_login
        - inactivity_reset_at (when admin re-enables account)
        - date_joined
        """
        values = [v for v in [self.last_login, self.inactivity_reset_at, self.date_joined] if v]
        return max(values) if values else None

    @property
    def inactive_days(self):
        anchor = self.inactivity_anchor
        if not anchor:
            return 0
        return (timezone.now() - anchor).days

    @property
    def should_auto_disable(self):
        """
        Auto-disable Treasurer, Pastor, and Member after 100 days of inactivity.
        """
        return (
            self.user_type in {
                self.UserType.TREASURER,
                self.UserType.PASTOR,
                self.UserType.MEMBER,
            }
            and self.status == self.Status.ACTIVE
            and self.inactive_days >= 100
        )

    # ——— Validation ———
    def clean(self):
        super().clean()
        errors = {}

        # Tenant / role validation
        if self.user_type == self.UserType.CHURCH_ADMIN and not self.church:
            errors['church'] = "ChurchAdmin must belong to a Church."

        if self.user_type == self.UserType.DENOMINATION_ADMIN and not self.denomination:
            errors['denomination'] = "DenominationAdmin must belong to a Denomination."

        if self.user_type in {
            self.UserType.TREASURER,
            self.UserType.PASTOR,
            self.UserType.MEMBER,
        } and not self.church:
            errors['church'] = f"{self.user_type} must belong to a Church."

        # Normalize links based on role
        if self.user_type == self.UserType.ADMIN:
            self.church = None
            self.denomination = None

        elif self.user_type == self.UserType.DENOMINATION_ADMIN:
            self.church = None

        # Optional consistency check:
        # if self.church and self.denomination and self.church.denomination_id != self.denomination_id:
        #     errors['denomination'] = "Selected denomination does not match the selected church."

        if errors:
            raise ValidationError(errors)

    # ——— Account actions ———
    def disable_account(self, by_user=None, save=True):
        self.status = self.Status.INACTIVE
        self.is_active = False
        self.disabled_at = timezone.now()
        self.disabled_by = by_user
        if save:
            self.save(update_fields=['status', 'is_active', 'disabled_at', 'disabled_by'])

    def enable_account(self, by_user=None, save=True):
        self.status = self.Status.ACTIVE
        self.is_active = True
        self.inactivity_reset_at = timezone.now()
        self.disabled_at = None
        self.disabled_by = None
        if save:
            self.save(update_fields=[
                'status',
                'is_active',
                'inactivity_reset_at',
                'disabled_at',
                'disabled_by',
            ])

    # ——— Save hook ———
    def save(self, *args, **kwargs):
        # Normalization logic
        if self.user_type == self.UserType.TREASURER:
            self.organization = None

        if self.user_type == self.UserType.MEMBER:
            self.year_term = None

        if self.user_type == self.UserType.DENOMINATION_ADMIN:
            self.church = None

        if self.user_type == self.UserType.ADMIN:
            self.church = None
            self.denomination = None

        # Sync custom status with Django auth flag
        self.is_active = (self.status == self.Status.ACTIVE)

        # Make sure model validation is enforced even on direct save()
        self.full_clean()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.get_user_type_display()}) - {self.status}"

    class Meta:
        indexes = [
            models.Index(fields=['user_type']),
            models.Index(fields=['status']),
        ]

class Tithe(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tithes', null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    description = models.CharField(max_length=200, default="No description")
    file = models.FileField(upload_to='tithes/', null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    church = models.ForeignKey(
        'Church.Church',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tithes'
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_tithes'
    )
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='edited_tithes'
    )

    updated_at = models.DateTimeField(auto_now=True, null=True)

    def clean(self):
        """
        Enforces a strictly 'Next Week Only' window based on the Lock Date.
        """
        if self.church and hasattr(self.church, 'accounting_settings'):
            lock_date = self.church.accounting_settings.lock_date

            if lock_date:
                # 1. PAST LOCK: Date must be AFTER the lock date
                if self.date <= lock_date:
                    raise ValidationError(
                        f"PERIOD LOCKED: The books are closed up to {lock_date}. "
                        "You cannot add or edit records in this closed period."
                    )

                # 2. FUTURE WINDOW: Date must be within 7 DAYS of the lock date
                # Example: If lock is 18th, allowed window is 19th to 25th.
                max_allowed_date = lock_date + timedelta(days=7)

                if self.date > max_allowed_date:
                    raise ValidationError(
                        f"DATE BLOCKED: Based on your lock date ({lock_date}), "
                        f"you are currently only allowed to enter records from "
                        f"{lock_date + timedelta(days=1)} to {max_allowed_date}. "
                        f"The date {self.date} is too far ahead."
                    )
            else:
                # Fallback if no lock date is set yet: Block strict future dates (7 days buffer)
                today = timezone.now().date()
                future_limit = today + timedelta(days=7)
                if self.date > future_limit:
                    raise ValidationError(f"FUTURE DATE BLOCKED: You cannot enter dates past {future_limit}.")

        super().clean()

    def save(self, *args, **kwargs):
        # Force validation on every save (Admin, Forms, APIs)
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Tithe of {self.amount} on {self.date}"


class Offering(models.Model):
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Approved", "Approved"),
        ("Rejected", "Rejected"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="offerings",
        null=True,
        blank=True
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    description = models.CharField(max_length=200, default="No description")

    church = models.ForeignKey(
        "Church.Church",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offerings"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_offerings"
    )

    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edited_offerings"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending"
    )

    proof_document = models.FileField(
        upload_to="offering_proofs/",
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["jpg", "jpeg", "png", "pdf"]
            )
        ],
        help_text="Upload JPG, PNG, or PDF of the tally sheet, envelope summary, or deposit slip."
    )

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = "Offering"
        verbose_name_plural = "Offerings"

    def clean(self):
        super().clean()

        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "Amount must be greater than zero."})

        if not self.date:
            raise ValidationError({"date": "Offering date is required."})

        if not self.church:
            return

        try:
            settings_obj = self.church.accounting_settings
        except ObjectDoesNotExist:
            settings_obj = None

        if settings_obj:
            lock_date = settings_obj.lock_date

            if lock_date:
                # Consistent with your accounting rule:
                # before lock_date = blocked
                # equal to lock_date = allowed
                if self.date < lock_date:
                    raise ValidationError(
                        f"PERIOD LOCKED: The books are closed before {lock_date}. "
                        "You cannot add or edit records in this closed period."
                    )

                max_allowed_date = lock_date + timedelta(days=7)

                if self.date > max_allowed_date:
                    raise ValidationError(
                        f"DATE BLOCKED: Based on your lock date ({lock_date}), "
                        f"you are currently only allowed to enter records from "
                        f"{lock_date} to {max_allowed_date}. "
                        f"The date {self.date} is too far ahead."
                    )
            else:
                today = timezone.now().date()
                future_limit = today + timedelta(days=7)

                if self.date > future_limit:
                    raise ValidationError(
                        f"FUTURE DATE BLOCKED: You cannot enter dates past {future_limit}."
                    )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Offering of {self.amount} on {self.date}"


class ExpenseCategory(models.Model):
    RESTRICTED_SOURCE_CHOICES = [
        ("DONATION", "Donation Fund"),
        ("OTHER_INCOME", "Other Income Fund"),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    # existing flags
    is_transfer = models.BooleanField(default=False)
    is_system = models.BooleanField(default=False)

    # fund accounting linkage
    is_restricted = models.BooleanField(
        default=False,
        help_text="If True, this expense category is tied to a specific restricted fund."
    )
    restricted_source = models.CharField(
        max_length=20,
        choices=RESTRICTED_SOURCE_CHOICES,
        null=True,
        blank=True
    )
    restricted_category_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="ID of DonationCategory or OtherIncomeCategory this expense category belongs to."
    )

    # ✅ IMPORTANT: stable identity for matching + reporting + SPs
    # U (unrestricted), D:<id> (restricted donation fund), I:<id> (restricted other income fund)
    fund_key = models.CharField(
        max_length=30,
        default="U",
        db_index=True
    )

    church = models.ForeignKey(
        'Church.Church',
        on_delete=models.CASCADE,
        related_name='expense_categories'
    )

    class Meta:
        verbose_name_plural = "Expense Categories"
        constraints = [
            # Unrestricted: name must be unique per church (so normal categories don't duplicate)
            models.UniqueConstraint(
                fields=["church", "name"],
                condition=Q(is_restricted=False),
                name="uniq_unrestricted_expensecategory_name_per_church",
            ),
            # Restricted: fund_key must be unique per church (prevents duplicate mapping)
            models.UniqueConstraint(
                fields=["church", "fund_key"],
                condition=Q(is_restricted=True),
                name="uniq_restricted_expensecategory_fund_key_per_church",
            ),
        ]

    def compute_fund_key(self) -> str:
        """
        Compute the fund_key for restricted categories.
        This function ensures the correct fund_key is used when the category is restricted.
        """
        if not self.is_restricted:
            return "U"  # Unrestricted categories are marked as 'U'

        # Depending on the restricted_source, assign a prefix to the fund_key
        prefix = "D" if self.restricted_source == "DONATION" else "I"
        return f"{prefix}:{int(self.restricted_category_id)}" if self.restricted_category_id else None

    def clean(self):
        """
        Perform validation before saving to ensure data integrity.
        """
        if not self.church_id:
            return super().clean()

        # Unrestricted: clear restricted fields and set fund_key to 'U'
        if not self.is_restricted:
            self.restricted_source = None
            self.restricted_category_id = None
            self.fund_key = "U"
            return super().clean()

        # Restricted: require source and category ID
        if not self.restricted_source or not self.restricted_category_id:
            raise ValidationError("Restricted categories require restricted_source and restricted_category_id.")

        if int(self.restricted_category_id) <= 0:
            raise ValidationError("restricted_category_id must be a positive integer.")

        # Validate the linked restricted fund exists
        if self.restricted_source == "DONATION":
            DonationCategory = apps.get_model("Register", "DonationCategory")
            ok = DonationCategory.objects.filter(
                id=self.restricted_category_id,
                church_id=self.church_id,
                is_restricted=True
            ).exists()
            if not ok:
                raise ValidationError("Linked Donation fund not found / not restricted / wrong church.")
        else:
            OtherIncomeCategory = apps.get_model("Register", "OtherIncomeCategory")
            ok = OtherIncomeCategory.objects.filter(
                id=self.restricted_category_id,
                church_id=self.church_id,
                is_restricted=True
            ).exists()
            if not ok:
                raise ValidationError("Linked Other Income fund not found / not restricted / wrong church.")

        # Update the fund_key based on the restrictions
        self.fund_key = self.compute_fund_key()

        super().clean()

    def save(self, *args, **kwargs):
        """
        Ensure that fund_key is computed and valid before saving.
        """
        if self.is_restricted and self.restricted_source and self.restricted_category_id:
            self.fund_key = self.compute_fund_key()
        elif not self.is_restricted:
            self.fund_key = "U"

        self.full_clean()  # Always validate the model before saving
        super().save(*args, **kwargs)

    def __str__(self):
        # Display the category name and whether it's restricted
        if self.is_restricted:
            return f"{self.name} (Restricted: {self.fund_key})"
        return self.name


# ==========================================
# 2. UPDATED MODEL: Expense
# ==========================================
class Expense(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]

    # --- REPLACED FIELDS ---
    # We removed 'expense_type' and 'other_expense_type'
    # We added 'category' and 'description'

    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.PROTECT,  # Protects data: Cannot delete a category if it has expenses
        related_name='expenses',
        null=True,  # Allows migration of existing data
        blank=False
    )

    description = models.TextField(
        blank=True,
        null=True,
        help_text="Details about the expense (e.g. Invoice #, Specific items)"
    )

    # Vendor / Payee name for general expenses
    vendor = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Vendor or payee name for this expense (optional)."
    )

    # --- EXISTING FIELDS ---
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    expense_date = models.DateField(default=timezone.now)

    # Legacy file field
    file = models.FileField(upload_to='expenses/', null=True, blank=True)

    # Relationships
    church = models.ForeignKey(
        'Church.Church',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expenses'
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='expenses',
        null=True,
        blank=True
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_expenses'
    )

    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='edited_expenses'
    )

    # --- FRAUD PREVENTION ---
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='Pending')

    receipt_image = models.ImageField(
        upload_to='expense_receipts/',
        null=True,
        blank=True,
        help_text="Upload a clear photo of the Official Receipt."
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def clean(self):
        """
        Enforces a strictly 'Next Week Only' window based on the Lock Date.
        """
        if self.church and hasattr(self.church, 'accounting_settings'):
            lock_date = self.church.accounting_settings.lock_date

            if lock_date:
                # 1. PAST LOCK: Date must be AFTER the lock date
                if self.expense_date <= lock_date:
                    raise ValidationError(
                        f"PERIOD LOCKED: The books are closed up to {lock_date}. "
                        "You cannot add or edit records in this closed period."
                    )

                # 2. FUTURE WINDOW: Date must be within 7 DAYS of the lock date
                max_allowed_date = lock_date + timedelta(days=7)

                if self.expense_date > max_allowed_date:
                    raise ValidationError(
                        f"DATE BLOCKED: Based on your lock date ({lock_date}), "
                        f"you are currently only allowed to enter records from "
                        f"{lock_date + timedelta(days=1)} to {max_allowed_date}. "
                        f"The date {self.expense_date} is too far ahead."
                    )
            else:
                # Fallback if no lock date is set yet
                today = timezone.now().date()
                future_limit = today + timedelta(days=7)
                if self.expense_date > future_limit:
                    raise ValidationError(f"FUTURE DATE BLOCKED: You cannot enter dates past {future_limit}.")

        super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        cat_name = self.category.name if self.category else "Uncategorized"
        return f"{cat_name}: {self.amount} on {self.expense_date}"


class ExpenseAllocation(models.Model):
    FUND_TYPE_CHOICES = [
        ("UNRESTRICTED", "Unrestricted"),
        ("RESTRICTED", "Restricted"),
    ]
    RESTRICTED_SOURCE_CHOICES = [
        ("DONATION", "Donation Fund"),
        ("OTHER_INCOME", "Other Income Fund"),
    ]

    expense = models.ForeignKey(
        "Expense",
        on_delete=models.CASCADE,
        related_name="allocations"
    )

    church = models.ForeignKey(
        "Church.Church",
        on_delete=models.CASCADE,
        related_name="expense_allocations"
    )

    fund_type = models.CharField(max_length=12, choices=FUND_TYPE_CHOICES)

    # ✅ Stable identifier for joins/reporting and avoiding name collisions:
    # "U", "D:<id>", "I:<id>"
    fund_key = models.CharField(max_length=32, db_index=True)

    # Only used when fund_type == RESTRICTED
    restricted_source = models.CharField(
        max_length=20,
        choices=RESTRICTED_SOURCE_CHOICES,
        null=True,
        blank=True
    )
    restricted_category_id = models.BigIntegerField(null=True, blank=True)

    # Snapshot label for UI/audit (renames won’t break history)
    fund_name = models.CharField(max_length=150, default="Unrestricted")

    amount = models.DecimalField(max_digits=18, decimal_places=2)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_expense_allocations"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["church", "fund_key"]),
            models.Index(fields=["church", "fund_type"]),
            models.Index(fields=["expense"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["expense", "fund_key"], name="uniq_expense_fund_key")
        ]

    def clean(self):
        if self.amount is None or self.amount <= Decimal("0.00"):
            raise ValidationError("Allocation amount must be greater than 0.")

        if not self.church_id:
            raise ValidationError("Allocation church is required.")

        if self.expense_id and self.expense.church_id and self.church_id != self.expense.church_id:
            raise ValidationError("Allocation church must match expense church.")

        if self.fund_type == "UNRESTRICTED":
            # ✅ force-clean restricted fields
            self.restricted_source = None
            self.restricted_category_id = None
            self.fund_key = "U"
            if not self.fund_name:
                self.fund_name = "Unrestricted"

        elif self.fund_type == "RESTRICTED":
            if not self.restricted_source or not self.restricted_category_id:
                raise ValidationError("Restricted allocations require restricted_source and restricted_category_id.")
            if int(self.restricted_category_id) <= 0:
                raise ValidationError("restricted_category_id must be a positive integer.")

            prefix = "D" if self.restricted_source == "DONATION" else "I"
            self.fund_key = f"{prefix}:{int(self.restricted_category_id)}"

            if not self.fund_name or not self.fund_name.strip():
                raise ValidationError("fund_name is required for restricted allocations.")
        else:
            raise ValidationError("Invalid fund_type.")

        super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.fund_key} | {self.fund_name} | {self.amount}"

class TemporaryExpenseFile(models.Model):
    """
    Temporary storage for receipt files between 'Add' and 'Review' steps.
    Clean up old records via a cron job or Celery task.
    """
    file = models.FileField(upload_to='temp_receipts/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Temp File {self.id}"

class DonationCategory(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    # False = General Fund
    # True = Restricted Fund
    is_restricted = models.BooleanField(
        default=False,
        verbose_name="Restricted Fund?",
        help_text="Check this if money in this category is reserved for a specific purpose (e.g., Building Fund) and cannot be used for general expenses."
    )

    church = models.ForeignKey(
        'Church.Church',
        on_delete=models.CASCADE,
        related_name='donation_categories'
    )

    def __str__(self):
        status = "Restricted" if self.is_restricted else "General"
        return f"{self.name} ({status})"

    @property
    def current_balance(self):
        total_in = self.donations.aggregate(total=Sum('amount'))['total'] or 0

        expenses_rel = getattr(self, 'expenses', None)
        if expenses_rel:
            total_out = expenses_rel.aggregate(total=Sum('amount'))['total'] or 0
        else:
            total_out = 0

        return total_in - total_out

    class Meta:
        verbose_name_plural = "Donation Categories"
        unique_together = ('name', 'church')


class Donations(models.Model):
    class DonorType(models.TextChoices):
        MEMBER = "member", "Member"
        NON_MEMBER = "non_member", "Non-member"
        ANONYMOUS = "anonymous", "Anonymous"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="donations",
        null=True,
        blank=True,
        help_text="Used when donor type is Member."
    )

    donor_type = models.CharField(
        max_length=20,
        choices=DonorType.choices,
        default=DonorType.ANONYMOUS,
        help_text="Select whether the donor is a member, non-member, or anonymous."
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    donations_type = models.ForeignKey(
        DonationCategory,
        on_delete=models.PROTECT,
        related_name="donations"
    )

    donor = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Stores donor name for member and non-member donations."
    )

    other_donations_type = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    donations_date = models.DateField(default=timezone.now)

    church = models.ForeignKey(
        "Church.Church",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="donations"
    )

    # Uploads
    file = models.FileField(
        upload_to="donations/files/%Y/%m/",
        blank=True,
        null=True,
        help_text="Upload PDF or image proof/receipt."
    )

    receipt_image = models.ImageField(
        upload_to="donations/receipts/%Y/%m/",
        blank=True,
        null=True,
        help_text="Optional image version of the receipt."
    )

    # OCR
    ocr_text = models.TextField(
        blank=True,
        null=True,
        help_text="Extracted OCR text from uploaded receipt."
    )

    ocr_extracted_at = models.DateTimeField(
        blank=True,
        null=True
    )

    # Audit Trail
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_donations"
    )

    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edited_donations"
    )

    class Meta:
        ordering = ["-donations_date", "-id"]
        verbose_name = "Donation"
        verbose_name_plural = "Donations"

    def clean(self):
        super().clean()
        errors = {}

        if self.amount is not None and self.amount <= 0:
            errors["amount"] = "Amount must be greater than 0."

        donor_name = (self.donor or "").strip()

        # Donor type rules
        if self.donor_type == self.DonorType.MEMBER:
            if not self.user_id:
                errors["user"] = "Please select a member, pastor, or treasurer."
            else:
                if self.church_id:
                    user_church_id = getattr(self.user, "church_id", None)
                    if user_church_id != self.church_id:
                        errors["user"] = "Selected user must belong to the same church."

                allowed_types = {"Member", "Pastor", "Treasurer"}
                user_type = getattr(self.user, "user_type", None)
                if user_type and user_type not in allowed_types:
                    errors["user"] = "Only Member, Pastor, or Treasurer can be selected."

                full_name = ""
                if hasattr(self.user, "get_full_name"):
                    full_name = (self.user.get_full_name() or "").strip()

                self.donor = full_name or getattr(self.user, "username", "") or donor_name or "Member"

        elif self.donor_type == self.DonorType.NON_MEMBER:
            if not donor_name:
                errors["donor"] = "Please enter the non-member donor name."

            self.user = None
            self.donor = donor_name

        elif self.donor_type == self.DonorType.ANONYMOUS:
            self.user = None
            self.donor = None

        else:
            errors["donor_type"] = "Invalid donor type selected."

        # If category is "Other", require description
        if self.donations_type_id and "other" in self.donations_type.name.lower():
            if not (self.other_donations_type or "").strip():
                errors["other_donations_type"] = "Please specify the details for 'Other'."

        # Accounting lock validation
        if self.church and hasattr(self.church, "accounting_settings"):
            lock_date = self.church.accounting_settings.lock_date

            if lock_date:
                if self.donations_date <= lock_date:
                    errors["donations_date"] = (
                        f"PERIOD LOCKED: The books are closed up to {lock_date}. "
                        "You cannot add or edit records in this closed period."
                    )
                else:
                    max_allowed_date = lock_date + timedelta(days=7)
                    if self.donations_date > max_allowed_date:
                        errors["donations_date"] = (
                            f"DATE BLOCKED: Based on your lock date ({lock_date}), "
                            f"you are currently only allowed to enter records from "
                            f"{lock_date + timedelta(days=1)} to {max_allowed_date}. "
                            f"The date {self.donations_date} is too far ahead."
                        )
            else:
                today = timezone.localdate()
                future_limit = today + timedelta(days=7)
                if self.donations_date > future_limit:
                    errors["donations_date"] = (
                        f"FUTURE DATE BLOCKED: You cannot enter dates past {future_limit}."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def donor_display(self):
        if self.donor_type == self.DonorType.MEMBER:
            if self.donor:
                return self.donor

            if self.user:
                full_name = ""
                if hasattr(self.user, "get_full_name"):
                    full_name = (self.user.get_full_name() or "").strip()
                return full_name or getattr(self.user, "username", "Member")

            return "Member"

        if self.donor_type == self.DonorType.NON_MEMBER:
            return self.donor or "Non-member"

        return "Anonymous"

    def __str__(self):
        category_name = self.donations_type.name if self.donations_type_id else "Donation"
        return f"{category_name} - {self.amount} - {self.donor_display}"


class TemporaryDonationFile(models.Model):
    file = models.FileField(upload_to="temp/donations/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Temporary Donation File #{self.pk}"


class Fund(models.Model):
    """Campaign / Fund buckets that members can give to (e.g., General, Building, Missions)."""
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name






class AuditLog(models.Model):
    """
    Step 6: simple audit trail (who did what, when, payload).
    """
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=60)   # e.g., 'give.initiated', 'give.paid', 'email.sent'
    object_model = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=60, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Ministry(models.Model):
    # 1. Church Link (Multi-tenancy)
    church = models.ForeignKey(
        'Church.Church',
        on_delete=models.CASCADE,
        related_name='ministries',
        null=True,
        blank=True
    )

    # 2. Basic Info
    name = models.CharField(max_length=80)
    code = models.SlugField(max_length=50, help_text="Short identifier (e.g., mens, womens, youth)")
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    # --- NEW FIELD: ASSIGNED LEADER / REQUESTER ---
    assigned_requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_ministries",
        help_text="The user authorized to request budgets for this ministry."
    )

    # 3. Audit Trails
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="ministries_created"
    )
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="ministries_edited"
    )

    # ==================================================
    # 4. AI ANALYTICS & OPTIMIZATION PARAMETERS
    # ==================================================
    priority_score = models.IntegerField(
        default=5,
        help_text="1-10 Scale: Higher score means higher funding priority in AI optimization."
    )

    min_monthly_budget = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Hard constraint: The minimum amount this ministry REQUIRES to operate."
    )

    max_monthly_cap = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional constraint: The maximum amount this ministry can effectively use."
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=['church', 'name'], name='unique_ministry_name_per_church'),
            models.UniqueConstraint(fields=['church', 'code'], name='unique_ministry_code_per_church')
        ]

    def __str__(self):
        return f"{self.name} ({self.church.name if self.church else 'No Church'})"


MONTH_CHOICES = (
(0, 'Whole Year (Lump Sum)'),
    (1, "January"), (2, "February"), (3, "March"), (4, "April"),
    (5, "May"), (6, "June"), (7, "July"), (8, "August"),
    (9, "September"), (10, "October"), (11, "November"), (12, "December"),
)


# ==========================================
# 1. THE PLAN (MinistryBudget)
# ==========================================
class MinistryBudget(models.Model):
    YEARLY_MONTH = 0

    # Make sure MONTH_CHOICES includes 0 in your constants file
    # Example:
    # MONTH_CHOICES = [
    #     (0, "Yearly Pool"),
    #     (1, "January"),
    #     ...
    #     (12, "December"),
    # ]

    church = models.ForeignKey(
        'Church.Church', # Update this path if your Church model is located elsewhere
        on_delete=models.CASCADE,
        related_name='ministry_budgets',
        null=True,
        blank=True,
    )
    ministry = models.ForeignKey(
        "Ministry",
        on_delete=models.CASCADE,
        related_name="budgets",
    )

    year = models.PositiveIntegerField()

    # 0 = Yearly Pool, 1..12 = Monthly
    month = models.PositiveSmallIntegerField(
        # choices=MONTH_CHOICES, # Uncomment or import MONTH_CHOICES if defined in this file
        default=YEARLY_MONTH,
    )

    amount_allocated = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    is_active = models.BooleanField(
        default=True,
        help_text="If unchecked, no new funds can be released from this budget."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="budgets_created",
    )
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="budgets_edited",
    )

    class Meta:
        ordering = ["-year", "-month", "ministry__name"]
        indexes = [
            models.Index(fields=["church", "year", "month"]),
            models.Index(fields=["church", "ministry", "year"]),
            models.Index(fields=["church", "is_active"]),
        ]
        constraints = [
            # Only one yearly pool per church + ministry + year
            models.UniqueConstraint(
                fields=["church", "ministry", "year"],
                condition=Q(month=0),
                name="uniq_yearly_pool_church_ministry_year",
            ),

            # Only one monthly row per church + ministry + year + month
            models.UniqueConstraint(
                fields=["church", "ministry", "year", "month"],
                condition=Q(month__gte=1, month__lte=12),
                name="uniq_monthly_budget_church_ministry_year_month",
            ),

            # Month must be 0 or 1..12
            models.CheckConstraint(
                condition=Q(month=0) | (Q(month__gte=1) & Q(month__lte=12)),
                name="chk_budget_month_0_or_1_12",
            ),

            # Amount must not be negative
            models.CheckConstraint(
                condition=Q(amount_allocated__gte=0),
                name="chk_budget_amount_non_negative",
            ),
        ]

    def __str__(self):
        status = "" if self.is_active else " [CLOSED]"
        # If MONTH_CHOICES is imported, you can use dict(MONTH_CHOICES).get(...) here
        # month_name = dict(MONTH_CHOICES).get(self.month, str(self.month))
        month_name = str(self.month) if self.month != 0 else "Yearly Pool"
        return f"{self.ministry.name} — {month_name} {self.year}{status}"

    def clean(self):
        errors = {}

        # Auto-check ministry presence
        if not getattr(self, 'ministry_id', None):
            errors["ministry"] = "Ministry is required."

        # Auto-assign / validate church against ministry
        if getattr(self, 'ministry_id', None):
            ministry_church_id = self.ministry.church_id

            if not self.church_id:
                self.church_id = ministry_church_id
            elif self.church_id != ministry_church_id:
                errors["church"] = "Budget church must match the ministry's church."

        # Validate month
        if self.month not in range(0, 13):
            errors["month"] = "Month must be 0 (Yearly Pool) or 1 to 12."

        # Validate amount
        if self.amount_allocated is None:
            errors["amount_allocated"] = "Allocated amount is required."
        elif self.amount_allocated < 0:
            errors["amount_allocated"] = "Allocated amount cannot be negative."

        # Block mixing yearly + monthly for same church/ministry/year
        if self.church_id and getattr(self, 'ministry_id', None) and self.year:
            qs = MinistryBudget.objects.filter(
                church_id=self.church_id,
                ministry_id=self.ministry_id,
                year=self.year,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)

            if self.month == 0:
                # CREATE MODE ONLY: Cannot create yearly if monthly exists.
                # In edit mode, we bypass this so the View can safely delete the old monthly records.
                if not self.pk and qs.filter(month__gte=1, month__lte=12).exists():
                    errors["month"] = (
                        "Cannot use Yearly Pool because monthly budgets already exist "
                        "for this ministry and year."
                    )
            else:
                # CREATE MODE ONLY: Cannot create monthly if yearly exists.
                # In edit mode, we bypass this so the View can safely delete the old yearly record.
                if not self.pk and qs.filter(month=0).exists():
                    errors["month"] = (
                        "Cannot use a monthly budget because a Yearly Pool already exists "
                        "for this ministry and year."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.church_id and getattr(self, 'ministry_id', None):
            self.church = self.ministry.church
        super().save(*args, **kwargs)

    @property
    def is_yearly_pool(self) -> bool:
        return self.month == self.YEARLY_MONTH

    @property
    def is_monthly(self) -> bool:
        return 1 <= self.month <= 12

    @property
    def current_balance(self) -> Decimal:
        """Reads the live balance from the related BudgetBalance row."""
        if hasattr(self, "balance_account") and self.balance_account:
            return self.balance_account.current_amount or Decimal("0.00")
        return Decimal("0.00")

    @property
    def remaining_to_release(self) -> Decimal:
        return self.current_balance

    @property
    def total_released_gross(self) -> Decimal:
        return self.released_budgets.aggregate(
            s=Sum("amount")
        )["s"] or Decimal("0.00")

    @property
    def total_returned(self) -> Decimal:
        return self.released_budgets.aggregate(
            s=Sum("amount_returned")
        )["s"] or Decimal("0.00")

    @property
    def total_released_net(self) -> Decimal:
        return self.total_released_gross - self.total_returned

    @property
    def total_spent(self) -> Decimal:
        # Avoids an import loop if BudgetExpense is defined elsewhere
        from .models import BudgetExpense # Adjust this import to match your structure
        return (
            BudgetExpense.objects
            .filter(release__budget=self)
            .aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )

    @property
    def unliquidated(self) -> Decimal:
        val = self.total_released_gross - self.total_spent - self.total_returned
        return val if val > 0 else Decimal("0.00")

    @property
    def cash_on_hand(self) -> Decimal:
        return self.unliquidated

    @property
    def utilization_rate(self) -> Decimal:
        """
        Percentage of allocated budget that has been spent.
        """
        if not self.amount_allocated or self.amount_allocated <= 0:
            return Decimal("0.00")
        return (self.total_spent / self.amount_allocated) * Decimal("100.00")

# ==========================================
# 2. THE WALLET (BudgetBalance) - UPDATED
# ==========================================
class BudgetBalance(models.Model):
    """
    The 'Bank Account' for the budget.
    """
    # Direct Tracking Fields
    church = models.ForeignKey('Church.Church', on_delete=models.CASCADE, null=True, blank=True)
    ministry = models.ForeignKey("Ministry", on_delete=models.CASCADE, null=True, blank=True)

    budget = models.OneToOneField(
        MinistryBudget,
        on_delete=models.CASCADE,
        related_name="balance_account"
    )

    current_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        help_text="The live physical cash available for this budget."
    )

    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Wallet: ₱{self.current_amount} (for {self.budget})"

    def save(self, *args, **kwargs):
        # Auto-fill tracking info from parent Budget
        if self.budget:
            self.church = self.budget.church
            self.ministry = self.budget.ministry
        super().save(*args, **kwargs)


# ==========================================
# 3. REQUESTS & RELEASES
# ==========================================

class BudgetReleaseRequest(models.Model):
    # Direct Tracking Fields
    church = models.ForeignKey('Church.Church', on_delete=models.CASCADE, related_name='budget_release_requests',
                               null=True, blank=True)
    ministry = models.ForeignKey("Ministry", on_delete=models.CASCADE, null=True, blank=True)

    budget = models.ForeignKey("MinistryBudget", on_delete=models.CASCADE, related_name="release_requests")

    date_released = models.DateField(help_text="Date the funds are needed")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    remarks = models.CharField(max_length=255, blank=True)

    STATUS_CHOICES = [('Pending', 'Pending'), ('Approved', 'Approved'), ('Rejected', 'Rejected')]
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='Pending')

    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="requests_created")
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="requests_approved")
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at", "-id"]

    def __str__(self):
        return f"Request: {self.budget.ministry.name} — ₱{self.amount} ({self.status})"

    def save(self, *args, **kwargs):
        # Auto-fill from Budget
        if self.budget:
            self.church = self.budget.church
            self.ministry = self.budget.ministry
        super().save(*args, **kwargs)


class ApprovedReleaseRequest(models.Model):
    # Direct Tracking Fields
    church = models.ForeignKey('Church.Church', on_delete=models.CASCADE, related_name='approved_release_requests',
                               null=True, blank=True)
    ministry = models.ForeignKey("Ministry", on_delete=models.CASCADE, null=True, blank=True)

    budget = models.ForeignKey("MinistryBudget", on_delete=models.CASCADE, related_name="approved_release_requests")

    date_released = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    remarks = models.CharField(max_length=255, blank=True)

    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    approved_at = models.DateTimeField(auto_now_add=True)

    # Store the original request to link back
    approved_request = models.OneToOneField(
        BudgetReleaseRequest,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="approval_ticket"
    )

    class Meta:
        ordering = ["-approved_at", "-id"]

    def __str__(self):
        return f"Approved: {self.budget.ministry.name} — ₱{self.amount}"

    def save(self, *args, **kwargs):
        # Auto-fill from Budget
        if self.budget:
            self.church = self.budget.church
            self.ministry = self.budget.ministry
        super().save(*args, **kwargs)


class DeclinedReleaseRequest(models.Model):
    # ✅ Link to the exact request that got declined (best for tracking + audit)
    original_request = models.ForeignKey(
        "BudgetReleaseRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decline_records"
    )

    # ✅ Keep budget link (useful for reporting)
    budget = models.ForeignKey(
        "MinistryBudget",
        on_delete=models.SET_NULL,
        null=True,
        related_name="declined_release_requests"
    )

    # ✅ WHO requested it (so requester can track their declined requests)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="declined_budget_requests"
    )

    # Optional but useful: keep request timestamp (copied from original request)
    requested_at = models.DateTimeField(null=True, blank=True)

    date_released = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    remarks = models.CharField(max_length=255, blank=True)
    declined_reason = models.CharField(max_length=255, blank=True)

    declined_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="declined_by_records"
    )
    declined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-declined_at", "-id"]


class ReleasedBudget(models.Model):
    DEDUCT_CASH = "cash"
    DEDUCT_BANK = "bank"

    DEDUCT_FROM_CHOICES = [
        (DEDUCT_CASH, "Physical Cash"),
        (DEDUCT_BANK, "Bank"),
    ]

    church = models.ForeignKey(
        "Church.Church",
        on_delete=models.CASCADE,
        related_name="released_budgets",
        null=True,
        blank=True,
    )
    ministry = models.ForeignKey("Ministry", on_delete=models.CASCADE, null=True, blank=True)
    budget = models.ForeignKey("MinistryBudget", on_delete=models.CASCADE, related_name="released_budgets")

    approved_request = models.OneToOneField(
        "BudgetReleaseRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actual_release",
    )

    date_released = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    remarks = models.CharField(max_length=255, blank=True)

    # Source of released funds
    deduct_from = models.CharField(
        max_length=10,
        choices=DEDUCT_FROM_CHOICES,
        default=DEDUCT_CASH,
        help_text="Source of released funds: Physical Cash or Bank.",
    )

    # Where the excess/unspent amount is returned after liquidation
    return_to = models.CharField(
        max_length=10,
        choices=DEDUCT_FROM_CHOICES,
        default=DEDUCT_CASH,
        help_text="Where the unused amount is returned after liquidation.",
    )

    amount_returned = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Excess cash returned after liquidation.",
    )

    is_liquidated = models.BooleanField(default=False)
    liquidated_date = models.DateField(null=True, blank=True)

    # Single accounting entry for returned unused budget
    # This is always recorded as OtherIncome
    budget_return_income = models.OneToOneField(
        "OtherIncome",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_budget_return",
    )

    # Linked cash transaction when returned to physical cash
    cash_return_txn = models.OneToOneField(
        "CashTransaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_budget_return_cash",
    )

    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    released_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-released_at", "-id"]

    def __str__(self):
        status = " [Settled]" if self.is_liquidated else " [Unliquidated]"
        source = "Cash" if self.deduct_from == self.DEDUCT_CASH else "Bank"
        ministry_name = self.budget.ministry.name if self.budget and self.budget.ministry else "Ministry"
        return f"Released: {ministry_name} — ₱{self.amount} [{source}]{status}"

    @property
    def deduct_from_label(self):
        return dict(self.DEDUCT_FROM_CHOICES).get(self.deduct_from, self.deduct_from)

    @property
    def return_to_label(self):
        return dict(self.DEDUCT_FROM_CHOICES).get(self.return_to, self.return_to)

    def _get_lock_date(self):
        church = self.church or getattr(self.budget, "church", None)
        if church and hasattr(church, "accounting_settings") and church.accounting_settings:
            return church.accounting_settings.lock_date
        return None

    def _next_open_posting_date(self):
        """
        IMPORTANT:
        OtherIncome.clean() blocks date <= lock_date,
        so the valid posting date must be the NEXT OPEN DATE.
        """
        lock_date = self._get_lock_date()
        today = timezone.localdate()

        if lock_date and today <= lock_date:
            return lock_date + timedelta(days=1)

        return today

    @property
    def total_expenses(self):
        agg = self.expenses.aggregate(total=Sum("amount"))
        return agg["total"] or Decimal("0.00")

    @property
    def remaining_release_balance(self):
        val = (
            Decimal(self.amount or 0)
            - Decimal(self.total_expenses or 0)
            - Decimal(self.amount_returned or 0)
        )
        return val if val > 0 else Decimal("0.00")

    @property
    def remaining_cash_on_hand(self):
        return self.remaining_release_balance

    @property
    def remaining(self):
        return self.remaining_release_balance

    def clean(self):
        super().clean()

        if self.amount is not None and Decimal(self.amount) <= Decimal("0.00"):
            raise ValidationError({"amount": "Released amount must be greater than 0."})

        if self.amount_returned is not None and Decimal(self.amount_returned) < Decimal("0.00"):
            raise ValidationError({"amount_returned": "Returned amount cannot be negative."})

        if self.deduct_from not in {self.DEDUCT_CASH, self.DEDUCT_BANK}:
            raise ValidationError({"deduct_from": "Invalid release source."})

        if self.return_to not in {self.DEDUCT_CASH, self.DEDUCT_BANK}:
            raise ValidationError({"return_to": "Invalid return destination."})

        if self.amount is not None and self.amount_returned is not None:
            if Decimal(self.amount_returned) > Decimal(self.amount):
                raise ValidationError({
                    "amount_returned": "Returned amount cannot be greater than released amount."
                })

        if self.is_liquidated:
            lock_date = self._get_lock_date()
            if self.liquidated_date and lock_date and self.liquidated_date <= lock_date:
                raise ValidationError({
                    "liquidated_date": (
                        f"PERIOD LOCKED: Books are closed up to {lock_date}. "
                        f"You cannot liquidate using date {self.liquidated_date}. "
                        f"Use a date after {lock_date}."
                    )
                })

            spent = Decimal(self.total_expenses or 0)
            returned = Decimal(self.amount_returned or 0)
            released = Decimal(self.amount or 0)

            if spent + returned > released:
                raise ValidationError({
                    "__all__": (
                        f"Liquidation exceeds released amount. "
                        f"Released: ₱{released:,.2f}, "
                        f"Expenses: ₱{spent:,.2f}, "
                        f"Returned: ₱{returned:,.2f}."
                    )
                })

    def save(self, *args, **kwargs):
        if self.budget_id:
            self.church = self.budget.church
            self.ministry = self.budget.ministry

        if self.deduct_from not in {self.DEDUCT_CASH, self.DEDUCT_BANK}:
            self.deduct_from = self.DEDUCT_CASH

        if self.return_to not in {self.DEDUCT_CASH, self.DEDUCT_BANK}:
            self.return_to = self.DEDUCT_CASH

        if self.is_liquidated:
            next_open = self._next_open_posting_date()

            if not self.liquidated_date:
                self.liquidated_date = next_open
            else:
                lock_date = self._get_lock_date()
                if lock_date and self.liquidated_date <= lock_date:
                    self.liquidated_date = next_open

        self.full_clean()
        super().save(*args, **kwargs)

        # Returned unused budget is always restored as unrestricted OtherIncome.
        # Destination handling (bank/cash movement) belongs to the view/service layer.
        self._sync_budget_return_income()

    def _sync_budget_return_income(self):
        """
        Posts returned unused budget as unrestricted OtherIncome under 'Budget Return'.

        Rules:
        - If not liquidated -> remove linked OtherIncome
        - If returned amount <= 0 -> remove linked OtherIncome
        - If liquidated and returned amount > 0 -> create/update linked OtherIncome

        Destination handling:
        - return_to='bank' -> handled by CashBankMovement in view/service layer
        - return_to='cash' -> handled by CashTransaction in view/service layer
        """
        from Register.models import OtherIncome, OtherIncomeCategory

        with transaction.atomic():
            if not self.is_liquidated:
                if self.budget_return_income_id:
                    self.budget_return_income.delete()
                    self.budget_return_income = None
                    super().save(update_fields=["budget_return_income"])
                return

            returned = Decimal(self.amount_returned or 0)

            if returned <= 0:
                if self.budget_return_income_id:
                    self.budget_return_income.delete()
                    self.budget_return_income = None
                    super().save(update_fields=["budget_return_income"])
                return

            cat = OtherIncomeCategory.objects.filter(
                church_id=self.church_id,
                name__iexact="Budget Return",
            ).first()

            if not cat:
                cat = OtherIncomeCategory.objects.create(
                    church_id=self.church_id,
                    name="Budget Return",
                    description="System-generated category for returned unused budget.",
                    is_restricted=False,
                )
            elif cat.is_restricted:
                cat.is_restricted = False
                cat.save(update_fields=["is_restricted"])

            ministry_name = self.ministry.name if self.ministry else "Ministry"
            desc = f"Budget return from {ministry_name} | Release ID {self.id}"
            income_date = self.liquidated_date or self._next_open_posting_date()

            if self.budget_return_income_id:
                OtherIncome.objects.filter(id=self.budget_return_income_id).update(
                    amount=returned,
                    income_type=cat,
                    description=desc,
                    date=income_date,
                )
            else:
                oi = OtherIncome.objects.create(
                    church_id=self.church_id,
                    income_type=cat,
                    amount=returned,
                    description=desc,
                    date=income_date,
                )
                self.budget_return_income = oi
                super().save(update_fields=["budget_return_income"])

class BudgetExpense(models.Model):
    PAID_CASH = "cash"
    PAID_BANK = "bank"

    PAID_FROM_CHOICES = [
        (PAID_CASH, "Physical Cash"),
        (PAID_BANK, "Bank"),
    ]

    church = models.ForeignKey(
        "Church.Church",
        on_delete=models.CASCADE,
        related_name="budget_expenses",
        null=True,
        blank=True,
    )
    ministry = models.ForeignKey("Ministry", on_delete=models.CASCADE, null=True, blank=True)

    release = models.ForeignKey(
        "ReleasedBudget",
        on_delete=models.CASCADE,
        related_name="expenses",
        null=True,
        blank=True,
    )

    date_incurred = models.DateField()
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    # NEW: audit field only; does not deduct central ledgers again
    paid_from = models.CharField(
        max_length=10,
        choices=PAID_FROM_CHOICES,
        default=PAID_CASH,
        help_text="How this ministry expense was paid. For audit/reference only.",
    )

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    receipt_proof = models.FileField(
        upload_to="receipts/%Y/%m/",
        blank=True,
        null=True,
        help_text="Upload an image or PDF of the receipt.",
    )

    class Meta:
        ordering = ["-date_incurred", "-id"]

    def __str__(self):
        return f"{self.description} — ₱{self.amount}"

    @property
    def paid_from_label(self):
        return dict(self.PAID_FROM_CHOICES).get(self.paid_from, self.paid_from)

    def clean(self):
        super().clean()

        church = self.church
        if not church and self.release_id:
            church = getattr(self.release, "church", None)

        if not church:
            return

        lock_date = None
        if hasattr(church, "accounting_settings") and church.accounting_settings:
            lock_date = church.accounting_settings.lock_date

        if lock_date and self.date_incurred and self.date_incurred < lock_date:
            raise ValidationError({
                "__all__": [
                    f"PERIOD LOCKED: Books are closed before {lock_date}. "
                    f"You cannot add or edit entries dated {self.date_incurred}."
                ]
            })

        if self.amount is None or Decimal(self.amount) <= Decimal("0.00"):
            raise ValidationError({"amount": "Amount must be greater than 0."})

        if self.paid_from not in {self.PAID_CASH, self.PAID_BANK}:
            raise ValidationError({"paid_from": "Invalid payment source."})

        if not self.release_id:
            raise ValidationError({"release": "A budget expense must be linked to a released budget."})

        release_amount = Decimal(self.release.amount or 0)
        returned_amount = Decimal(self.release.amount_returned or 0)

        already_spent = self.release.expenses.exclude(pk=self.pk).aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0.00")

        available = release_amount - returned_amount - already_spent
        if available < Decimal("0.00"):
            available = Decimal("0.00")

        if Decimal(self.amount) > available:
            raise ValidationError({
                "amount": (
                    f"Expense exceeds available released balance. "
                    f"Available: ₱{available:,.2f}."
                )
            })

    def save(self, *args, **kwargs):
        if self.release_id:
            rel = self.release
            self.church = rel.church
            self.ministry = rel.ministry

        if self.paid_from not in {self.PAID_CASH, self.PAID_BANK}:
            self.paid_from = self.PAID_CASH

        self.full_clean()
        return super().save(*args, **kwargs)

class CashTransaction(models.Model):
    IN = "IN"
    OUT = "OUT"

    DIRECTION_CHOICES = [
        (IN, "Cash In"),
        (OUT, "Cash Out"),
    ]

    SOURCE_BUDGET_RETURN = "BUDGET_RETURN"

    church = models.ForeignKey(
        "Church.Church",
        on_delete=models.CASCADE,
        related_name="cash_transactions",
    )
    txn_date = models.DateField()
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES, default=IN)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    source_type = models.CharField(max_length=50, default=SOURCE_BUDGET_RETURN)
    description = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-txn_date", "-id"]

    def __str__(self):
        sign = "+" if self.direction == self.IN else "-"
        return f"{self.txn_date} | {sign}₱{self.amount} | {self.description}"

    def clean(self):
        super().clean()
        if self.amount is None or Decimal(self.amount) <= Decimal("0.00"):
            raise ValidationError({"amount": "Amount must be greater than 0."})


# ==========================================
# 4. AUTOMATION LOGIC (Signals) - UPDATED
# ==========================================

@receiver(post_save, sender=MinistryBudget)
def create_budget_balance(sender, instance, created, **kwargs):
    """
    When a NEW Budget Plan is created (e.g. 10k allocation),
    automatically open a 'Wallet' with that amount.
    """
    if created:
        BudgetBalance.objects.create(
            budget=instance,
            church=instance.church,  # <--- Added
            ministry=instance.ministry,  # <--- Added
            current_amount=instance.amount_allocated
        )


@receiver(post_save, sender=ReleasedBudget)
@receiver(post_delete, sender=ReleasedBudget)
def update_balance_on_transaction(sender, instance, **kwargs):
    """
    Triggers whenever money is RELEASED or RETURNED.
    Recalculates the BudgetBalance (Wallet).
    """
    # Safety check: if budget was deleted, skip
    if not instance.budget:
        return

    # 1. Get (or create if missing) the Balance Wallet
    balance_acct, _ = BudgetBalance.objects.get_or_create(
        budget=instance.budget,
        defaults={
            'church': instance.budget.church,
            'ministry': instance.budget.ministry
        }
    )

    # 2. Calculate Total Outflow
    total_released = instance.budget.released_budgets.aggregate(s=Sum('amount'))['s'] or Decimal(0)
    total_returned = instance.budget.released_budgets.aggregate(s=Sum('amount_returned'))['s'] or Decimal(0)

    net_used = total_released - total_returned

    # 3. Update the Wallet
    balance_acct.current_amount = instance.budget.amount_allocated - net_used

    # Force sync IDs just in case they were empty
    balance_acct.church = instance.budget.church
    balance_acct.ministry = instance.budget.ministry

    balance_acct.save()



class PendingReference(models.Model):
    reference_number = models.CharField(max_length=100)
    date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to='references/pending/', null=True, blank=True)

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pending_references'
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.reference_number} - {self.name} (PENDING)"


class ApprovedReference(models.Model):
    reference_number = models.CharField(max_length=100)
    date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to='references/approved/', null=True, blank=True)

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_references_submitted'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_references'
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.reference_number} - {self.name} (APPROVED)"


class ThankYouLetter(models.Model):
    reference = models.ForeignKey(ApprovedReference, on_delete=models.CASCADE)  # Reference linked to the letter
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,  # The user who submitted the reference
        on_delete=models.CASCADE,
        related_name='thank_you_letters_received'  # Unique reverse relationship for recipient
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,  # The sender of the letter (pastor)
        on_delete=models.SET_NULL,
        null=True,
        related_name='thank_you_letters_sent'  # Unique reverse relationship for sender
    )
    message = models.TextField()  # The content of the letter
    sent_at = models.DateTimeField(default=timezone.now)  # The time when the letter was sent

    def __str__(self):
        return f"Thank You Letter to {self.recipient.username} for {self.reference.reference_number} on {self.sent_at}"


from django.db import models
from django.core.exceptions import ValidationError


class HomePageContent(models.Model):
    # Church-owned homepage content
    church = models.OneToOneField(
        'Church.Church',
        on_delete=models.CASCADE,
        related_name='home_content',
        null=True,
        blank=True
    )

    # Denomination-owned homepage content
    denomination = models.OneToOneField(
        'Church.Denomination',
        on_delete=models.CASCADE,
        related_name='home_content',
        null=True,
        blank=True
    )

    title = models.CharField(
        max_length=200,
        default="Welcome to Church Financial Management System"
    )
    subtitle = models.TextField(default="Disciple making Disciples")
    hero_image = models.ImageField(upload_to='home_hero/', blank=True, null=True)

    def clean(self):
        has_church = bool(self.church_id)
        has_denomination = bool(self.denomination_id)

        if not has_church and not has_denomination:
            raise ValidationError(
                "Home page content must belong to either a church or a denomination."
            )

        if has_church and has_denomination:
            raise ValidationError(
                "Home page content cannot belong to both a church and a denomination."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.church:
            return f"Home Page for Church: {self.church.name}"
        if self.denomination:
            return f"Home Page for Denomination: {self.denomination.name}"
        return "Home Page Content"


class BankAccount(models.Model):
    church = models.OneToOneField(Church, on_delete=models.CASCADE, related_name='bank_account')

    # 1. Identity Information
    bank_name = models.CharField(max_length=100, default="Main Bank Account")
    # ADD THIS LINE:
    account_name = models.CharField(max_length=100, default="Church Account",
                                    help_text="e.g. Living Stone Church Main Fund")

    account_number = models.CharField(
        max_length=50,
        unique=True,
        help_text="Enter the official bank account number."
    )

    # 2. Money Information
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    # 3. Verification
    # Note: We don't store the setup image permanently here unless you want to.
    # Usually, we just use it for the one-time check or add a separate field.
    # For now, let's keep the balance verification image.
    verification_image = models.ImageField(
        upload_to='bank_verification/',
        help_text="Upload a screenshot or photo of the bank statement/balance."
    )

    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.bank_name} - {self.church.name}"


class AccountingSettings(models.Model):
    church = models.OneToOneField(
        "Church.Church",
        on_delete=models.CASCADE,
        related_name="accounting_settings"
    )

    lock_date = models.DateField(
        null=True,
        blank=True,
        help_text="Transactions before this date cannot be added or edited."
    )

    enable_expense_fraud_detection = models.BooleanField(
        default=False,
        help_text="Enable AI fraud detection for expense receipt uploads. Default is OFF."
    )

    enable_other_income_fraud_detection = models.BooleanField(
        default=False,
        help_text="Enable AI fraud detection for other income proof uploads. Default is OFF."
    )

    enable_donation_fraud_detection = models.BooleanField(
        default=False,
        help_text="Enable AI fraud detection for donation proof uploads. Default is OFF."
    )

    enable_tithe_fraud_detection = models.BooleanField(
        default=False,
        help_text="Enable AI fraud detection for tithe proof uploads. Default is OFF."
    )

    enable_offering_fraud_detection = models.BooleanField(
        default=False,
        help_text="Enable AI fraud detection for offering proof uploads. Default is OFF."
    )

    class Meta:
        verbose_name = "Accounting Setting"
        verbose_name_plural = "Accounting Settings"

    def __str__(self):
        return f"Settings for {self.church.name}"

    def is_locked(self, txn_date):
        """
        Returns True if the given transaction date is before the lock date.
        Equality is allowed:
        - txn_date < lock_date  -> blocked
        - txn_date == lock_date -> allowed
        """
        return bool(self.lock_date and txn_date and txn_date < self.lock_date)

    def fraud_detection_enabled_for(self, transaction_type):
        mapping = {
            "expense": self.enable_expense_fraud_detection,
            "other_income": self.enable_other_income_fraud_detection,
            "donation": self.enable_donation_fraud_detection,
            "tithe": self.enable_tithe_fraud_detection,
            "offering": self.enable_offering_fraud_detection,
        }
        return mapping.get(transaction_type, False)


class OtherIncomeCategory(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    # --- ADDED THIS FIELD ---
    is_restricted = models.BooleanField(
        default=False,
        help_text="Check if this income is restricted for specific use."
    )
    # ------------------------

    church = models.ForeignKey(
        'Church.Church',
        on_delete=models.CASCADE,
        related_name='other_income_categories'
    )

    class Meta:
        verbose_name_plural = "Other Income Categories"
        unique_together = ('name', 'church')

    def __str__(self):
        status = "(Restricted)" if self.is_restricted else ""
        return f"{self.name} {status}"


class TemporaryOtherIncomeFile(models.Model):
    """
    Temporary storage for uploaded files between 'Add' and 'Review' steps.
    Clean up old records via cron/Celery.
    """
    file = models.FileField(upload_to='temp_other_income/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Temp Other Income File {self.id}"


class OtherIncome(models.Model):
    church = models.ForeignKey(
        'Church.Church',
        on_delete=models.CASCADE,
        related_name='other_incomes'
    )

    income_type = models.ForeignKey(
        'OtherIncomeCategory',
        on_delete=models.PROTECT,
        related_name='entries'
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.now)

    description = models.CharField(max_length=255, blank=True, default="")

    # ✅ PERMANENT FILE FIELD (like Expense.file)
    file = models.FileField(upload_to='other_income/', null=True, blank=True)

    # ✅ OPTIONAL: if you want image-only receipts (like Expense.receipt_image)
    # Use this if your OCR pipeline expects images.
    receipt_image = models.ImageField(
        upload_to='other_income_receipts/',
        null=True,
        blank=True,
        help_text="Upload a clear photo of the receipt/supporting document."
    )

    # ✅ OCR STORAGE (so you can show extracted text later)
    ocr_text = models.TextField(blank=True, default="")
    ocr_processed_at = models.DateTimeField(null=True, blank=True)

    # Audit Fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_other_incomes'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='edited_other_incomes'
    )
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        """
        Validates the transaction date against the Church's accounting lock settings.
        Mirrors your logic style in Expense.clean().
        """
        try:
            current_church = self.church

            if hasattr(current_church, 'accounting_settings'):
                lock_date = current_church.accounting_settings.lock_date

                # 1) PAST LOCK: Date must be AFTER lock date
                if lock_date and self.date <= lock_date:
                    raise ValidationError(
                        f"PERIOD LOCKED: Books are closed up to {lock_date}. "
                        "You cannot add or edit entries before this date."
                    )

                # 2) FUTURE WINDOW: allow only within 7 days
                if lock_date:
                    future_limit = lock_date + timedelta(days=7)
                else:
                    future_limit = timezone.now().date() + timedelta(days=7)

                if self.date > future_limit:
                    raise ValidationError(
                        f"FUTURE DATE BLOCKED: You cannot enter dates past {future_limit}."
                    )

        except ObjectDoesNotExist:
            pass

        super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        type_name = self.income_type.name if self.income_type_id else "Unknown Type"
        return f"{type_name}: {self.amount} on {self.date}"


class CashBankMovement(models.Model):
    class Direction(models.TextChoices):
        CASH_TO_BANK = "CASH_TO_BANK", "Cash → Bank (Deposit)"
        BANK_TO_CASH = "BANK_TO_CASH", "Bank → Cash (Withdrawal)"
        BANK_TO_BANK = "BANK_TO_BANK", "Bank → Bank (Transfer)"

        DIRECT_BANK_RECEIPT = "DIRECT_BANK_RECEIPT", "Direct to Bank (Income)"
        BANK_PAID_EXPENSE = "BANK_PAID_EXPENSE", "Paid from Bank (Expense)"

    class SourceType(models.TextChoices):
        TITHE = "TITHE", "Tithe"
        OFFERING = "OFFERING", "Offering"
        DONATION = "DONATION", "Donation"
        OTHER_INCOME = "OTHER_INCOME", "Other Income"
        EXPENSE = "EXPENSE", "Expense"
        TRANSFER_ONLY = "TRANSFER_ONLY", "Transfer Only"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"

    # ✅ FIX: match your AccountingSettings example
    church = models.ForeignKey(
        "Church.Church",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="cash_bank_movements",
    )

    date = models.DateField(db_index=True)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    direction = models.CharField(max_length=32, choices=Direction.choices, db_index=True)
    source_type = models.CharField(max_length=24, choices=SourceType.choices, default=SourceType.TRANSFER_ONLY)

    # optional links to created source record
    source_id = models.BigIntegerField(null=True, blank=True)

    memo = models.CharField(max_length=255, blank=True, default="")
    reference_no = models.CharField(max_length=64, blank=True, default="")

    proof_file = models.FileField(
        upload_to="bank_movements/%Y/%m/",
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png"])
        ],
    )

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_bank_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["church", "date"]),
            models.Index(fields=["church", "direction", "date"]),
            models.Index(fields=["source_type", "source_id"]),
            models.Index(fields=["church", "status", "date"]),
        ]

    def clean(self):
        # lock-date enforcement (same behavior as your other modules)
        if self.church_id and hasattr(self.church, "accounting_settings") and self.church.accounting_settings:
            lock_date = self.church.accounting_settings.lock_date
            if lock_date and self.date and self.date <= lock_date:
                raise ValidationError(f"Transactions on or before {lock_date} are locked.")

        # enforce sensible combinations
        if self.direction in (self.Direction.CASH_TO_BANK, self.Direction.BANK_TO_CASH, self.Direction.BANK_TO_BANK):
            # pure transfers: should normally be TRANSFER_ONLY
            # (but you may allow TITHE/OFFERING/.. if you want, so keep this soft)
            pass

        if self.direction == self.Direction.DIRECT_BANK_RECEIPT and self.source_type == self.SourceType.TRANSFER_ONLY:
            raise ValidationError("Direct to Bank (Income) must be linked to a source type (Donation/Other Income/Tithe/Offering).")

        if self.direction == self.Direction.BANK_PAID_EXPENSE and self.source_type != self.SourceType.EXPENSE:
            raise ValidationError("Paid from Bank (Expense) must have source type = EXPENSE.")

        super().clean()

    def __str__(self):
        return f"{self.church_id} | {self.date} | {self.direction} | {self.amount}"

class TemporaryBankMovementFile(models.Model):
    file = models.FileField(upload_to="temp_bank_movements/%Y/%m/")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Temp Bank Movement File {self.id}"
