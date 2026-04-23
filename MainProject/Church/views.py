import random
import traceback
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.mixins import UserPassesTestMixin, LoginRequiredMixin
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.views.generic import ListView, CreateView, TemplateView
from django.urls import reverse_lazy
from django.db import connection
from decimal import Decimal, InvalidOperation
from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.conf import settings
from datetime import date
from calendar import monthrange
from django.core.exceptions import ValidationError
import copy
from collections import defaultdict
import logging
from django.views.generic import UpdateView
from .forms import ChurchProfileForm
from .models import Denomination
from .forms import DenominationForm
# Import your forms and models
from .models import Church, Denomination, ChurchApplication
from .forms import ChurchSignupForm, DenominationSignupForm, ChurchApplicationForm
from django.http import HttpResponse
# --- IMPORT THE FAST EMAIL UTILITY ---
from .utils import send_html_email

User = get_user_model()


# --- PERMISSION MIXINS ---
class IsDenominationAdmin(UserPassesTestMixin):
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and u.user_type in ['DenominationAdmin', 'Admin'] and u.denomination_id


class IsChurchAdmin(UserPassesTestMixin):
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and u.user_type in ['ChurchAdmin', 'Admin'] and u.church_id


logger = logging.getLogger(__name__)

# =========================================================
# 1. CHURCH SIGNUP VIEW (OTP VERSION)
# =========================================================
class ChurchSignupView(View):
    template_name = 'church_signup.html'

    def get(self, request):
        return render(request, self.template_name, {'form': ChurchSignupForm()})

    @transaction.atomic
    def post(self, request):
        form = ChurchSignupForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form})

        # 1) Create Church
        church = form.save()

        # 2) Create the ChurchAdmin as INACTIVE until OTP is verified
        admin = User.objects.create_user(
            username=form.cleaned_data['admin_username'],
            email=form.cleaned_data['admin_email'],
            password=form.cleaned_data['admin_password'],
            user_type=User.UserType.CHURCH_ADMIN,
            church=church,
            status=User.Status.INACTIVE,
        )

        # 3) Generate 6-digit OTP
        otp_code = str(random.randint(100000, 999999))

        # 4) Store OTP + pending user in session
        request.session['pending_user_id'] = admin.id
        request.session['verification_code'] = otp_code
        request.session.modified = True

        # 5) Send verification email
        subject = "Your Verification Code"
        message = (
            f"Hello {admin.username},\n\n"
            f"Your verification code is: {otp_code}\n\n"
            f"Please enter this code on the website to activate your account."
        )

        try:
            send_html_email(subject, message, admin.email)
            messages.info(request, "Code sent! Please check your email.")
        except Exception:
            messages.warning(request, "Account created, but email failed. Contact support.")

        # 6) Go to OTP verification page
        return redirect('Church:verify_email')

# =========================================================
# 2. DENOMINATION SIGNUP VIEW (OTP VERSION)
# =========================================================
class DenominationSignupView(View):
    template_name = 'denomination_signup.html'

    def get(self, request):
        return render(request, self.template_name, {'form': DenominationSignupForm()})

    @transaction.atomic
    def post(self, request):
        form = DenominationSignupForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form})

        # 1) Create Denomination
        denom = form.save()

        # 2) Create the DenominationAdmin as INACTIVE until OTP is verified
        admin = User.objects.create_user(
            username=form.cleaned_data['admin_username'],
            email=form.cleaned_data['admin_email'],
            password=form.cleaned_data['admin_password'],
            user_type=User.UserType.DENOMINATION_ADMIN,
            denomination=denom,
            status=User.Status.INACTIVE,
        )

        # 3) Generate 6-digit OTP
        otp_code = str(random.randint(100000, 999999))

        # 4) Store OTP + pending user in session
        request.session['pending_user_id'] = admin.id
        request.session['verification_code'] = otp_code
        request.session.modified = True

        # 5) Send verification email
        subject = "Your Verification Code"
        message = (
            f"Hello {admin.username},\n\n"
            f"Your verification code is: {otp_code}\n\n"
            f"Please enter this code on the website to activate your account."
        )

        try:
            send_html_email(subject, message, admin.email)
            messages.info(request, "Code sent! Please check your email.")
        except Exception:
            messages.warning(request, "Account created, but email failed. Contact support.")

        # 6) Redirect to verification page
        return redirect('Church:verify_email')


# =========================================================
# 3. VERIFY CODE VIEW (NEW LOGIC)
# =========================================================
import traceback
from django.http import HttpResponse

