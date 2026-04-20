from django.views.generic import TemplateView
from django.contrib.auth.views import LogoutView
from django.urls import reverse_lazy
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views import View
from Register.views import RoleAwareLoginView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db import connection
from django.db.models import Sum, Q, Case, When, Value, CharField
from django.db.models.functions import ExtractYear, TruncMonth
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.generic import TemplateView
import json
from decimal import Decimal
from calendar import monthrange
from datetime import date, timedelta
from django.contrib.auth import get_user_model
# adjust these imports based on your app structure
from Register.models import CustomUser
from Register.models import (
    Tithe,
    Offering,
    Donations,
    OtherIncome,
    Expense,
    BankAccount,
    BudgetReleaseRequest,
    ReleasedBudget,  ApprovedReleaseRequest,
)
from django.apps import apps
from django.http import HttpResponseForbidden
import logging
logger = logging.getLogger(__name__)

# ADJUST THESE IMPORTS if your app is named differently (e.g. 'Register')
from Register.models import HomePageContent
from Register.forms import HomeContentForm
class IsDenominationAdmin(UserPassesTestMixin):
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and u.user_type in ['DenominationAdmin', 'Admin'] and u.denomination_id

class FinanceRole(LoginRequiredMixin):
    """
    Allows access to: Admin, ChurchAdmin, and Treasurer.
    Redirects unauthorized users to the home dashboard.
    """

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        # Define authorized roles
        allowed_roles = ['Admin', 'ChurchAdmin', 'Treasurer', 'DenominationAdmin','Pastor']

        if not user.is_authenticated or getattr(user, "user_type", None) not in allowed_roles:
            messages.error(request, "Access Denied: You must be a Treasurer or Admin.")
            return redirect("home")

        return super().dispatch(request, *args, **kwargs)


def test_welcome_trigger(request):
    """
    Temporary view to force-show the Welcome Guide.
    Visit /test-welcome/ in your browser to test.
    """
    request.session['show_welcome_guide'] = True
    request.session['registered_org_name'] = "Test Organization"
    messages.info(request, "Debug: Welcome flags set. Redirecting to home...")
    return redirect('home')

class FrontPageView(RoleAwareLoginView):
    template_name = "Landing.html"

class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('landing')

# =========================================================
# MISSING HOMEVIEW ADDED BELOW
# =========================================================
from decimal import Decimal
from calendar import monthrange
from datetime import date, timedelta
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Sum, Q, Case, When, Value, CharField
from django.db.models.functions import ExtractYear, TruncMonth
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView

from Register.models import (
    BankAccount,
    Expense,
    Tithe,
    Offering,
    Donations,
    OtherIncome,
    BudgetReleaseRequest,
    ApprovedReleaseRequest,
    ReleasedBudget,
)


