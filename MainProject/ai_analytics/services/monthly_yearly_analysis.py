from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone


ZERO = Decimal("0.00")


def _resolve_model(model_name: str):
    """
    Resolve models lazily so Django won't crash during import
    if the first candidate app label is wrong.
    """
    candidates = {
        "MinistryBudget": [
            ("Register", "MinistryBudget"),
            ("Church", "MinistryBudget"),
            ("Process", "MinistryBudget"),
        ],
        "ReleasedBudget": [
            ("Register", "ReleasedBudget"),
            ("Church", "ReleasedBudget"),
            ("Process", "ReleasedBudget"),
        ],
        "BudgetExpense": [
            ("Register", "BudgetExpense"),
            ("Church", "BudgetExpense"),
            ("Process", "BudgetExpense"),
        ],
    }

    for app_label, class_name in candidates.get(model_name, []):
        try:
            return apps.get_model(app_label, class_name)
        except LookupError:
            continue

    tried = ", ".join([f"{a}.{m}" for a, m in candidates.get(model_name, [])])
    raise ImproperlyConfigured(
        f"Could not resolve model '{model_name}'. Tried: {tried}"
    )


def _get_models():
    MinistryBudget = _resolve_model("MinistryBudget")
    ReleasedBudget = _resolve_model("ReleasedBudget")
    BudgetExpense = _resolve_model("BudgetExpense")
    return MinistryBudget, ReleasedBudget, BudgetExpense