class VerifyEmailView(View):
    template_name = 'verify_email.html'

    def get(self, request):
        if 'verification_code' not in request.session:
            messages.error(request, "Session expired or invalid. Please register again.")
            return redirect('login')
        return render(request, self.template_name)

    def post(self, request):
        entered_code = (request.POST.get('code') or '').strip()
        session_code = str(request.session.get('verification_code') or '').strip()
        user_id = request.session.get('pending_user_id')

        logger.info(
            "VerifyEmailView POST started | user_id=%s | entered_code=%s | session_code_exists=%s",
            user_id,
            entered_code,
            bool(session_code),
        )

        if entered_code != session_code or not user_id:
            logger.warning(
                "VerifyEmailView invalid code | user_id=%s | entered_code=%s | session_code=%s",
                user_id,
                entered_code,
                session_code,
            )
            messages.error(request, "Invalid code. Please try again.")
            return render(request, self.template_name)

        try:
            user = User.objects.select_related('church', 'denomination').get(pk=user_id)

            logger.info(
                "Verification matched | user_id=%s | username=%s | user_type=%s | church_id=%s | denomination_id=%s | current_status=%s",
                user.id,
                user.username,
                user.user_type,
                user.church_id,
                user.denomination_id,
                getattr(user, "status", None),
            )

            # Activate user
            user.status = User.Status.ACTIVE
            user.save()
            logger.info(
                "User activation save passed | user_id=%s | status=%s | is_active=%s",
                user.id,
                getattr(user, "status", None),
                getattr(user, "is_active", None),
            )

            # Auto-login
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            logger.info("Login passed | user_id=%s", user.id)

            # Clear verification session data
            request.session.pop('verification_code', None)
            request.session.pop('pending_user_id', None)

            # Welcome/session flags
            request.session['show_welcome_guide'] = True
            request.session['registered_role'] = user.user_type

            if user.church:
                request.session['registered_org_name'] = user.church.name
            elif user.denomination:
                request.session['registered_org_name'] = user.denomination.name
            else:
                request.session['registered_org_name'] = ""

            request.session.modified = True
            logger.info(
                "Session update passed | user_id=%s | registered_org_name=%s",
                user.id,
                request.session.get('registered_org_name', ''),
            )

            messages.success(request, "Email verified successfully! Welcome.")

            # TEMPORARY HARD DEBUG:
            # If this page appears, VerifyEmailView is working
            # and the crash is in the destination page after redirect.
            return HttpResponse(
                f"""
                <h2>VERIFY OK</h2>
                <p><strong>User ID:</strong> {user.id}</p>
                <p><strong>Username:</strong> {user.username}</p>
                <p><strong>User Type:</strong> {user.user_type}</p>
                <p><strong>Church ID:</strong> {user.church_id}</p>
                <p><strong>Denomination ID:</strong> {user.denomination_id}</p>
                <p><strong>Status:</strong> {getattr(user, "status", None)}</p>
                <p><strong>is_active:</strong> {getattr(user, "is_active", None)}</p>
                <p>Verification succeeded. The next step is to debug the destination page.</p>
                """,
                status=200,
            )

            # AFTER YOU SEE "VERIFY OK", replace the HttpResponse above with this:
            #
            # if user.user_type == User.UserType.CHURCH_ADMIN:
            #     logger.info("Redirecting ChurchAdmin user_id=%s to home", user.id)
            #     return redirect('home')
            # elif user.user_type == User.UserType.DENOMINATION_ADMIN:
            #     logger.info("Redirecting DenominationAdmin user_id=%s to denomination_dashboard", user.id)
            #     return redirect('denomination_dashboard')
            # elif user.user_type == User.UserType.MEMBER:
            #     logger.info("Redirecting Member user_id=%s to weekly_financial_report", user.id)
            #     return redirect('weekly_financial_report')
            # else:
            #     logger.info("Redirecting default user_id=%s to home", user.id)
            #     return redirect('home')

        except User.DoesNotExist:
            logger.exception("VerifyEmailView failed: user does not exist | pending_user_id=%s", user_id)
            return HttpResponse(
                f"<h2>ERROR</h2><p>User does not exist. pending_user_id={user_id}</p>",
                status=500,
            )

        except ValidationError as e:
            logger.exception("VerifyEmailView validation error | pending_user_id=%s | error=%s", user_id, e)
            return HttpResponse(
                f"<h2>VALIDATION ERROR</h2><p>{e}</p><pre>{traceback.format_exc()}</pre>",
                status=500,
            )

        except Exception as e:
            logger.exception("VerifyEmailView unexpected error | pending_user_id=%s | error=%s", user_id, e)
            return HttpResponse(
                f"<h2>UNEXPECTED ERROR</h2><p>{type(e).__name__}: {e}</p><pre>{traceback.format_exc()}</pre>",
                status=500,
            )
# =========================================================
# 4. APPLICATION & MANAGEMENT VIEWS (Unchanged)
# =========================================================

class ApplyToDenominationView(LoginRequiredMixin, CreateView):
    model = ChurchApplication
    form_class = ChurchApplicationForm
    template_name = 'apply_denomination.html'
    success_url = reverse_lazy('Church:apply_denomination')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # --- 1. SEARCH LOGIC ---
        search_query = self.request.GET.get('q')  # 'q' is the name of the input in HTML
        search_results = None

        if search_query:
            # Clean the input
            search_query = search_query.strip()

            # Logic: If it's a number, search by ID. Otherwise, search by Name.
            if search_query.isdigit():
                search_results = Denomination.objects.filter(id=int(search_query))
            else:
                search_results = Denomination.objects.filter(name__icontains=search_query)

        context['search_results'] = search_results
        context['search_query'] = search_query

        # --- 2. EXISTING CONTEXT LOGIC ---
        church = getattr(self.request.user, 'church', None)
        if church:
            context['my_applications'] = ChurchApplication.objects.filter(
                church=church
            ).select_related('denomination').order_by('-applied_at')

            # Helper flag to check if church already has a denomination
            context['current_denomination'] = church.denomination
        else:
            context['my_applications'] = []
            context['current_denomination'] = None

        return context

    def form_valid(self, form):
        # ... (Your existing code remains exactly the same here) ...
        church = getattr(self.request.user, 'church', None)

        if not church:
            messages.error(self.request, "Only Church Admins can apply.")
            return redirect('Register:dashboard')

        if church.denomination:
            messages.warning(self.request, f"Already a member of {church.denomination.name}.")
            return redirect(self.success_url)

        if ChurchApplication.objects.filter(church=church, status='Pending').exists():
            messages.warning(self.request, "You already have a pending application.")
            return redirect(self.success_url)

        application = form.save(commit=False)
        application.church = church
        application.status = 'Pending'
        application.save()

        messages.success(self.request, "Application submitted successfully!")
        return redirect(self.success_url)