class HomeView(FinanceRole, TemplateView):
    template_name = "analytics_dashboard.html"

    # =========================================================
    # STORED PROCEDURE HELPER
    # =========================================================
    def sp_one(self, sp_name, params):
        try:
            with connection.cursor() as cursor:
                cursor.callproc(sp_name, params)
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

            return row
        except Exception as e:
            logger.exception("Stored procedure failed: %s | params=%s | error=%s", sp_name, params, e)
            return None
    # =========================================================
    # HELPERS
    # =========================================================
    def _safe_int(self, value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _sum_amount(self, model, church, date_field, start_date, end_date):
        return (
            model.objects.filter(
                church=church,
                **{f"{date_field}__range": (start_date, end_date)}
            ).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )

    def _sum_amount_datetime(self, model, church, datetime_field, start_date, end_date):
        return (
            model.objects.filter(
                church=church,
                **{f"{datetime_field}__date__range": (start_date, end_date)}
            ).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )

    def _count_users(self, UserModel, church, user_type=None, status=None):
        qs = UserModel.objects.filter(church=church)

        if user_type:
            qs = qs.filter(user_type=user_type)

        if status:
            qs = qs.filter(status=status)

        return qs.count()

    def _get_bank_balance(self, church):
        bank = BankAccount.objects.filter(church=church).first()
        if bank and bank.current_balance is not None:
            return Decimal(bank.current_balance)
        return Decimal("0.00")

    def _handle_user_without_church(self, request):
        """
        Important:
        Never redirect authenticated users back to login here.
        Doing so creates an infinite loop when LoginView has
        redirect_authenticated_user = True.
        """
        messages.error(request, "No church is assigned to your account.")
        return HttpResponseForbidden("No church is assigned to your account.")

    # =========================================================
    # REAL EXPENSE FILTERING
    # =========================================================
    def _expense_queryset(self, church, start_date=None, end_date=None):
        """
        Keep real expenses:
        - Budget Release (Unposted)
        - Budget Release - Cash
        - Budget Release - Bank

        Exclude:
        - transfer / bank movement rows
        - internal budget return rows
        """
        qs = Expense.objects.filter(church=church)

        if start_date and end_date:
            qs = qs.filter(expense_date__range=(start_date, end_date))

        transfer_filter = (
            Q(category__name__istartswith="Bank Depos") |
            Q(category__name__icontains="Bank Deposit") |
            Q(category__name__istartswith="Bank Withdr") |
            Q(category__name__icontains="Bank Withdraw") |
            Q(category__name__icontains="Bank Withdrawal") |
            Q(category__name__icontains="Transfer to Bank") |
            Q(category__name__icontains="Transfer from Bank") |
            Q(category__name__icontains="Cash to Bank") |
            Q(category__name__icontains="Bank to Cash")
        )

        internal_budget_filter = (
            Q(category__name__iexact="Budget Release") |
            Q(category__name__iexact="Budget Return") |
            Q(category__name__istartswith="Budget Return Deposit") |
            Q(category__name__istartswith="Budget Return From")
        )

        qs = qs.exclude(transfer_filter | internal_budget_filter)
        return qs

    def _get_available_years(self, church, current_year):
        years = set()

        sources = [
            (Expense, "expense_date"),
            (Tithe, "date"),
            (Offering, "date"),
            (Donations, "donations_date"),
            (OtherIncome, "date"),
            (BudgetReleaseRequest, "requested_at"),
            (ApprovedReleaseRequest, "date_released"),
            (ReleasedBudget, "date_released"),
            (ReleasedBudget, "liquidated_date"),
        ]

        for model, field_name in sources:
            result = (
                model.objects.filter(church=church)
                .annotate(year=ExtractYear(field_name))
                .values_list("year", flat=True)
                .distinct()
            )
            years.update(y for y in result if y is not None)

        years = sorted(years, reverse=True)
        if current_year not in years:
            years.insert(0, current_year)

        return years

    def _build_week_options(self, selected_year):
        max_week = date(selected_year, 12, 28).isocalendar().week
        options = []

        for week_num in range(1, max_week + 1):
            start_date = date.fromisocalendar(selected_year, week_num, 1)
            end_date = date.fromisocalendar(selected_year, week_num, 7)

            label = f"Week {week_num} — {start_date.strftime('%b %d')} to {end_date.strftime('%b %d, %Y')}"
            options.append({
                "value": week_num,
                "label": label,
                "start_date": start_date,
                "end_date": end_date,
            })

        return options

    def _get_period_range(self, selected_year, period, selected_month=None, selected_week=None):
        today = timezone.localdate()

        if period == "monthly":
            selected_month = self._safe_int(selected_month, today.month)
            if selected_month < 1 or selected_month > 12:
                selected_month = today.month

            start_date = date(selected_year, selected_month, 1)
            end_date = date(
                selected_year,
                selected_month,
                monthrange(selected_year, selected_month)[1]
            )

        elif period == "weekly":
            current_week = today.isocalendar().week
            selected_week = self._safe_int(selected_week, current_week)

            max_week = date(selected_year, 12, 28).isocalendar().week
            if selected_week < 1 or selected_week > max_week:
                selected_week = current_week if selected_year == today.year and current_week <= max_week else 1

            try:
                start_date = date.fromisocalendar(selected_year, selected_week, 1)
                end_date = date.fromisocalendar(selected_year, selected_week, 7)
            except ValueError:
                selected_week = 1
                start_date = date.fromisocalendar(selected_year, selected_week, 1)
                end_date = date.fromisocalendar(selected_year, selected_week, 7)

        else:
            period = "yearly"
            selected_month = None
            selected_week = None
            start_date = date(selected_year, 1, 1)
            end_date = date(selected_year, 12, 31)

        return period, start_date, end_date, selected_month, selected_week

    def _build_chart_data(self, church, period, selected_year, selected_month, start_date, end_date):
        if period == "yearly":
            labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            income_data = [0.0] * 12
            expense_data = [0.0] * 12

            expense_qs = (
                self._expense_queryset(church, start_date, end_date)
                .annotate(month=TruncMonth("expense_date"))
                .values("month")
                .annotate(total=Sum("amount"))
                .order_by("month")
            )
            for entry in expense_qs:
                if entry["month"]:
                    idx = entry["month"].month - 1
                    expense_data[idx] = float(entry["total"] or 0)

            def add_income(model, date_field):
                qs = (
                    model.objects.filter(
                        church=church,
                        **{f"{date_field}__range": (start_date, end_date)}
                    )
                    .annotate(month=TruncMonth(date_field))
                    .values("month")
                    .annotate(total=Sum("amount"))
                    .order_by("month")
                )
                for entry in qs:
                    if entry["month"]:
                        idx = entry["month"].month - 1
                        income_data[idx] += float(entry["total"] or 0)

        elif period == "monthly":
            days_in_month = monthrange(selected_year, selected_month)[1]
            labels = [str(i) for i in range(1, days_in_month + 1)]
            income_data = [0.0] * days_in_month
            expense_data = [0.0] * days_in_month

            expense_qs = (
                self._expense_queryset(church, start_date, end_date)
                .values("expense_date")
                .annotate(total=Sum("amount"))
                .order_by("expense_date")
            )
            for entry in expense_qs:
                if entry["expense_date"]:
                    idx = entry["expense_date"].day - 1
                    expense_data[idx] = float(entry["total"] or 0)

            def add_income(model, date_field):
                qs = (
                    model.objects.filter(
                        church=church,
                        **{f"{date_field}__range": (start_date, end_date)}
                    )
                    .values(date_field)
                    .annotate(total=Sum("amount"))
                    .order_by(date_field)
                )
                for entry in qs:
                    current_date = entry[date_field]
                    if current_date:
                        idx = current_date.day - 1
                        income_data[idx] += float(entry["total"] or 0)

        else:
            labels = [(start_date + timedelta(days=i)).strftime("%a") for i in range(7)]
            income_data = [0.0] * 7
            expense_data = [0.0] * 7

            expense_qs = (
                self._expense_queryset(church, start_date, end_date)
                .values("expense_date")
                .annotate(total=Sum("amount"))
                .order_by("expense_date")
            )
            for entry in expense_qs:
                if entry["expense_date"]:
                    idx = (entry["expense_date"] - start_date).days
                    if 0 <= idx < 7:
                        expense_data[idx] = float(entry["total"] or 0)

            def add_income(model, date_field):
                qs = (
                    model.objects.filter(
                        church=church,
                        **{f"{date_field}__range": (start_date, end_date)}
                    )
                    .values(date_field)
                    .annotate(total=Sum("amount"))
                    .order_by(date_field)
                )
                for entry in qs:
                    current_date = entry[date_field]
                    if current_date:
                        idx = (current_date - start_date).days
                        if 0 <= idx < 7:
                            income_data[idx] += float(entry["total"] or 0)

        add_income(Tithe, "date")
        add_income(Offering, "date")
        add_income(Donations, "donations_date")
        add_income(OtherIncome, "date")

        return labels, income_data, expense_data

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        role = getattr(request.user, "user_type", None)

        # Prevent church-based dashboard access for users with no church.
        # Most important: do NOT redirect authenticated users back to login.
        if not getattr(request.user, "church", None):
            return self._handle_user_without_church(request)

        # Optional extra guard:
        # If you do not want DenominationAdmin on this page at all,
        # redirect to a denomination-specific page instead of loading church analytics.
        # Uncomment and adjust the URL name if needed.
        #
        # if role == "DenominationAdmin":
        #     return redirect("denomination_dashboard")

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        church = self.request.user.church
        today = timezone.localdate()
        User = get_user_model()

        # =========================================================
        # 1. HANDLE FILTER SELECTION
        # =========================================================
        available_years = self._get_available_years(church, today.year)

        selected_year = self._safe_int(self.request.GET.get("year"), today.year)
        if selected_year not in available_years:
            selected_year = today.year if today.year in available_years else available_years[0]

        period = (self.request.GET.get("period") or "yearly").lower()
        selected_month = self.request.GET.get("month")
        selected_week = self.request.GET.get("week")

        period, start_date, end_date, selected_month, selected_week = self._get_period_range(
            selected_year=selected_year,
            period=period,
            selected_month=selected_month,
            selected_week=selected_week,
        )

        # =========================================================
        # 2. KPI TOTALS - FILTER AWARE
        # =========================================================
        t_total = self._sum_amount(Tithe, church, "date", start_date, end_date)
        o_total = self._sum_amount(Offering, church, "date", start_date, end_date)
        d_total = self._sum_amount(Donations, church, "donations_date", start_date, end_date)
        oi_total = self._sum_amount(OtherIncome, church, "date", start_date, end_date)

        period_income = t_total + o_total + d_total + oi_total

        period_expense = (
            self._expense_queryset(church, start_date, end_date)
            .aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )

        period_net = period_income - period_expense

        cash_on_hand = Decimal("0.00")
        result = self.sp_one("Calculate_CashOnHand", [church.id])
        if result and result[0] is not None:
            cash_on_hand = Decimal(result[0] or 0)

        bank_balance = self._get_bank_balance(church)

        # =========================================================
        # 2B. BUDGET KPIs
        # =========================================================
        total_budget_to_release = (
            ApprovedReleaseRequest.objects.filter(
                church=church,
                date_released__range=(start_date, end_date),
            ).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )

        total_budget_to_release_count = ApprovedReleaseRequest.objects.filter(
            church=church,
            date_released__range=(start_date, end_date),
        ).count()

        total_budget_request = self._sum_amount_datetime(
            BudgetReleaseRequest, church, "requested_at", start_date, end_date
        )

        total_budget_unliquidated = (
            ReleasedBudget.objects.filter(
                church=church,
                is_liquidated=False,
                date_released__range=(start_date, end_date),
            ).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )

        total_budget_liquidated = (
            ReleasedBudget.objects.filter(
                church=church,
                is_liquidated=True,
                liquidated_date__range=(start_date, end_date),
            ).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )

        total_budget_request_count = BudgetReleaseRequest.objects.filter(
            church=church,
            requested_at__date__range=(start_date, end_date),
        ).count()

        total_budget_unliquidated_count = ReleasedBudget.objects.filter(
            church=church,
            is_liquidated=False,
            date_released__range=(start_date, end_date),
        ).count()

        total_budget_liquidated_count = ReleasedBudget.objects.filter(
            church=church,
            is_liquidated=True,
            liquidated_date__range=(start_date, end_date),
        ).count()

        # =========================================================
        # 3. USER KPIs
        # =========================================================
        total_users = self._count_users(User, church)
        total_active_users = self._count_users(User, church, status=User.Status.ACTIVE)
        total_inactive_users = self._count_users(User, church, status=User.Status.INACTIVE)

        total_pastors = self._count_users(User, church, user_type=User.UserType.PASTOR)
        total_active_pastors = self._count_users(
            User, church, user_type=User.UserType.PASTOR, status=User.Status.ACTIVE
        )
        total_inactive_pastors = self._count_users(
            User, church, user_type=User.UserType.PASTOR, status=User.Status.INACTIVE
        )

        total_treasurers = self._count_users(User, church, user_type=User.UserType.TREASURER)
        total_active_treasurers = self._count_users(
            User, church, user_type=User.UserType.TREASURER, status=User.Status.ACTIVE
        )
        total_inactive_treasurers = self._count_users(
            User, church, user_type=User.UserType.TREASURER, status=User.Status.INACTIVE
        )

        total_members = self._count_users(User, church, user_type=User.UserType.MEMBER)
        total_active_members = self._count_users(
            User, church, user_type=User.UserType.MEMBER, status=User.Status.ACTIVE
        )
        total_inactive_members = self._count_users(
            User, church, user_type=User.UserType.MEMBER, status=User.Status.INACTIVE
        )

        # =========================================================
        # 4. CHART DATA
        # =========================================================
        chart_labels, income_data, expense_data = self._build_chart_data(
            church=church,
            period=period,
            selected_year=selected_year,
            selected_month=selected_month,
            start_date=start_date,
            end_date=end_date,
        )

        # =========================================================
        # 5. PIE CHARTS
        # =========================================================
        expense_breakdown = (
            self._expense_queryset(church, start_date, end_date)
            .values("category__name")
            .annotate(total=Sum("amount"))
            .order_by("-total")
        )
        pie_labels = [x["category__name"] or "Uncategorized" for x in expense_breakdown]
        pie_data = [float(x["total"] or 0) for x in expense_breakdown]

        fundtype_breakdown = (
            self._expense_queryset(church, start_date, end_date)
            .annotate(
                fund_type=Case(
                    When(
                        category__description__isnull=False,
                        category__description__gt="",
                        then=Value("Restricted")
                    ),
                    default=Value("Unrestricted"),
                    output_field=CharField()
                )
            )
            .values("fund_type")
            .annotate(total=Sum("amount"))
            .order_by("-total")
        )
        fund_pie_labels = [x["fund_type"] for x in fundtype_breakdown]
        fund_pie_data = [float(x["total"] or 0) for x in fundtype_breakdown]

        # =========================================================
        # 6. FILTER OPTIONS
        # =========================================================
        month_options = [
            (1, "January"), (2, "February"), (3, "March"), (4, "April"),
            (5, "May"), (6, "June"), (7, "July"), (8, "August"),
            (9, "September"), (10, "October"), (11, "November"), (12, "December"),
        ]

        week_options = self._build_week_options(selected_year)

        if period == "yearly":
            filter_label = f"Year {selected_year}"
        elif period == "monthly":
            filter_label = f"{month_options[selected_month - 1][1]} {selected_year}"
        else:
            filter_label = (
                f"Week {selected_week} — "
                f"{start_date.strftime('%b %d, %Y')} to {end_date.strftime('%b %d, %Y')}"
            )

        # =========================================================
        # 7. CONTEXT
        # =========================================================
        context.update({
            "period": period,
            "selected_year": selected_year,
            "selected_month": selected_month,
            "selected_week": selected_week,
            "available_years": available_years,
            "month_options": month_options,
            "week_options": week_options,
            "filter_label": filter_label,
            "range_start": start_date,
            "range_end": end_date,

            "kpi_cash": cash_on_hand,
            "kpi_bank_balance": bank_balance,
            "kpi_income": period_income,
            "kpi_expense": period_expense,
            "kpi_net": period_net,

            "kpi_budget_total_to_release": total_budget_to_release,
            "kpi_budget_total_to_release_count": total_budget_to_release_count,
            "kpi_budget_total_request": total_budget_request,
            "kpi_budget_unliquidated": total_budget_unliquidated,
            "kpi_budget_liquidated": total_budget_liquidated,
            "kpi_budget_total_request_count": total_budget_request_count,
            "kpi_budget_unliquidated_count": total_budget_unliquidated_count,
            "kpi_budget_liquidated_count": total_budget_liquidated_count,

            "kpi_total_users": total_users,
            "kpi_total_active_users": total_active_users,
            "kpi_total_inactive_users": total_inactive_users,

            "kpi_total_pastors": total_pastors,
            "kpi_total_active_pastors": total_active_pastors,
            "kpi_total_inactive_pastors": total_inactive_pastors,

            "kpi_total_treasurers": total_treasurers,
            "kpi_total_active_treasurers": total_active_treasurers,
            "kpi_total_inactive_treasurers": total_inactive_treasurers,

            "kpi_total_members": total_members,
            "kpi_total_active_members": total_active_members,
            "kpi_total_inactive_members": total_inactive_members,

            "chart_labels": json.dumps(chart_labels),
            "chart_income": json.dumps(income_data),
            "chart_expense": json.dumps(expense_data),

            "pie_labels": json.dumps(pie_labels),
            "pie_data": json.dumps(pie_data),

            "fund_pie_labels": json.dumps(fund_pie_labels),
            "fund_pie_data": json.dumps(fund_pie_data),
        })
        return context

