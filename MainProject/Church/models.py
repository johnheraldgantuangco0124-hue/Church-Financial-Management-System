from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class Denomination(models.Model):
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    contact_email = models.EmailField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.name


class Church(models.Model):
    name = models.CharField(max_length=150, unique=True)

    # Address Info
    province = models.CharField(max_length=100, blank=True, null=True)
    municipality_or_city = models.CharField(max_length=100, blank=True, null=True)
    barangay = models.CharField(max_length=100, blank=True, null=True)
    purok = models.CharField(max_length=100, blank=True, null=True)

    # Relationships
    denomination = models.ForeignKey(
        'Denomination',  # Using string to avoid circular imports if defined in same file
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='churches'
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)

    # --- FRAUD PREVENTION: MIGRATION & WEEKLY LOCK ---
    accounting_lock_date = models.DateField(
        null=True,
        blank=True,
        help_text="Transactions on or before this date are LOCKED (Cannot be added, edited, or deleted)."
    )

    def __str__(self):
        return self.name


class ChurchApplication(models.Model):
    STATUS = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Revoked', 'Revoked'),
    ]

    church = models.ForeignKey(
        'Church.Church',
        on_delete=models.CASCADE,
        related_name='applications'
    )
    denomination = models.ForeignKey(
        'Church.Denomination',
        on_delete=models.CASCADE,
        related_name='applications'
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS,
        default='Pending'
    )

    applied_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(blank=True, null=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='decided_church_applications'
    )

    revocation_reason = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-applied_at']
        verbose_name = 'Church Application'
        verbose_name_plural = 'Church Applications'

    def __str__(self):
        return f"{self.church.name} → {self.denomination.name} ({self.status})"

    def clean(self):
        if self.status == 'Revoked' and not self.revocation_reason:
            raise ValidationError({
                'revocation_reason': 'Revocation reason is required when the application is revoked.'
            })

        if self.status != 'Revoked' and self.revocation_reason:
            # Optional strict validation
            raise ValidationError({
                'revocation_reason': 'Revocation reason should only be set when the status is Revoked.'
            })

    def save(self, *args, **kwargs):
        if self.status != 'Revoked':
            self.revocation_reason = None
        super().save(*args, **kwargs)

    @transaction.atomic
    def approve(self, user):
        """
        Approves the application and links the church to the denomination.
        """
        self.status = 'Approved'
        self.revocation_reason = None
        self.decided_at = timezone.now()
        self.decided_by = user

        self.church.denomination = self.denomination
        self.church.save(update_fields=['denomination'])

        self.save()

    @transaction.atomic
    def reject(self, user):
        """
        Rejects the application. Church remains independent.
        """
        self.status = 'Rejected'
        self.revocation_reason = None
        self.decided_at = timezone.now()
        self.decided_by = user
        self.save()

    @transaction.atomic
    def revoke(self, user, reason):
        """
        Revokes the approved relationship and frees the church
        so it can apply to another denomination.
        """
        reason = (reason or '').strip()
        if not reason:
            raise ValidationError("Revocation reason is required.")

        self.status = 'Revoked'
        self.revocation_reason = reason
        self.decided_at = timezone.now()
        self.decided_by = user

        self.church.denomination = None
        self.church.save(update_fields=['denomination'])

        self.save()

    @property
    def is_pending(self):
        return self.status == 'Pending'

    @property
    def is_approved(self):
        return self.status == 'Approved'

    @property
    def is_rejected(self):
        return self.status == 'Rejected'

    @property
    def is_revoked(self):
        return self.status == 'Revoked'

class DenominationLiquidationAccessRequest(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CLOSED = "CLOSED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CLOSED, "Closed"),
    ]

    church = models.ForeignKey(
        "Church.Church",
        on_delete=models.CASCADE,
        related_name="denomination_liquidation_requests",
    )
    denomination_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="denomination_liquidation_requests",
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )

    requested_at = models.DateTimeField(auto_now_add=True)

    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_denomination_liquidation_requests",
    )
    remarks = models.TextField(blank=True, null=True)

    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_denomination_liquidation_requests",
    )
    close_remarks = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-requested_at"]
        verbose_name = "Denomination Liquidation Access Request"
        verbose_name_plural = "Denomination Liquidation Access Requests"

    def __str__(self):
        return f"{self.denomination_admin} -> {self.church} [{self.status}]"

    @property
    def can_view(self):
        return self.status == self.STATUS_APPROVED

    @property
    def is_closed(self):
        return self.status == self.STATUS_CLOSED

    def approve(self, reviewer, remarks=""):
        self.status = self.STATUS_APPROVED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.remarks = remarks
        self.closed_by = None
        self.closed_at = None
        self.close_remarks = ""
        self.save(update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "remarks",
            "closed_by",
            "closed_at",
            "close_remarks",
        ])

    def reject(self, reviewer, remarks=""):
        self.status = self.STATUS_REJECTED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.remarks = remarks
        self.save(update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "remarks",
        ])

    def close_access(self, closed_by_user, remarks=""):
        self.status = self.STATUS_CLOSED
        self.closed_by = closed_by_user
        self.closed_at = timezone.now()
        self.close_remarks = remarks
        self.save(update_fields=[
            "status",
            "closed_by",
            "closed_at",
            "close_remarks",
        ])