@login_required
@require_POST
def cancel_application(request, app_id):
    application = get_object_or_404(ChurchApplication, id=app_id)

    if not hasattr(request.user, 'church') or not request.user.church:
        messages.error(request, "Unauthorized access.")
        return redirect('Church:apply_denomination')

    if application.church != request.user.church:
        messages.error(request, "You cannot cancel an application that isn't yours.")
        return redirect('Church:apply_denomination')

    if application.status == 'Pending':
        application.delete()
        messages.success(request, "Application withdrawn successfully.")
    else:
        messages.error(request, "Cannot cancel. This application has already been processed.")

    return redirect('Church:apply_denomination')


class DenominationApplicationListView(IsDenominationAdmin, ListView):
    model = ChurchApplication
    template_name = 'denomination_applications.html'
    context_object_name = 'applications'

    def get_queryset(self):
        user = self.request.user
        denomination = getattr(user, 'denomination', None)

        if denomination:
            return (
                ChurchApplication.objects.filter(
                    denomination=denomination,
                    status='Pending'
                )
                .select_related('church', 'decided_by', 'denomination')
                .order_by('-applied_at')
            )

        return ChurchApplication.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        user = self.request.user
        denomination = getattr(user, 'denomination', None)

        if denomination:
            context['approved_churches'] = Church.objects.filter(
                denomination=denomination
            ).order_by('name')

            context['revoked_applications'] = (
                ChurchApplication.objects.filter(
                    denomination=denomination,
                    status='Revoked'
                )
                .select_related('church', 'decided_by', 'denomination')
                .order_by('-decided_at', '-applied_at')
            )

            context['pending_count'] = ChurchApplication.objects.filter(
                denomination=denomination,
                status='Pending'
            ).count()

            context['revoked_count'] = ChurchApplication.objects.filter(
                denomination=denomination,
                status='Revoked'
            ).count()
        else:
            context['approved_churches'] = Church.objects.none()
            context['revoked_applications'] = ChurchApplication.objects.none()
            context['pending_count'] = 0
            context['revoked_count'] = 0

        return context



class ApplicationActionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        application = get_object_or_404(ChurchApplication, pk=pk)
        user_denom = getattr(request.user, 'denomination', None)

        if not user_denom or user_denom != application.denomination:
            messages.error(request, "Unauthorized action.")
            return redirect('Church:denomination_applications')

        action = request.POST.get('action')

        if action == 'approve':
            application.status = 'Approved'
            application.save()
            church = application.church
            church.denomination = application.denomination
            church.save()
            messages.success(request, f"{church.name} has been added to your denomination.")

        elif action == 'reject':
            application.status = 'Rejected'
            application.save()
            messages.info(request, f"Application from {application.church.name} rejected.")

        return redirect('Church:denomination_applications')


class DenominationChurchListView(IsDenominationAdmin, ListView):
    model = Church
    template_name = 'denomination_churches.html'
    context_object_name = 'churches'

    def get_queryset(self):
        return Church.objects.filter(denomination=self.request.user.denomination).order_by('name')


class DecideApplicationView(IsDenominationAdmin, View):
    def post(self, request, pk):
        app = get_object_or_404(ChurchApplication, pk=pk, denomination=request.user.denomination)
        action = request.POST.get('action')
        if action == 'approve':
            app.approve(request.user)
            messages.success(request, 'Application approved.')
        elif action == 'reject':
            app.reject(request.user)
            messages.info(request, 'Application rejected.')
        return redirect('denomination_churches')


