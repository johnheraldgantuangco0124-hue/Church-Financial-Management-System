# myapp/urls.py

from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static
from .views import HomeView
from .views import api_get_ministry_stats_year
from .views import (RegisterView, CustomLoginView, UnifiedIncomeEntryPageView, ChurchAdminLiquidationRequestsView,
                    CustomLogoutView,ConfirmDonationsView,LandingView,ManageExpenseCategoriesView,
                    ReviewExpensesView,AddDonationsView,
                    SelectExpensesNumberView, TitheCreateView, ReviewTitheView, ExpenseFraudDetectionSettingsView,
                    AddExpenseView, TreasurerLoginView,
                    MemberLoginView,FinanceOverview, CustomUserDetailView, CustomUserUpdateView, FinanceChartView, ChangePasswordView,TemplateView)
from django.urls import path
from django.urls import path
from .views import WeeklyReportView, UploadTempReceiptView, OpenAIPrescriptiveBudgetOptimizersView, api_run_optimizer_openai
from .views import MemberEditView,ForgotPasswordView, TreasurerEditView,MonthlyFinancialSummaryView, AdminLoginView, FinancialOverviewView
from .views import RoleAwareLoginView, CustomLogoutView, BankWithdrawView
from .views import FinancialReportView
from .views import SendThankYouLetterView
from .views import AddDonationCategoryView
from .views import DeleteExpenseView
from .views import ReleaseBudgetDeclineView, ResetPasswordConfirmView
from .views import BankSettingsView, DonationReceiptView
from .views import PastorEditView
from .views import (
    # ... your other views ...
    UnifiedOfferingView,
    UnifiedOfferingReviewView, MonthlyYearlyAnalysisView
)
from .views import (
    ChurchAccountListView,
    ToggleChurchAccountStatusView
)
from .views import (
    # Ministries
    MinistryManageView,
    MinistryToggleActiveView,
    MinistryDeleteView, ReleaseBudgetView,ReleaseBudgetPerformView,PrescriptiveBudgetOptimizerView,
    # Budgets flow
    BudgetManageView,
BankMovementReviewView,
    BudgetRequest,
    BudgetReleaseView,
    BudgetExpenseView,
    BudgetReleaseView,
    BudgetReleaseApproveView,
    BudgetReleaseDeclineView,
DonationListView,
ManageBankView,
    BankDepositView,
    BankMovementCreateView,
    BankMovementHistoryView, DenominationAdminHomeView

)
from .views import (
    PendingReferenceCreateView,
    PendingReferenceListView,
    ApproveReferenceView,
    ReferenceHistoryView,
BudgetRequestApprovalView, AnalyticsDashboardView, # <--- The new Graphs page
)
from .views import BudgetSummaryView
from .views import ThankYouLetterView
from .views import ReferenceHistoryViewMember
from .views import UnifiedOfferingView
urlpatterns = [


    path('logout/', CustomLogoutView.as_view(), name='logout'),

    path('manage/ministries/', MinistryManageView.as_view(), name='ministries_manage'),
    path('manage/ministries/<int:pk>/toggle/', MinistryToggleActiveView.as_view(), name='ministry_toggle'),
    path('manage/ministries/<int:pk>/delete/', MinistryDeleteView.as_view(), name='ministry_delete'),
    path('manage/ministries/edit/<int:pk>/', views.MinistryEditView.as_view(), name='ministry_edit'),

    # Budgeting flow
    path('manage/budgets/', BudgetManageView.as_view(), name='budgets_manage'),
    path('manage/budgets/edit/<int:pk>/', views.BudgetEditView.as_view(), name='budget_edit'),
    path('manage/budgets/release/', BudgetReleaseView.as_view(), name='budget_release'),
    path('manage/budgets/release/<int:pk>/approve/', BudgetReleaseApproveView.as_view(), name='budget_release_approve'),
    path('manage/budgets/release/<int:pk>/decline/', BudgetReleaseDeclineView.as_view(), name='budget_release_decline'),
    path('manage/budgets/expense/delete/<int:pk>/', DeleteExpenseView.as_view(), name='delete_expense'),
    path('manage/budgets/released/', ReleaseBudgetView.as_view(), name='release_budget'),
    path('manage/budgets/expense/', BudgetExpenseView.as_view(), name='budget_expense'),
    # Backward compatibility: old endpoints now redirect to /login
    path('manage/budgets/released/<int:pk>/release/', ReleaseBudgetPerformView.as_view(),
         name='release_budget_release'),
    path('manage/budgets/released/decline/<int:pk>/', ReleaseBudgetDeclineView.as_view(), name='release_budget_decline'),


    path('Budget Request/', BudgetRequest.as_view(), name='budget_request'),

    path('optimizer/', PrescriptiveBudgetOptimizerView.as_view(), name='optimizer'),

    path('register/', RegisterView.as_view(), name='register'),
    path('login/', CustomLoginView.as_view(), name='login'),
    path('home/', HomeView.as_view(), name='home'),

    path('logout/', CustomLogoutView.as_view(), name='logout'),

    path('tithes/', TitheCreateView.as_view(), name='add_tithe'),
    path('review-tithes/', ReviewTitheView.as_view(), name='review_tithe'),

path('add-offerings/', UnifiedOfferingView.as_view(), name='add_offerings'),

    # 2. Review Page for Batch (Grid)
    path('add-offerings/', UnifiedOfferingView.as_view(), name='add_offerings'),

    # 2. The Unified Review Page (Handles both)
    # Note: We keep the name 'review_offerings' because views.py redirects to this specific name.
    path('offering/review/', UnifiedOfferingReviewView.as_view(), name='review_offerings'),

    path('reports/', FinancialReportView.as_view(), name='financial_reports'),

    path('financial/weekly-report/', WeeklyReportView.as_view(), name='weekly_financial_report'),

path("Register/income/scan-ocr/", views.scan_other_income_api, name="scan_other_income_api"),


    path("add-expenses/", AddExpenseView.as_view(), name="add_expenses"),
    path("review-expenses/", ReviewExpensesView.as_view(), name="review_expenses"),
path('expenses/categories/', ManageExpenseCategoriesView.as_view(), name='manage_expense_categories'),

path('upload-temp-receipt/', UploadTempReceiptView.as_view(), name='upload_temp_receipt'),

path('session-test/', views.session_test, name='session_test'),

path('donations/manage-types/', AddDonationCategoryView.as_view(), name='add_donation_category'),
    path('add-donations', AddDonationsView.as_view(), name='add_donations'),
    path('confirm-donations/', ConfirmDonationsView.as_view(), name='confirm_donations'),

    path('donations/history/', DonationListView.as_view(), name='donation_history'),
    path('donation/receipt/<int:pk>/', DonationReceiptView.as_view(), name='donation_receipt_print'),

    path('income/manage-types/', views.ManageIncomeCategoriesView.as_view(), name='manage_income_categories'),
    path('income/add/', views.AddOtherIncomeView.as_view(), name='add_other_income'),
    path('income/review/', views.ReviewOtherIncomeView.as_view(), name='review_other_income'),
    path('income/history/', views.OtherIncomeListView.as_view(), name='other_income_list'),


    path('landing-view/', LandingView.as_view(), name='landing-view'),

    path('treasurer-login/', TreasurerLoginView.as_view(), name='treasurer_login'),
    path('member-login/', MemberLoginView.as_view(), name='member_login'),


    path('finance/', FinanceOverview.as_view(), name='finance'),

    path('logout/', CustomLogoutView.as_view(), name='logout'),

    path('user_detail/', CustomUserDetailView.as_view(), name='user_detail'),
    path('user_edit/', CustomUserUpdateView.as_view(), name='user_edit'),

    path("accounts/", ChurchAccountListView.as_view(), name="church-account-list"),
    path("accounts/<int:pk>/toggle-status/", ToggleChurchAccountStatusView.as_view(),
         name="toggle-church-account-status"),

    path("accounts/pastor/<int:pk>/edit/", PastorEditView.as_view(), name="pastor-edit"),
    path("accounts/member/<int:pk>/edit/", MemberEditView.as_view(), name="member-edit"),
    path("accounts/treasurer/<int:pk>/edit/", TreasurerEditView.as_view(), name="treasurer-edit"),

    path('financial-overview/', FinancialOverviewView.as_view(), name='financial_overview'),

    path('monthly-summary/', MonthlyFinancialSummaryView.as_view(), name='monthly_summary'),

    path('finance/chart/', FinanceChartView.as_view(), name='finance_chart'),

    path('financial-overview/', FinancialOverviewView.as_view(), name='financial_overview'),

path('analytics/', AnalyticsDashboardView.as_view(), name='analytics_dashboard'),

path('api/run-optimizer/', views.api_run_optimizer, name='api_run_optimizer'),
    path('api/historical-stats/', views.api_get_historical_stats, name='api_get_historical_stats'),

    path('change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('change-password-done/', TemplateView.as_view(template_name='change_password_done.html'), name='change_password_done'),

    path('references/submit/', PendingReferenceCreateView.as_view(), name='reference_submit'),

    # 2. Approve pending submissions (list)
    path('references/pending/', PendingReferenceListView.as_view(), name='reference_approve_list'),

    # Approve action (POST)
    path('references/approve/<int:pk>/', ApproveReferenceView.as_view(), name='reference_approve'),

    # 3. View pending + approved together
    path('references/history/', ReferenceHistoryView.as_view(), name='reference_history'),

    path('send-thank-you/', SendThankYouLetterView.as_view(), name='send_thank_you'),


    path('thank-you-letters/', ThankYouLetterView.as_view(), name='thank_you_letters'),

    path('reference-history/member/', ReferenceHistoryViewMember.as_view(), name='reference_history_member'),


path('analytics/optimizer/', views.PrescriptiveBudgetOptimizersView.as_view(), name='budget_optimizer'),

path("api/ministry-stats-year/", api_get_ministry_stats_year, name="api_get_ministry_stats_year"),


    # The API path stays the same
    path('api/run-optimizer/', views.api_run_optimizer, name='api_run_optimizer'),

    path('budget/release/', BudgetReleaseView.as_view(), name='budget_release'),

    # Logic Actions (POST only)
    path('budget/approve/<int:pk>/', BudgetReleaseApproveView.as_view(), name='budget_release_approve'),
    path('budget/decline/<int:pk>/', BudgetReleaseDeclineView.as_view(), name='budget_release_decline'),

    # The NEW Approval Page (GET)
path('budget/summary/', BudgetSummaryView.as_view(), name='budget_summary'),

    path('budget/review/<int:pk>/', BudgetRequestApprovalView.as_view(), name='budget_request_review'),


path('finance/bank/settings/', BankSettingsView.as_view(), name='bank_settings'),

    # 2. Bank Dashboard (Manage Balance & History)
    path('finance/bank/dashboard/', ManageBankView.as_view(), name='manage_bank'),

    # 3. Bank Deposit (Transactions)
    path('finance/bank/deposit/', BankDepositView.as_view(), name='bank_deposit'),

    path("Register/finance/bank/withdraw/", BankWithdrawView.as_view(), name="bank_withdraw"),


path('forgot-password/', ForgotPasswordView.as_view(), name='forgot_password'),
    path('reset-password-confirm/', ResetPasswordConfirmView.as_view(), name='reset_password_confirm'),

path('accounting-lock/', views.AccountingLockView.as_view(), name='accounting_lock'),

path("bank-movement/add/", BankMovementCreateView.as_view(), name="add_bank_movement"),
    path("bank-movement/review/", BankMovementReviewView.as_view(), name="review_bank_movement"),
    path("bank-movement/history/", BankMovementHistoryView.as_view(), name="bank_movement_history"),

path("income/unified/", UnifiedIncomeEntryPageView.as_view(), name="unified_income_entry"),

path(
    "expense-fraud-detection-settings/",
    ExpenseFraudDetectionSettingsView.as_view(),
    name="expense_fraud_detection_settings",
),

path(
    "church-admin/liquidation-requests/",
    ChurchAdminLiquidationRequestsView.as_view(),
    name="church_admin_liquidation_requests",
),

path(
    "monthly-yearly-analysis/",
    MonthlyYearlyAnalysisView.as_view(),
    name="monthly_yearly_analysis",
),

path(
    "finance/prescriptive-optimizer/openai/",
    OpenAIPrescriptiveBudgetOptimizersView.as_view(),
    name="prescriptive_budget_optimizer_openai"
),
path(
    "api/optimizer/openai/",
    api_run_optimizer_openai,
    name="api_run_optimizer_openai"
),
path(
    "api/notifications/",
    views.api_get_notifications,
    name="api_get_notifications"
),
path("denomination/dashboard/", DenominationAdminHomeView.as_view(), name="denomination_dashboard")
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)