@dataclass
class MinistryAnalysisBucket:
    ministry_id: int
    ministry_name: str

    allocated_total: Decimal = field(default_factory=lambda: ZERO)
    released_total: Decimal = field(default_factory=lambda: ZERO)
    returned_total: Decimal = field(default_factory=lambda: ZERO)
    spent_total: Decimal = field(default_factory=lambda: ZERO)
    unliquidated_total: Decimal = field(default_factory=lambda: ZERO)
    available_total: Decimal = field(default_factory=lambda: ZERO)
    unreleased_total: Decimal = field(default_factory=lambda: ZERO)

    yearly_pool_amount: Decimal = field(default_factory=lambda: ZERO)
    monthly_budget_total: Decimal = field(default_factory=lambda: ZERO)

    monthly_allocated: dict[int, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    monthly_released: dict[int, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    monthly_returned: dict[int, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    monthly_spent: dict[int, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))

    category_totals: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    detected_categories: bool = False

    structure_type: str = "Unknown"


def _d(value: Any) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalize_month(month) -> int | None:
    try:
        month = int(month)
    except (TypeError, ValueError):
        return None
    return month if month in range(1, 13) else None


def _month_label(month_no: int) -> str:
    if month_no in range(1, 13):
        return calendar.month_name[month_no]
    return f"Month {month_no}"


def _elapsed_months_for_year(year: int) -> int:
    today = timezone.localdate()

    if year < today.year:
        return 12
    if year == today.year:
        return today.month
    return 0


def _safe_pct(part: Decimal, total: Decimal) -> Decimal:
    if total <= 0:
        return ZERO
    return (part / total) * Decimal("100")


def _pick_category_name(expense: Any) -> str:
    candidate_attrs = [
        "expense_category",
        "category",
        "expense_type",
    ]

    for attr in candidate_attrs:
        obj = getattr(expense, attr, None)
        if obj:
            return getattr(obj, "name", str(obj))

    return "Uncategorized"


def _month_from_date_or_fallback(obj: Any, date_attr: str, fallback: int | None = None) -> int | None:
    dt = getattr(obj, date_attr, None)
    if dt:
        return dt.month
    return fallback


def _build_month_series(source_map: dict[int, Decimal], selected_month: int | None = None) -> list[dict[str, Any]]:
    months = [selected_month] if selected_month in range(1, 13) else range(1, 13)
    return [
        {
            "month_no": m,
            "month": calendar.month_name[m],
            "amount": source_map.get(m, ZERO),
        }
        for m in months
    ]


def _top_month(source_map: dict[int, Decimal]) -> dict[str, Any] | None:
    best_month = None
    best_amount = ZERO

    for m in range(1, 13):
        amt = source_map.get(m, ZERO)
        if amt > best_amount:
            best_amount = amt
            best_month = m

    if best_month is None or best_amount <= 0:
        return None

    return {
        "month_no": best_month,
        "month": calendar.month_name[best_month],
        "amount": best_amount,
    }


def _lowest_nonzero_month(source_map: dict[int, Decimal]) -> dict[str, Any] | None:
    nonzero = [(m, amt) for m, amt in source_map.items() if amt > 0]
    if not nonzero:
        return None

    best_month, amount = min(nonzero, key=lambda x: x[1])
    return {
        "month_no": best_month,
        "month": calendar.month_name[best_month],
        "amount": amount,
    }


def _bucket_to_dict(bucket: MinistryAnalysisBucket, year: int, selected_month: int | None = None) -> dict[str, Any]:
    elapsed_months = 1 if selected_month in range(1, 13) else _elapsed_months_for_year(year)

    burn_rate_monthly_avg = (
        bucket.spent_total / Decimal(str(elapsed_months))
        if elapsed_months > 0 else ZERO
    )

    projected_year_end_spend = burn_rate_monthly_avg * Decimal("12")

    bucket.unreleased_total = bucket.allocated_total - bucket.released_total
    bucket.available_total = bucket.allocated_total - bucket.spent_total

    if bucket.unreleased_total < 0:
        bucket.unreleased_total = ZERO

    if bucket.available_total < 0:
        bucket.available_total = ZERO

    top_spending = _top_month(bucket.monthly_spent)
    lowest_nonzero = _lowest_nonzero_month(bucket.monthly_spent)

    category_mix = []
    total_for_mix = sum(bucket.category_totals.values(), ZERO)
    if bucket.detected_categories or total_for_mix > 0:
        for category_name, amount in sorted(
            bucket.category_totals.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            category_mix.append({
                "category": category_name,
                "amount": amount,
                "percent": _safe_pct(amount, bucket.spent_total).quantize(Decimal("0.01")),
            })

    if bucket.yearly_pool_amount > 0 and bucket.monthly_budget_total > 0:
        structure_type = "Mixed"
    elif bucket.yearly_pool_amount > 0:
        structure_type = "Yearly Pool"
    elif bucket.monthly_budget_total > 0:
        structure_type = "Monthly"
    else:
        structure_type = bucket.structure_type or "Unknown"

    return {
        "ministry_id": bucket.ministry_id,
        "ministry_name": bucket.ministry_name,
        "year": year,
        "selected_month": selected_month,
        "structure_type": structure_type,

        "allocated_total": bucket.allocated_total,
        "released_total": bucket.released_total,
        "returned_total": bucket.returned_total,
        "spent_total": bucket.spent_total,
        "unliquidated_total": bucket.unliquidated_total,
        "available_total": bucket.available_total,
        "unreleased_total": bucket.unreleased_total,

        "yearly_pool_amount": bucket.yearly_pool_amount,
        "monthly_budget_total": bucket.monthly_budget_total,

        "utilization_pct": _safe_pct(bucket.spent_total, bucket.allocated_total).quantize(Decimal("0.01")),
        "release_utilization_pct": _safe_pct(bucket.spent_total, bucket.released_total).quantize(Decimal("0.01")),

        "elapsed_months_basis": elapsed_months,
        "burn_rate_monthly_avg": burn_rate_monthly_avg.quantize(Decimal("0.01")),
        "projected_year_end_spend": projected_year_end_spend.quantize(Decimal("0.01")),

        "highest_spending_month": top_spending,
        "lowest_nonzero_spending_month": lowest_nonzero,

        "monthly_allocated_series": _build_month_series(bucket.monthly_allocated, selected_month),
        "monthly_released_series": _build_month_series(bucket.monthly_released, selected_month),
        "monthly_returned_series": _build_month_series(bucket.monthly_returned, selected_month),
        "monthly_spent_series": _build_month_series(bucket.monthly_spent, selected_month),

        "category_mix": category_mix,
        "has_category_data": bucket.detected_categories or total_for_mix > 0,
    }


def get_ministry_monthly_yearly_analysis(church, year: int, month: int | None = None) -> list[dict[str, Any]]:
    MinistryBudget, ReleasedBudget, BudgetExpense = _get_models()
    selected_month = _normalize_month(month)

    budgets = (
        MinistryBudget.objects
        .filter(church=church, year=year)
        .select_related("ministry")
        .prefetch_related("released_budgets", "released_budgets__expenses")
        .order_by("ministry__name", "month", "id")
    )

    # Monthly scope:
    # include the selected monthly budget plus yearly pool (month=0)
    if selected_month:
        budgets = budgets.filter(month__in=[selected_month, 0])

    grouped: dict[int, MinistryAnalysisBucket] = {}

    for budget in budgets:
        ministry = getattr(budget, "ministry", None)
        if ministry is None:
            continue

        ministry_id = ministry.id

        if ministry_id not in grouped:
            grouped[ministry_id] = MinistryAnalysisBucket(
                ministry_id=ministry_id,
                ministry_name=getattr(ministry, "name", f"Ministry {ministry_id}"),
            )

        bucket = grouped[ministry_id]

        allocated_amount = _d(getattr(budget, "amount_allocated", ZERO))
        budget_month = getattr(budget, "month", 0) or 0

        # Allocation handling
        if selected_month is None:
            bucket.allocated_total += allocated_amount

            if budget_month == 0:
                bucket.yearly_pool_amount += allocated_amount
                bucket.structure_type = "Yearly Pool"
            else:
                bucket.monthly_budget_total += allocated_amount
                bucket.monthly_allocated[budget_month] += allocated_amount
                bucket.structure_type = "Monthly"
        else:
            if budget_month == 0:
                bucket.allocated_total += allocated_amount
                bucket.yearly_pool_amount += allocated_amount
                bucket.structure_type = "Yearly Pool"
            elif budget_month == selected_month:
                bucket.allocated_total += allocated_amount
                bucket.monthly_budget_total += allocated_amount
                bucket.monthly_allocated[selected_month] += allocated_amount
                bucket.structure_type = "Monthly"

        released_items = list(budget.released_budgets.all())

        for release in released_items:
            release_amount = _d(getattr(release, "amount", ZERO))
            returned_amount = _d(getattr(release, "amount_returned", ZERO))

            release_month = _month_from_date_or_fallback(
                release,
                "date_released",
                fallback=(budget_month if budget_month in range(1, 13) else None),
            )

            return_month = _month_from_date_or_fallback(
                release,
                "liquidated_date",
                fallback=release_month,
            )

            # Released totals
            if selected_month is None:
                bucket.released_total += release_amount
                if release_month in range(1, 13):
                    bucket.monthly_released[release_month] += release_amount
            else:
                if release_month == selected_month:
                    bucket.released_total += release_amount
                    bucket.monthly_released[selected_month] += release_amount

            # Returned totals
            if selected_month is None:
                bucket.returned_total += returned_amount
                if return_month in range(1, 13) and returned_amount > 0:
                    bucket.monthly_returned[return_month] += returned_amount
            else:
                if return_month == selected_month and returned_amount > 0:
                    bucket.returned_total += returned_amount
                    bucket.monthly_returned[selected_month] += returned_amount

            release_spent_scope = ZERO
            release_spent_all = ZERO

            release_expenses = list(release.expenses.all())

            for expense in release_expenses:
                expense_amount = _d(getattr(expense, "amount", ZERO))
                expense_month = _month_from_date_or_fallback(
                    expense,
                    "date_incurred",
                    fallback=release_month,
                )

                # track full release spending for yearly mode
                release_spent_all += expense_amount

                if selected_month is None:
                    release_spent_scope += expense_amount
                    bucket.spent_total += expense_amount
                    if expense_month in range(1, 13):
                        bucket.monthly_spent[expense_month] += expense_amount
                else:
                    if expense_month == selected_month:
                        release_spent_scope += expense_amount
                        bucket.spent_total += expense_amount
                        bucket.monthly_spent[selected_month] += expense_amount

                category_name = _pick_category_name(expense)
                if category_name != "Uncategorized":
                    bucket.detected_categories = True

                if selected_month is None or expense_month == selected_month:
                    bucket.category_totals[category_name] += expense_amount

            # Unliquidated
            if selected_month is None:
                current_unliquidated = release_amount - release_spent_all - returned_amount
                if current_unliquidated > 0:
                    bucket.unliquidated_total += current_unliquidated
            else:
                current_unliquidated = ZERO

                if release_month == selected_month:
                    current_unliquidated = release_amount - release_spent_scope
                    if return_month == selected_month:
                        current_unliquidated -= returned_amount

                if current_unliquidated > 0:
                    bucket.unliquidated_total += current_unliquidated

    results = [_bucket_to_dict(bucket, year, selected_month) for bucket in grouped.values()]
    results.sort(key=lambda item: item["ministry_name"].lower())
    return results


def get_monthly_yearly_dashboard_summary(church, year: int, month: int | None = None) -> dict[str, Any]:
    selected_month = _normalize_month(month)
    ministry_rows = get_ministry_monthly_yearly_analysis(church, year, selected_month)

    summary = {
        "year": year,
        "selected_month": selected_month,
        "ministry_count": len(ministry_rows),
        "allocated_total": ZERO,
        "released_total": ZERO,
        "returned_total": ZERO,
        "spent_total": ZERO,
        "unliquidated_total": ZERO,
        "available_total": ZERO,
        "unreleased_total": ZERO,
        "monthly_spent_series": [],
        "ministries": ministry_rows,
    }

    monthly_spent_totals = defaultdict(lambda: ZERO)

    for row in ministry_rows:
        summary["allocated_total"] += row["allocated_total"]
        summary["released_total"] += row["released_total"]
        summary["returned_total"] += row["returned_total"]
        summary["spent_total"] += row["spent_total"]
        summary["unliquidated_total"] += row["unliquidated_total"]
        summary["available_total"] += row["available_total"]
        summary["unreleased_total"] += row["unreleased_total"]

        for item in row["monthly_spent_series"]:
            monthly_spent_totals[item["month_no"]] += _d(item["amount"])

    if selected_month is None:
        summary["monthly_spent_series"] = [
            {
                "month_no": m,
                "month": _month_label(m),
                "amount": monthly_spent_totals[m],
            }
            for m in range(1, 13)
        ]
        elapsed_months = _elapsed_months_for_year(year)
    else:
        summary["monthly_spent_series"] = [
            {
                "month_no": selected_month,
                "month": _month_label(selected_month),
                "amount": monthly_spent_totals[selected_month],
            }
        ]
        elapsed_months = 1

    summary["utilization_pct"] = _safe_pct(
        summary["spent_total"],
        summary["allocated_total"],
    ).quantize(Decimal("0.01"))

    summary["burn_rate_monthly_avg"] = (
        (summary["spent_total"] / Decimal(str(elapsed_months))).quantize(Decimal("0.01"))
        if elapsed_months > 0 else ZERO
    )

    summary["projected_year_end_spend"] = (
        summary["burn_rate_monthly_avg"] * Decimal("12")
    ).quantize(Decimal("0.01"))

    return summary