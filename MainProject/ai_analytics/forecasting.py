from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.apps import apps
from django.db import connection
from django.db.models import Sum, DecimalField, Q,Exists, OuterRef
from django.db.models.functions import Coalesce
from django.utils import timezone


def get_model_safe(model_name):
    """Load models dynamically to avoid circular imports."""
    try:
        return apps.get_model("Register", model_name)
    except LookupError:
        return None


def _to_decimal(val, default="0.00") -> Decimal:
    try:
        if val is None or val == "":
            return Decimal(default)
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


# ==========================================
# 1. CURRENT CASH / FUND BALANCE HELPERS
# ==========================================
def _get_total_cash(church_id: int) -> Decimal:
    """
    Uses SP: Calculate_CashOnHand(church_id)
    Returns current total cash on hand (restricted + unrestricted).
    """
    try:
        with connection.cursor() as cursor:
            cursor.callproc("Calculate_CashOnHand", [church_id])
            row = cursor.fetchone()
        return _to_decimal(row[0] if row and row[0] is not None else "0.00")
    except Exception:
        return Decimal("0.00")


def _get_unrestricted_net_now(church_id: int) -> Decimal:
    """
    Uses SP: Finance_UnrestrictedNet(church_id)

    Expected row shape:
      0 TotalTithes
      1 TotalOfferings
      2 TotalUnrestrictedDonations
      3 TotalUnrestrictedOtherIncome
      4 TotalBudgetReturnsToUnrestricted
      5 GrandTotalUnrestricted
      6 TotalUnrestrictedExpenses
      7 NetGrandTotalUnrestricted
      8 TotalRealExpensesAll
      9 TotalRestrictedExpenses
    """
    try:
        with connection.cursor() as cursor:
            cursor.callproc("Finance_UnrestrictedNet", [church_id])
            row = cursor.fetchone()
        return _to_decimal(row[7] if row and len(row) > 7 else "0.00")
    except Exception:
        return Decimal("0.00")


def _get_restricted_balance_now(church_id: int) -> Decimal:
    """
    Uses SP: Finance_RestrictedBalanceNow(church_id)

    Expected row shape:
      0 TotalRestrictedDonations
      1 TotalRestrictedOtherIncome
      2 TotalRestrictedExpenses
      3 RestrictedBalanceOutstanding
    """
    try:
        with connection.cursor() as cursor:
            cursor.callproc("Finance_RestrictedBalanceNow", [church_id])
            row = cursor.fetchone()
        return _to_decimal(row[3] if row and len(row) > 3 else "0.00")
    except Exception:
        return Decimal("0.00")


def get_current_fund_balances(church_id: int):
    """
    Manual optimizer source:
      - total cash on hand
      - restricted funds held (direct from Finance_RestrictedBalanceNow)
      - unrestricted cash available (direct from Finance_UnrestrictedNet)
    """
    total_cash = _get_total_cash(church_id)
    restricted_balance = _get_restricted_balance_now(church_id)
    unrestricted_cash = _get_unrestricted_net_now(church_id)

    if total_cash < 0:
        total_cash = Decimal("0.00")
    if restricted_balance < 0:
        restricted_balance = Decimal("0.00")
    if unrestricted_cash < 0:
        unrestricted_cash = Decimal("0.00")

    return {
        "total_cash": total_cash,
        "restricted_balance_outstanding": restricted_balance,
        "unrestricted_cash_available": unrestricted_cash,
    }


# Backward-compatible alias if your view uses the underscored name
_get_current_fund_balances = get_current_fund_balances