class DenominationFinanceOverview(IsDenominationAdmin, TemplateView):
    template_name = "denomination_finance_summary.html"

    def _request_model(self):
        return apps.get_model("Church", "DenominationLiquidationAccessRequest")

    def _accounting_settings_model(self):
        return apps.get_model("Register", "AccountingSettings")

    def _church_model(self):
        return apps.get_model("Church", "Church")

    def _redirect_overview(self, request):
        return redirect(request.path)

    def post(self, request, *args, **kwargs):
        action = (request.POST.get("action") or "").strip()

        if action == "request_access":
            return self._handle_request_access(request)

        messages.warning(request, "Invalid action.")
        return self._redirect_overview(request)

    def _handle_request_access(self, request):
        RequestModel = self._request_model()
        Church = self._church_model()

        church_id = (request.POST.get("church_id") or "").strip()
        denom = getattr(request.user, "denomination", None)

        if not denom:
            messages.error(request, "No denomination is linked to your account.")
            return self._redirect_overview(request)

        try:
            church_id = int(church_id)
        except (TypeError, ValueError):
            messages.error(request, "Invalid church selected.")
            return self._redirect_overview(request)

        church = Church.objects.filter(id=church_id, denomination=denom).first()
        if not church:
            messages.error(request, "Church not found under your denomination.")
            return self._redirect_overview(request)

        existing_pending = RequestModel.objects.filter(
            church=church,
            denomination_admin=request.user,
            status=RequestModel.STATUS_PENDING,
        ).exists()

        if existing_pending:
            messages.info(request, f"Your request for {church.name} is still pending.")
            return self._redirect_overview(request)

        existing_approved = RequestModel.objects.filter(
            church=church,
            denomination_admin=request.user,
            status=RequestModel.STATUS_APPROVED,
        ).exists()

        if existing_approved:
            messages.info(request, f"You already have approved access for {church.name}.")
            return self._redirect_overview(request)

        RequestModel.objects.create(
            church=church,
            denomination_admin=request.user,
            status=RequestModel.STATUS_PENDING,
        )

        messages.success(request, f"Request sent to the church admin of {church.name}.")
        return self._redirect_overview(request)

    # =========================================================
    #  GENERIC HELPERS
    # =========================================================
    def money(self, v):
        try:
            return f"{Decimal(str(v or 0)).quantize(Decimal('0.01')):,.2f}"
        except (InvalidOperation, TypeError, ValueError):
            return "0.00"

    def _drain_cursor(self, cursor):
        try:
            cursor.fetchall()
        except Exception:
            pass

        while cursor.nextset():
            try:
                cursor.fetchall()
            except Exception:
                pass

    def _get_unrestricted_net_row(self, church_id):
        """
        Keep this only for legacy unrestricted detail columns
        like Tithes, Offerings, Unrestricted Donations, etc.
        Do NOT use this anymore for Church Income.
        """
        try:
            with connection.cursor() as cursor:
                cursor.execute("CALL Finance_UnrestrictedNet(%s)", [church_id])
                row = cursor.fetchone()
                self._drain_cursor(cursor)
                return row or [0] * 8
        except Exception:
            return [0] * 8

    def _get_latest_requests_map(self, churches):
        RequestModel = self._request_model()

        request_rows = (
            RequestModel.objects
            .filter(
                denomination_admin=self.request.user,
                church__in=churches,
            )
            .select_related("church")
            .order_by("church_id", "-requested_at", "-id")
        )

        latest_by_church = {}
        for req in request_rows:
            if req.church_id not in latest_by_church:
                latest_by_church[req.church_id] = req

        return latest_by_church

    # =========================================================
    #  STORED PROCEDURE HELPERS
    # =========================================================
    def sp_one(self, sp_name, params):
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

    def sp_all(self, sp_name, params):
        with connection.cursor() as cursor:
            cursor.callproc(sp_name, params)
            rows = cursor.fetchall()

            try:
                cursor.fetchall()
            except Exception:
                pass

            while cursor.nextset():
                try:
                    cursor.fetchall()
                except Exception:
                    pass

        return rows

    # =========================================================
    #  PERIOD LABEL FORMATTERS
    # =========================================================
    def _format_period_label(self, report_type, label):
        raw = str(label or "").strip()
        if not raw:
            return raw

        if report_type == "weekly":
            try:
                year_str, week_str = raw.split("-")
                year = int(year_str)
                week = int(week_str)

                start_date = date.fromisocalendar(year, week, 1)
                end_date = date.fromisocalendar(year, week, 7)

                if start_date.month == end_date.month and start_date.year == end_date.year:
                    return f"{start_date.strftime('%b %d')}–{end_date.strftime('%d, %Y')}"
                elif start_date.year == end_date.year:
                    return f"{start_date.strftime('%b %d')}–{end_date.strftime('%b %d, %Y')}"
                else:
                    return f"{start_date.strftime('%b %d, %Y')}–{end_date.strftime('%b %d, %Y')}"
            except Exception:
                return raw

        if report_type == "monthly":
            try:
                year_str, month_str = raw.split("-")
                year = int(year_str)
                month = int(month_str)
                return date(year, month, 1).strftime("%B %Y")
            except Exception:
                return raw

        if report_type == "yearly":
            return raw

        return raw

    def _register_period(self, sort_key, label, available_periods, seen_sort_keys, label_to_sortkey, report_type):
        sort_key = str(sort_key or "")
        raw_label = str(label or "")

        if not sort_key or not raw_label:
            return

        display_label = self._format_period_label(report_type, raw_label)

        if sort_key not in seen_sort_keys:
            available_periods.append(display_label)
            seen_sort_keys.add(sort_key)

        label_to_sortkey[display_label] = sort_key

    # =========================================================
    #  MEMBER-STYLE VISIBILITY HELPERS
    # =========================================================
    def _get_period_end_date(self, report_type, raw_label):
        raw = str(raw_label or "").strip()
        if not raw:
            return None

        try:
            if report_type == "weekly":
                year_str, week_str = raw.split("-")
                year = int(year_str)
                week = int(week_str)
                return date.fromisocalendar(year, week, 7)

            if report_type == "monthly":
                year_str, month_str = raw.split("-")
                year = int(year_str)
                month = int(month_str)
                last_day = monthrange(year, month)[1]
                return date(year, month, last_day)

            if report_type == "yearly":
                year = int(raw)
                return date(year, 12, 31)

        except Exception:
            return None

        return None

    def _can_view_period(self, report_type, raw_label, lock_date):
        if not lock_date:
            return False

        period_end = self._get_period_end_date(report_type, raw_label)
        if not period_end:
            return False

        return period_end <= lock_date

    # =========================================================
    #  CHURCH-INCOME SNAPSHOT
    #  MATCH WEEKLYREPORTVIEW BALANCE LOGIC
    # =========================================================
    def _zero_period_balance_payload(self):
        return {
            "unrestricted_income": Decimal("0.00"),
            "unrestricted_expenses": Decimal("0.00"),
            "unrestricted_balance": Decimal("0.00"),
            "total_restricted_income": Decimal("0.00"),
            "total_restricted_expenses": Decimal("0.00"),
            "total_restricted_balance": Decimal("0.00"),
            "overall_income": Decimal("0.00"),
            "overall_expenses": Decimal("0.00"),
            "overall_balance": Decimal("0.00"),
            "period_label": "",
            "raw_label": "",
            "sort_key": "",
        }

    def _get_church_income_snapshot(self, church_id, report_type, date_filter=""):
        """
        Use the same balance source as WeeklyReportView:
        Finance_PeriodBalancesSummary -> overall_balance

        If date_filter is supplied, use that exact visible period.
        If date_filter is blank, use the latest locked/visible period.
        """
        AccountingSettings = self._accounting_settings_model()
        settings_obj = AccountingSettings.objects.filter(church_id=church_id).first()
        lock_date = settings_obj.lock_date if settings_obj else None

        try:
            balance_rows = self.sp_all("Finance_PeriodBalancesSummary", [church_id, report_type])
        except Exception:
            return self._zero_period_balance_payload()

        visible_rows = []

        for r in balance_rows:
            sort_key = str(r[0] or "")
            raw_label = str(r[1] or "")
            display_label = self._format_period_label(report_type, raw_label)

            if raw_label and not self._can_view_period(report_type, raw_label, lock_date):
                continue

            payload = {
                "unrestricted_income": Decimal(str(r[2] or 0)),
                "unrestricted_expenses": Decimal(str(r[3] or 0)),
                "unrestricted_balance": Decimal(str(r[4] or 0)),
                "total_restricted_income": Decimal(str(r[5] or 0)),
                "total_restricted_expenses": Decimal(str(r[6] or 0)),
                "total_restricted_balance": Decimal(str(r[7] or 0)),
                "overall_income": Decimal(str(r[8] or 0)),
                "overall_expenses": Decimal(str(r[9] or 0)),
                "overall_balance": Decimal(str(r[10] or 0)),
                "period_label": display_label,
                "raw_label": raw_label,
                "sort_key": sort_key,
            }
            visible_rows.append(payload)

        if not visible_rows:
            return self._zero_period_balance_payload()

        if date_filter:
            for item in visible_rows:
                if item["period_label"] == date_filter:
                    return item
            return self._zero_period_balance_payload()

        visible_rows.sort(
            key=lambda x: self._get_period_end_date(report_type, x["raw_label"]) or date.min,
            reverse=True,
        )
        return visible_rows[0]

    # =========================================================
    #  NORMALIZE / COERCE REPORT TX TYPE
    # =========================================================
    def _normalize_report_tx_type(self, txn_type):
        tx = (txn_type or "").strip()
        key = tx.upper()

        aliases = {
            "TITHE": "Tithe",
            "OFFERING": "Offering",
            "UNRES_DONATION": "Unres_Donation",
            "UNRES_OTHER": "Unres_Other",
            "RES_DONATION": "Res_Donation",
            "RES_OTHER": "Res_Other",
            "GEN_EXPENSE": "Gen_Expense",
            "RES_EXPENSE": "Res_Expense",
            "TRANSFER_DEPOSIT": "Transfer_Deposit",
            "TRANSFER_WITHDRAW": "Transfer_Withdraw",
            "SYSTEM_BUDGETRELEASE": "System_BudgetRelease",
            "SYSTEM_BUDGETRETURN": "System_BudgetReturn",
        }
        return aliases.get(key, tx)

    def _is_budget_return_label(self, category_name: str) -> bool:
        c = (category_name or "").strip().lower()
        if not c:
            return False

        return (
            c == "budget return"
            or c.startswith("budget return:")
            or c.startswith("budget return -")
            or c.startswith("cash:budget return:")
            or c.startswith("bank:budget return:")
            or c.startswith("unposted:budget return:")
            or ":budget return:" in c
        )

    def _is_visible_budget_release_label(self, category_name: str) -> bool:
        c = (category_name or "").strip().lower()
        if not c:
            return False

        return (
            c in {
                "budget release - cash",
                "budget release - bank",
                "budget release (unposted)",
            }
            or c.startswith("cash:budget release:")
            or c.startswith("bank:budget release:")
            or c.startswith("unposted:budget release:")
            or ":budget release:" in c
        )

    def _coerce_report_tx_type(self, txn_type: str, category_name: str) -> str:
        """
        Budget Return belongs to General Income (Unrestricted).
        Visible Budget Release stays as restricted expense.
        """
        tx = self._normalize_report_tx_type(txn_type)

        if self._is_budget_return_label(category_name):
            return "Unres_Other"

        if self._is_visible_budget_release_label(category_name):
            return "Res_Expense"

        return tx

    # =========================================================
    #  DEFENSIVE DETECTORS
    # =========================================================
    def _looks_like_transfer(self, category_name: str) -> bool:
        c = (category_name or "").strip().lower()

        return (
            c.startswith("bank depos")
            or "bank deposit" in c
            or c.startswith("bank withdr")
            or "bank withdraw" in c
            or "bank withdrawal" in c
            or "transfer to bank" in c
            or "transfer from bank" in c
            or "cash to bank" in c
            or "bank to cash" in c
        )

    def _looks_like_internal_budget_expense(self, category_name: str) -> bool:
        """
        Exclude only true internal/system budget rows.

        KEEP as visible rows:
        - Budget Release (Unposted)
        - Budget Release - Cash
        - Budget Release - Bank
        - Budget Return rows
        """
        c = (category_name or "").strip().lower()

        if self._is_visible_budget_release_label(category_name):
            return False

        if self._is_budget_return_label(category_name):
            return False

        return c in {
            "budget release",
            "system budget release",
            "system budget return",
        }

    def _should_skip_detailed_row(self, txn_type: str, category_name: str) -> bool:
        tx = self._coerce_report_tx_type(txn_type, category_name)

        # Budget return is visible unrestricted income, never skip it here
        if self._is_budget_return_label(category_name):
            return False

        if tx in {
            "Transfer_Deposit",
            "Transfer_Withdraw",
            "System_BudgetRelease",
            "System_BudgetReturn",
        }:
            return True

        if tx in {"Gen_Expense", "Res_Expense"}:
            if self._looks_like_transfer(category_name):
                return True
            if self._looks_like_internal_budget_expense(category_name):
                return True

        return False

    # =========================================================
    #  MERGE SAME-NAME ROWS
    # =========================================================
    def _append_or_merge_amount(self, bucket, name, amount):
        clean_name = str(name or "").strip()

        for item in bucket:
            if item["name"] == clean_name:
                item["amount"] += amount
                return

        bucket.append({
            "name": clean_name,
            "amount": amount,
        })

    # =========================================================
    #  LIQUIDATION BUILDER (MEMBER-SCOPE STYLE)
    # =========================================================
    def _build_member_scope_liquidation_context(self, church_id):
        AccountingSettings = self._accounting_settings_model()

        settings_obj = AccountingSettings.objects.filter(church_id=church_id).first()
        lock_date = settings_obj.lock_date if settings_obj else None

        report_type = (self.request.GET.get("report_type") or "weekly").strip().lower()
        date_filter = (self.request.GET.get("date_filter") or "").strip()

        if report_type == "monthly":
            detailed_sp = "Finance_MonthlyDetailedReport"
            report_title = "Monthly Financial Report"
        elif report_type == "yearly":
            detailed_sp = "Finance_YearlyDetailedReport"
            report_title = "Yearly Financial Report"
        else:
            report_type = "weekly"
            detailed_sp = "Finance_WeeklyDetailedReport"
            report_title = "Weekly Financial Report"

        balances_sp = "Finance_PeriodBalancesSummary"
        restricted_breakdown_sp = "Finance_RestrictedFunds_ByPeriod"
        bank_cashflow_sp = "Finance_BankCashFlow_ByPeriod"
        restricted_net_balance_sp = "Finance_RestrictedDonationsNetBalance"

        raw_data = self.sp_all(detailed_sp, [church_id])
        balance_rows = self.sp_all(balances_sp, [church_id, report_type])
        restricted_rows = self.sp_all(restricted_breakdown_sp, [church_id, report_type])
        bank_rows = self.sp_all(bank_cashflow_sp, [church_id, report_type])
        restricted_net_rows = self.sp_all(restricted_net_balance_sp, [church_id])

        restricted_map = defaultdict(list)
        for r in restricted_rows:
            sk = str(r[0] or "")
            restricted_map[sk].append({
                "category": str(r[1] or ""),
                "income": Decimal(str(r[2] or 0)),
                "expenses": Decimal(str(r[3] or 0)),
                "balance": Decimal(str(r[4] or 0)),
            })

        balance_by_sortkey = {}
        balance_by_label = {}

        for r in balance_rows:
            sort_key = str(r[0] or "")
            raw_label = str(r[1] or "")
            display_label = self._format_period_label(report_type, raw_label)

            payload = {
                "unrestricted_income": Decimal(str(r[2] or 0)),
                "unrestricted_expenses": Decimal(str(r[3] or 0)),
                "unrestricted_balance": Decimal(str(r[4] or 0)),
                "total_restricted_income": Decimal(str(r[5] or 0)),
                "total_restricted_expenses": Decimal(str(r[6] or 0)),
                "total_restricted_balance": Decimal(str(r[7] or 0)),
                "overall_income": Decimal(str(r[8] or 0)),
                "overall_expenses": Decimal(str(r[9] or 0)),
                "overall_balance": Decimal(str(r[10] or 0)),
                "restricted_funds": [],
            }

            if sort_key:
                balance_by_sortkey[sort_key] = payload
            if display_label:
                balance_by_label[display_label] = payload

        bank_by_sortkey = {}
        bank_by_label = {}

        for r in bank_rows:
            sk = str(r[0] or "")
            raw_label = str(r[1] or "")
            display_label = self._format_period_label(report_type, raw_label)

            deposits = Decimal(str(r[2] or 0))
            withdrawals = Decimal(str(r[3] or 0))

            bank_payload = {
                "deposits": deposits,
                "withdrawals": withdrawals,
                "net_to_physical_cash": withdrawals - deposits,
                "net_to_bank": deposits - withdrawals,
            }

            if sk:
                bank_by_sortkey[sk] = bank_payload
            if display_label:
                bank_by_label[display_label] = bank_payload

        report = defaultdict(
            lambda: {
                "tithes": Decimal("0.00"),
                "offering": Decimal("0.00"),
                "unres_donations": [],
                "total_unres_donations": Decimal("0.00"),
                "unres_other": [],
                "total_unres_other": Decimal("0.00"),
                "res_donations": [],
                "total_res_donations": Decimal("0.00"),
                "res_other": [],
                "total_res_other": Decimal("0.00"),
                "gen_expenses": [],
                "total_gen_expenses": Decimal("0.00"),
                "res_expenses": [],
                "total_res_expenses": Decimal("0.00"),
            }
        )

        available_periods = []
        seen_sort_keys = set()
        label_to_sortkey = {}
        sortkey_to_rawlabel = {}

        for source_rows in (raw_data, balance_rows, bank_rows):
            for row in source_rows:
                sort_key = str(row[0] or "") if len(row) > 0 else ""
                raw_label = str(row[1] or "") if len(row) > 1 else ""

                if sort_key and raw_label:
                    sortkey_to_rawlabel[sort_key] = raw_label

                self._register_period(
                    row[0] if len(row) > 0 else None,
                    row[1] if len(row) > 1 else None,
                    available_periods,
                    seen_sort_keys,
                    label_to_sortkey,
                    report_type,
                )

        filtered_periods = []
        filtered_label_to_sortkey = {}

        for period_label in available_periods:
            sort_key = label_to_sortkey.get(period_label)
            raw_label = sortkey_to_rawlabel.get(sort_key, "")

            if self._can_view_period(report_type, raw_label, lock_date):
                filtered_periods.append(period_label)
                filtered_label_to_sortkey[period_label] = sort_key

        available_periods = filtered_periods
        label_to_sortkey = filtered_label_to_sortkey

        if date_filter and date_filter not in available_periods:
            messages.warning(
                self.request,
                "That report period is not yet available because accounting for that period is not locked yet."
            )
            date_filter = ""

        for row in raw_data:
            sort_key = str(row[0] or "")
            raw_period_label = str(row[1] or "")
            display_period_label = self._format_period_label(report_type, raw_period_label)

            raw_txn_type = row[2] if len(row) > 2 else ""
            category = str(row[3] or "") if len(row) > 3 else ""
            amount = Decimal(str(row[4] or 0)) if len(row) > 4 else Decimal("0.00")

            txn_type = self._coerce_report_tx_type(raw_txn_type, category)

            if date_filter and date_filter != display_period_label:
                continue

            if self._should_skip_detailed_row(txn_type, category):
                continue

            d = report[sort_key]

            if txn_type == "Tithe":
                d["tithes"] += amount

            elif txn_type == "Offering":
                d["offering"] += amount

            elif txn_type == "Unres_Donation":
                self._append_or_merge_amount(d["unres_donations"], category, amount)
                d["total_unres_donations"] += amount

            elif txn_type == "Unres_Other":
                self._append_or_merge_amount(d["unres_other"], category, amount)
                d["total_unres_other"] += amount

            elif txn_type == "Res_Donation":
                self._append_or_merge_amount(d["res_donations"], category, amount)
                d["total_res_donations"] += amount

            elif txn_type == "Res_Other":
                self._append_or_merge_amount(d["res_other"], category, amount)
                d["total_res_other"] += amount

            elif txn_type == "Gen_Expense":
                self._append_or_merge_amount(d["gen_expenses"], category, amount)
                d["total_gen_expenses"] += amount

            elif txn_type == "Res_Expense":
                self._append_or_merge_amount(d["res_expenses"], category, amount)
                d["total_res_expenses"] += amount

        restricted_income_updates = []
        total_restricted_collected = Decimal("0.00")
        total_restricted_spent = Decimal("0.00")
        total_restricted_balance = Decimal("0.00")

        for r in restricted_net_rows:
            category_name = str(r[0] or "")
            total_collected = Decimal(str(r[1] or 0))
            total_spent = Decimal(str(r[2] or 0))
            current_balance = Decimal(str(r[3] or 0))

            restricted_income_updates.append({
                "category": category_name,
                "total_collected": total_collected,
                "total_spent": total_spent,
                "current_balance": current_balance,
            })

            total_restricted_collected += total_collected
            total_restricted_spent += total_spent
            total_restricted_balance += current_balance

        ZERO_BAL = {
            "unrestricted_income": Decimal("0.00"),
            "unrestricted_expenses": Decimal("0.00"),
            "unrestricted_balance": Decimal("0.00"),
            "total_restricted_income": Decimal("0.00"),
            "total_restricted_expenses": Decimal("0.00"),
            "total_restricted_balance": Decimal("0.00"),
            "overall_income": Decimal("0.00"),
            "overall_expenses": Decimal("0.00"),
            "overall_balance": Decimal("0.00"),
            "restricted_funds": [],
        }

        ZERO_BANK = {
            "deposits": Decimal("0.00"),
            "withdrawals": Decimal("0.00"),
            "net_to_physical_cash": Decimal("0.00"),
            "net_to_bank": Decimal("0.00"),
        }

        final_report = []

        for period_label in available_periods:
            if date_filter and date_filter != period_label:
                continue

            sort_key = label_to_sortkey.get(period_label)
            if not sort_key:
                continue

            d = report.get(sort_key) or report[sort_key]

            total_general_income = (
                d["tithes"]
                + d["offering"]
                + d["total_unres_donations"]
                + d["total_unres_other"]
            )

            total_restricted_income = d["total_res_donations"] + d["total_res_other"]
            total_period_income = total_general_income + total_restricted_income
            total_real_expenses = d["total_gen_expenses"] + d["total_res_expenses"]
            net_fund_flow = total_period_income - total_real_expenses

            bank_payload = (
                bank_by_sortkey.get(sort_key)
                or bank_by_label.get(period_label)
                or ZERO_BANK
            )

            deposits = Decimal(str(bank_payload["deposits"] or 0))
            withdrawals = Decimal(str(bank_payload["withdrawals"] or 0))
            net_to_physical_cash = Decimal(str(bank_payload["net_to_physical_cash"] or 0))
            net_to_bank = Decimal(str(bank_payload["net_to_bank"] or 0))

            period_physical_cash_change = net_fund_flow + net_to_physical_cash

            base_balances = (
                balance_by_sortkey.get(sort_key)
                or balance_by_label.get(period_label)
                or copy.deepcopy(ZERO_BAL)
            )

            true_balances = copy.deepcopy(base_balances)
            true_balances["restricted_funds"] = restricted_map.get(sort_key, [])

            final_report.append({
                "week": period_label,
                "data": d,
                "bank": {
                    "deposits": deposits,
                    "withdrawals": withdrawals,
                    "net_to_physical_cash": net_to_physical_cash,
                    "net_to_bank": net_to_bank,
                },
                "summary": {
                    "total_general_income": total_general_income,
                    "total_restricted_income": total_restricted_income,
                    "total_weekly_income": total_period_income,
                    "total_expenses": total_real_expenses,
                    "total_real_expenses": total_real_expenses,
                    "net_fund_flow": net_fund_flow,
                    "weekly_cash_on_hand": net_fund_flow,
                    "weekly_cash_on_hand_change": net_fund_flow,
                    "total_bank_deposits": deposits,
                    "total_bank_withdrawals": withdrawals,
                    "net_transfer_to_bank": net_to_bank,
                    "net_transfer_to_physical_cash": net_to_physical_cash,
                    "weekly_physical_cash_change": period_physical_cash_change,
                },
                "balances": true_balances,
            })

        return {
            "weekly_report": final_report,
            "available_periods": available_periods,
            "current_report_type": report_type,
            "current_filter": date_filter,
            "accounting_lock_date": lock_date,
            "restricted_income_updates": restricted_income_updates,
            "restricted_income_summary": {
                "total_collected": total_restricted_collected,
                "total_spent": total_restricted_spent,
                "total_balance": total_restricted_balance,
            },
            "report_title": report_title,
        }

    # =========================================================
    #  ATTACH SELECTED LIQUIDATION TO SAME PAGE
    # =========================================================
    def _attach_selected_liquidation(self, context, churches, latest_request_by_church):
        RequestModel = self._request_model()

        selected_church_id = (self.request.GET.get("selected_church") or "").strip()
        if not selected_church_id:
            return

        try:
            selected_church_id = int(selected_church_id)
        except (TypeError, ValueError):
            messages.error(self.request, "Invalid selected church.")
            return

        selected_church = churches.filter(id=selected_church_id).first()
        if not selected_church:
            messages.error(self.request, "Selected church is invalid.")
            return

        access_req = latest_request_by_church.get(selected_church.id)
        if not access_req or access_req.status != RequestModel.STATUS_APPROVED:
            messages.error(
                self.request,
                f"You do not have approved liquidation access for {selected_church.name}."
            )
            return

        report_context = self._build_member_scope_liquidation_context(selected_church.id)
        context.update(report_context)
        context["show_liquidation"] = True
        context["selected_church_id"] = selected_church.id
        context["selected_church_name"] = selected_church.name

    # =========================================================
    #  MAIN CONTEXT
    # =========================================================
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        RequestModel = self._request_model()
        Church = self._church_model()

        denom = getattr(self.request.user, "denomination", None)
        context["daily_summary"] = []
        context["denomination_name"] = getattr(denom, "name", "")
        context["show_liquidation"] = False
        context["selected_church_id"] = None
        context["selected_church_name"] = ""
        context["weekly_report"] = []
        context["available_periods"] = []
        context["current_report_type"] = (self.request.GET.get("report_type") or "weekly").strip().lower()
        context["current_filter"] = (self.request.GET.get("date_filter") or "").strip()
        context["restricted_income_updates"] = []
        context["restricted_income_summary"] = {
            "total_collected": Decimal("0.00"),
            "total_spent": Decimal("0.00"),
            "total_balance": Decimal("0.00"),
        }
        context["report_title"] = "Financial Report"

        if not denom:
            return context

        churches = Church.objects.filter(denomination=denom).order_by("name")
        latest_request_by_church = self._get_latest_requests_map(churches)

        formatted_rows = []
        report_type = context["current_report_type"]
        date_filter = context["current_filter"]

        for church in churches:
            row = self._get_unrestricted_net_row(church.id)

            balance_payload = self._get_church_income_snapshot(
                church_id=church.id,
                report_type=report_type,
                date_filter=date_filter,
            )

            access_req = latest_request_by_church.get(church.id)
            request_status = access_req.status if access_req else None

            church_income_amount = balance_payload["overall_balance"]
            unrestricted_balance_amount = balance_payload["unrestricted_balance"]
            restricted_balance_amount = balance_payload["total_restricted_balance"]

            formatted_rows.append({
                "ChurchID": church.id,
                "ChurchName": church.name,

                # legacy unrestricted detail columns
                "TotalTithes": self.money(row[0] if len(row) > 0 else 0),
                "TotalOfferings": self.money(row[1] if len(row) > 1 else 0),
                "TotalUnrestrictedDonations": self.money(row[2] if len(row) > 2 else 0),
                "TotalUnrestrictedOtherIncome": self.money(row[3] if len(row) > 3 else 0),
                "TotalBudgetReturnsToUnrestricted": self.money(row[4] if len(row) > 4 else 0),
                "TotalUnrestrictedExpenses": self.money(row[6] if len(row) > 6 else 0),
                "NetGrandTotalUnrestricted": self.money(row[7] if len(row) > 7 else 0),

                # authoritative church-income values
                "ChurchIncome": self.money(church_income_amount),
                "RestrictedBalance": self.money(restricted_balance_amount),
                "UnrestrictedBalance": self.money(unrestricted_balance_amount),
                "CurrentPeriodLabel": balance_payload.get("period_label", ""),

                # compatibility mapping
                "GrandTotalUnrestricted": self.money(church_income_amount),

                "request_status": request_status,
                "can_view_liquidation": request_status == RequestModel.STATUS_APPROVED,
                "is_pending": request_status == RequestModel.STATUS_PENDING,
                "is_rejected": request_status == RequestModel.STATUS_REJECTED,
                "is_closed": request_status == RequestModel.STATUS_CLOSED,
            })

        context["daily_summary"] = formatted_rows
        self._attach_selected_liquidation(context, churches, latest_request_by_church)
        return context


