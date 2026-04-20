from decimal import Decimal

from django.db import IntegrityError
from django.db.models import Sum
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import (
    MinistryBudget,
    BudgetBalance,
    ReleasedBudget,
    DonationCategory,
    OtherIncomeCategory,
    ExpenseCategory,
)

# ==========================================
# 1) BUDGET & BALANCE (unchanged behavior)
# ==========================================

@receiver(post_save, sender=MinistryBudget)
def create_budget_balance(sender, instance, created, **kwargs):
    """
    Ensures a BudgetBalance exists for a budget.
    If budget is updated, recompute wallet balance.
    """
    balance_acct, newly_created = BudgetBalance.objects.get_or_create(
        budget=instance,
        defaults={'current_amount': instance.amount_allocated}
    )

    if not newly_created:
        total_released = instance.released_budgets.aggregate(s=Sum('amount'))['s'] or Decimal("0.00")
        total_returned = instance.released_budgets.aggregate(s=Sum('amount_returned'))['s'] or Decimal("0.00")
        net_used = total_released - total_returned

        balance_acct.current_amount = (instance.amount_allocated or Decimal("0.00")) - net_used
        balance_acct.save()


@receiver(post_save, sender=ReleasedBudget)
@receiver(post_delete, sender=ReleasedBudget)
def update_balance_on_release(sender, instance, **kwargs):
    """
    Recalculates BudgetBalance whenever money is released/returned or release record is deleted.
    """
    budget = instance.budget

    balance_acct, _ = BudgetBalance.objects.get_or_create(
        budget=budget,
        defaults={'current_amount': budget.amount_allocated}
    )

    total_released = budget.released_budgets.aggregate(s=Sum('amount'))['s'] or Decimal("0.00")
    total_returned = budget.released_budgets.aggregate(s=Sum('amount_returned'))['s'] or Decimal("0.00")
    net_used = total_released - total_returned

    balance_acct.current_amount = (budget.amount_allocated or Decimal("0.00")) - net_used
    balance_acct.save()


# ==========================================
# 2) RESTRICTED FUNDS AUTO-SYNC (correct)
# ==========================================

def _make_unique_name(church, base_name: str, suffix: str) -> str:
    """
    Ensures name uniqueness within a church.
    Used when a restricted fund name collides with an existing category name.
    """
    name = (base_name or "").strip()
    if not name:
        name = "Restricted Fund"

    if not ExpenseCategory.objects.filter(church=church, name__iexact=name).exists():
        return name

    candidate = f"{name} ({suffix})"
    if not ExpenseCategory.objects.filter(church=church, name__iexact=candidate).exists():
        return candidate

    i = 2
    while True:
        candidate = f"{name} ({suffix} {i})"
        if not ExpenseCategory.objects.filter(church=church, name__iexact=candidate).exists():
            return candidate
        i += 1


def _sync_restricted_fund_to_expense_category(*, church, fund_name, source, fund_id, is_restricted_flag: bool):
    """
    Keeps ExpenseCategory consistent with restricted flags in DonationCategory/OtherIncomeCategory.

    - If restricted=True:
        Ensure an ExpenseCategory exists that is linked to (source, fund_id),
        and is_restricted=True with correct mapping.

    - If restricted=False:
        Revert ONLY the ExpenseCategory that is currently linked to (source, fund_id).
        (Does not touch manual categories.)
    """

    fund_name = (fund_name or "").strip()
    fund_id = int(fund_id)

    # 1) Find by explicit mapping first (safe across renames)
    ec = ExpenseCategory.objects.filter(
        church=church,
        restricted_source=source,
        restricted_category_id=fund_id
    ).first()

    # 2) If not found: try to reuse same-name UNRESTRICTED category
    #    (this handles your "Wedding exists but should become restricted")
    if not ec and fund_name:
        candidate = ExpenseCategory.objects.filter(church=church, name__iexact=fund_name).first()
        if candidate:
            # Convert ONLY if candidate is currently unrestricted (or has no mapping)
            if (not candidate.is_restricted) or (candidate.restricted_source is None and candidate.restricted_category_id is None):
                ec = candidate

    if is_restricted_flag:
        # Must ensure category exists
        if not ec:
            suffix = "Donation Fund" if source == "DONATION" else "Other Income Fund"
            safe_name = _make_unique_name(church, fund_name, suffix)
            ec = ExpenseCategory(church=church, name=safe_name)

        # If the chosen ec is already restricted for a DIFFERENT fund, do NOT overwrite it
        if ec.is_restricted and (
            ec.restricted_source != source or int(ec.restricted_category_id or 0) != fund_id
        ):
            suffix = "Donation Fund" if source == "DONATION" else "Other Income Fund"
            safe_name = _make_unique_name(church, fund_name, suffix)
            ec = ExpenseCategory(church=church, name=safe_name)

        # Apply mapping
        ec.is_restricted = True
        ec.restricted_source = source
        ec.restricted_category_id = fund_id

        # IMPORTANT: keep is_system=False because your SP excludes system categories
        ec.is_system = False
        ec.is_transfer = False

        # Keep the display name aligned if it doesn't break uniqueness
        # (if we created a safe_name, we keep it; if converted by name, it stays same)
        if ec.name.lower() == fund_name.lower():
            ec.name = fund_name

        # Description markers used by your Unrestricted SP to exclude restricted spending
        if source == "DONATION":
            ec.description = f"Auto-generated restricted fund from Donation: {fund_name}"
        else:
            ec.description = f"Auto-generated restricted fund from Other Income: {fund_name}"

        try:
            ec.save()
        except IntegrityError:
            # If unique_together(name, church) blocks rename collisions, create a unique alternative
            suffix = "Donation Fund" if source == "DONATION" else "Other Income Fund"
            safe_name = _make_unique_name(church, fund_name, suffix)
            ExpenseCategory.objects.update_or_create(
                church=church,
                restricted_source=source,
                restricted_category_id=fund_id,
                defaults={
                    "name": safe_name,
                    "description": ec.description,
                    "is_restricted": True,
                    "is_system": False,
                    "is_transfer": False,
                }
            )

    else:
        # Fund became UNRESTRICTED: only revert the explicitly linked one
        if ec and ec.restricted_source == source and int(ec.restricted_category_id or 0) == fund_id:
            ec.is_restricted = False
            ec.restricted_source = None
            ec.restricted_category_id = None

            # keep it as a normal editable category
            ec.is_system = False
            ec.is_transfer = False

            # Optional note
            if ec.description and "Auto-generated restricted fund" in ec.description:
                ec.description = (ec.description + " (Now unrestricted)")[:1000]

            ec.save()


@receiver(post_save, sender=DonationCategory)
def sync_donation_to_expense(sender, instance, **kwargs):
    _sync_restricted_fund_to_expense_category(
        church=instance.church,
        fund_name=instance.name,
        source="DONATION",
        fund_id=instance.id,
        is_restricted_flag=bool(instance.is_restricted),
    )


@receiver(post_save, sender=OtherIncomeCategory)
def sync_other_income_to_expense(sender, instance, **kwargs):
    _sync_restricted_fund_to_expense_category(
        church=instance.church,
        fund_name=instance.name,
        source="OTHER_INCOME",
        fund_id=instance.id,
        is_restricted_flag=bool(instance.is_restricted),
    )