# ==========================================
# 2. SP-BASED FINANCIAL HEALTH (YEARLY)
# ==========================================
def _sp_unrestricted_year_row(church_id: int, year: int):
    """
    Reads one year row from Finance_UnrestrictedIncomeByYear.

    Column map:
      0  Year
      1  TotalTithes
      2  TotalOfferings
      3  TotalUnrestrictedDonations
      4  TotalUnrestrictedOtherIncome
      5  GrandTotalUnrestricted
      6  TotalBudgetReturnsToUnrestricted
      7  TotalUnrestrictedExpenses
      8  NetGrandTotalUnrestricted
      9  TotalRealExpensesAll
      10 TotalRestrictedExpenses
    """
    with connection.cursor() as cursor:
        cursor.callproc("Finance_UnrestrictedIncomeByYear", [church_id])
        rows = cursor.fetchall() or []

    for r in rows:
        try:
            if int(r[0]) == int(year):
                return {
                    "year": int(r[0]),
                    "tithes": _to_decimal(r[1]),
                    "offerings": _to_decimal(r[2]),
                    "donations": _to_decimal(r[3]),
                    "other_income": _to_decimal(r[4]),
                    "gross_unrestricted": _to_decimal(r[5]),
                    "budget_returns": _to_decimal(r[6]),
                    "unrestricted_expenses": _to_decimal(r[7]),
                    "net_unrestricted": _to_decimal(r[8]),
                    "real_expenses_all": _to_decimal(r[9]),
                    "restricted_expenses": _to_decimal(r[10]),
                }
        except Exception:
            continue

    return {
        "year": int(year),
        "tithes": Decimal("0.00"),
        "offerings": Decimal("0.00"),
        "donations": Decimal("0.00"),
        "other_income": Decimal("0.00"),
        "gross_unrestricted": Decimal("0.00"),
        "budget_returns": Decimal("0.00"),
        "unrestricted_expenses": Decimal("0.00"),
        "net_unrestricted": Decimal("0.00"),
        "real_expenses_all": Decimal("0.00"),
        "restricted_expenses": Decimal("0.00"),
    }