@login_required
@require_POST
def revoke_membership(request, app_id):
    application = get_object_or_404(ChurchApplication, id=app_id)
    reason = request.POST.get('revocation_reason')

    if not hasattr(request.user, 'church') or not request.user.church:
        messages.error(request, "Unauthorized access.")
        return redirect('Church:apply_denomination')

    if application.church != request.user.church:
        messages.error(request, "You cannot revoke a membership that isn't yours.")
        return redirect('Church:apply_denomination')

    if not reason or not reason.strip():
        messages.error(request, "You must provide a reason for revoking membership.")
        return redirect('Church:apply_denomination')

    if application.status == 'Approved':
        application.revoke(request.user, reason)
        messages.success(request, "Membership revoked successfully.")
    else:
        messages.error(request, "Cannot revoke. This application is not currently active.")

    return redirect('Church:apply_denomination')

class MyChurchUpdateView(LoginRequiredMixin, IsChurchAdmin, UpdateView):
    model = Church
    form_class = ChurchProfileForm
    template_name = 'my_church_edit.html'
    context_object_name = 'church_obj'
    success_url = reverse_lazy('Church:my_church_edit')

    def get_object(self, queryset=None):
        return self.request.user.church

    def form_valid(self, form):
        messages.success(self.request, 'Church information updated successfully.')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['denomination'] = self.object.denomination
        return context



class MyDenominationUpdateView(LoginRequiredMixin, IsDenominationAdmin, UpdateView):
    model = Denomination
    form_class = DenominationForm
    template_name = 'my_denomination_edit.html'
    context_object_name = 'denomination_obj'
    success_url = reverse_lazy('Church:my_denomination_edit')

    def get_object(self, queryset=None):
        return self.request.user.denomination

    def form_valid(self, form):
        messages.success(self.request, 'Denomination information updated successfully.')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['denomination'] = self.object
        return context