def calculate_financial_health(church_id, year=None):
    """
    SP-based financial health using Finance_UnrestrictedIncomeByYear.

    ratio = unrestricted_expenses / gross_unrestricted

    Status rules:
      - Deficit Risk: net < 0 OR ratio >= 1.00
      - Critical:     ratio >= 0.80
      - Warning:      ratio >= 0.50
      - Healthy:      ratio < 0.50
    """
    yr = int(year) if year else timezone.now().year
    row = _sp_unrestricted_year_row(church_id, yr)

    gross = row["gross_unrestricted"]
    expenses = row["unrestricted_expenses"]
    net = row["net_unrestricted"]

    if gross > 0:
        ratio = (expenses / gross).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        ratio = Decimal("1.00") if expenses > 0 else Decimal("0.00")

    if net < 0 or ratio >= Decimal("1.00"):
        status = "Deficit Risk"
        advice = "Spending exceeds income. Immediate cuts recommended."
        color = "danger"
    elif ratio >= Decimal("0.80"):
        status = "Critical"
        advice = "Spending is very high relative to income. Tight control is needed."
        color = "danger"
    elif ratio >= Decimal("0.50"):
        status = "Warning"
        advice = "Spending is manageable but should be monitored closely."
        color = "warning"
    else:
        status = "Healthy"
        advice = "Income safely covers spending."
        color = "success"

    return {
        "status": status,
        "ratio": float(ratio),
        "color": color,
        "advice": advice,
        "year": yr,

        "tithes": float(row["tithes"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "offerings": float(row["offerings"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "donations": float(row["donations"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "other_income": float(row["other_income"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "budget_returns": float(row["budget_returns"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "gross_unrestricted": float(row["gross_unrestricted"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "unrestricted_expenses": float(row["unrestricted_expenses"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "net_unrestricted": float(row["net_unrestricted"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "real_expenses_all": float(row["real_expenses_all"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "restricted_expenses": float(row["restricted_expenses"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),

        # compatibility keys
        "total_income": float(row["gross_unrestricted"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_expenses": float(row["unrestricted_expenses"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    }


calculate_financial_health_sp = calculate_financial_health


# ==========================================
# 3. OLD 90-DAY HEALTH KPI (OPTIONAL)
# ==========================================
def calculate_financial_health90D(church_id):
    """
    Old rolling 90-day health KPI.
    """
    Tithe = get_model_safe("Tithe")
    Offering = get_model_safe("Offering")
    Donations = get_model_safe("Donations")
    OtherIncome = get_model_safe("OtherIncome")
    Expense = get_model_safe("Expense")

    today = timezone.now().date()
    start_date = today - timedelta(days=90)

    income_sources = []

    if Tithe:
        val = Tithe.objects.filter(
            church_id=church_id,
            date__gte=start_date
        ).aggregate(t=Sum("amount"))["t"]
        income_sources.append(val or 0)

    if Offering:
        val = Offering.objects.filter(
            church_id=church_id,
            date__gte=start_date
        ).aggregate(t=Sum("amount"))["t"]
        income_sources.append(val or 0)

    if Donations:
        val = Donations.objects.filter(
            church_id=church_id,
            donations_date__gte=start_date
        ).aggregate(t=Sum("amount"))["t"]
        income_sources.append(val or 0)

    if OtherIncome:
        val = OtherIncome.objects.filter(
            church_id=church_id,
            date__gte=start_date
        ).aggregate(t=Sum("amount"))["t"]
        income_sources.append(val or 0)

    total_income = sum(float(x) for x in income_sources)

    total_expenses = 0.0
    if Expense:
        val = (
            Expense.objects.filter(
                church_id=church_id,
                expense_date__gte=start_date
            )
            .exclude(status__in=["Declined", "Rejected"])
            .exclude(category__is_system=True)
            .exclude(category__is_transfer=True)
            .aggregate(t=Sum("amount"))["t"]
        )
        total_expenses = float(val or 0)

    if total_expenses == 0:
        ratio = 2.0
    elif total_income == 0:
        ratio = 0.0
    else:
        ratio = total_income / total_expenses

    if ratio >= 1.2:
        return {
            "status": "Healthy",
            "ratio": round(ratio, 2),
            "color": "success",
            "advice": "Surplus detected. Consider reallocating to reserves.",
        }
    elif 1.0 <= ratio < 1.2:
        return {
            "status": "Caution",
            "ratio": round(ratio, 2),
            "color": "warning",
            "advice": "Tight margin. Monitor discretionary spending.",
        }
    else:
        return {
            "status": "Deficit Risk",
            "ratio": round(ratio, 2),
            "color": "danger",
            "advice": "Spending exceeds income. Immediate cuts recommended.",
        }


# ==========================================
# 4. PROJECTED EXPENSES
# ==========================================
def _recent_valid_expenses_qs(church_id):
    """
    Base queryset for last-90-days valid expenses.

    Excludes:
      - Declined / Rejected expenses
      - system categories
      - transfer categories
      - expenses linked to cash/bank transfer movements
        (CASH_TO_BANK, BANK_TO_CASH)
    """
    Expense = get_model_safe("Expense")
    CashBankMovement = get_model_safe("CashBankMovement")

    if not Expense:
        return None

    today = timezone.now().date()
    ninety_days_ago = today - timedelta(days=90)

    qs = (
        Expense.objects.filter(
            church_id=church_id,
            expense_date__gte=ninety_days_ago
        )
        .exclude(status__in=["Declined", "Rejected"])
        .exclude(category__is_system=True)
        .exclude(category__is_transfer=True)
    )

    # Exclude expenses that are tied to cash/bank transfer movement records
    if CashBankMovement:
        transfer_link = CashBankMovement.objects.filter(
            church_id=church_id,
            source_type="EXPENSE",
            source_id=OuterRef("pk"),
            direction__in=["CASH_TO_BANK", "BANK_TO_CASH"],
        )

        qs = qs.annotate(
            has_cashbank_transfer=Exists(transfer_link)
        ).filter(
            has_cashbank_transfer=False
        )

    return qs

def get_projected_expenses_all(church_id):
    """
    General projected bills using actual valid expenses from the last 90 days.
    Includes both restricted and unrestricted expenses.
    """
    qs = _recent_valid_expenses_qs(church_id)
    if qs is None:
        return 0.0

    total_fixed = qs.aggregate(
        t=Coalesce(Sum("amount"), Decimal("0.00"))
    )["t"]

    total_fixed = _to_decimal(total_fixed)
    return float((total_fixed / Decimal("3")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_projected_expenses_unrestricted(church_id):
    """
    Projected unrestricted bills using actual unrestricted expenses
    from the last 90 days.
    """
    qs = _recent_valid_expenses_qs(church_id)
    if qs is None:
        return 0.0

    total_fixed = (
        qs.exclude(category__is_restricted=True)
        .aggregate(t=Coalesce(Sum("amount"), Decimal("0.00")))["t"]
    )

    total_fixed = _to_decimal(total_fixed)
    return float((total_fixed / Decimal("3")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_projected_expenses_restricted(church_id):
    """
    Projected restricted bills using actual restricted expenses
    from the last 90 days.
    """
    qs = _recent_valid_expenses_qs(church_id)
    if qs is None:
        return 0.0

    total_fixed = (
        qs.filter(category__is_restricted=True)
        .aggregate(t=Coalesce(Sum("amount"), Decimal("0.00")))["t"]
    )

    total_fixed = _to_decimal(total_fixed)
    return float((total_fixed / Decimal("3")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# Default projected expenses for the optimizer page = unrestricted-aware
def get_projected_expenses(church_id):
    return get_projected_expenses_unrestricted(church_id)


# ==========================================
# 5. MINISTRY PERFORMANCE
# ==========================================
def analyze_ministry_performance(church_id, year=None):
    """
    Calculates Allocated vs Spent for a specific year.

    IMPORTANT:
    If your related expense date field is not `date_incurred`,
    replace it below with the correct field.
    """
    Ministry = get_model_safe("Ministry")
    MinistryBudget = get_model_safe("MinistryBudget")

    if not Ministry or not MinistryBudget:
        return {}

    target_year = int(year) if year else timezone.now().year
    ministries = Ministry.objects.filter(church_id=church_id, is_active=True)

    budget_stats = (
        MinistryBudget.objects
        .filter(church_id=church_id, year=target_year)
        .values("ministry_id")
        .annotate(
            total_allocated=Coalesce(
                Sum("amount_allocated"),
                Decimal("0.00"),
                output_field=DecimalField()
            ),
            total_spent=Coalesce(
                Sum(
                    "released_budgets__expenses__amount",
                    filter=Q(released_budgets__expenses__date_incurred__year=target_year)
                ),
                Decimal("0.00"),
                output_field=DecimalField()
            )
        )
    )

    stats_map = {
        item["ministry_id"]: {
            "alloc": float(item["total_allocated"] or 0),
            "spent": float(item["total_spent"] or 0),
        }
        for item in budget_stats
    }

    grand_total_spent = sum(item["spent"] for item in stats_map.values())
    performance_data = {}

    for m in ministries:
        data = stats_map.get(m.id, {"alloc": 0.0, "spent": 0.0})

        allocated = float(data["alloc"] or 0.0)
        if allocated <= 0:
            min_monthly = float(getattr(m, "min_monthly_budget", 0) or 0)
            allocated = min_monthly * 12

        spent = float(data["spent"] or 0.0)

        utilization = (spent / allocated) * 100 if allocated > 0 else (100.0 if spent > 0 else 0.0)
        share_percentage = (spent / grand_total_spent) * 100 if grand_total_spent > 0 else 0.0

        if share_percentage >= 20:
            suggested = 9
        elif share_percentage >= 15:
            suggested = 8
        elif share_percentage >= 10:
            suggested = 7
        elif share_percentage >= 5:
            suggested = 5
        else:
            suggested = 3

        performance_data[m.id] = {
            "allocated": round(allocated, 2),
            "spent": round(spent, 2),
            "utilization": round(utilization, 1),
            "share_percentage": round(share_percentage, 1),
            "suggested_score": suggested,
        }

    return performance_data

def get_trailing_3_month_unrestricted_operating_avg(church_id):
    qs = _recent_valid_expenses_qs(church_id)
    if qs is None:
        return 0.0

    total = (
        qs.exclude(category__is_restricted=True)
        .aggregate(t=Coalesce(Sum("amount"), Decimal("0.00")))["t"]
    )

    total = _to_decimal(total)
    return float((total / Decimal("3")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
