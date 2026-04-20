# Church/urls.py
from django.urls import path
from .views import (
    ChurchSignupView,
    DenominationSignupView,
    ApplyToDenominationView,
    DenominationApplicationListView,
    ApplicationActionView,
    DenominationFinanceOverview,
    VerifyEmailView, MyDenominationUpdateView # <--- Added this (New)
    # ActivateAccountView <--- Removed this (Old)
)
from .views import MyChurchUpdateView
from .views import cancel_application, revoke_membership

app_name = 'Church'

urlpatterns = [
    # --- Signup Views ---
    path('signup/church/', ChurchSignupView.as_view(), name='church_signup'),
    path('signup/denomination/', DenominationSignupView.as_view(), name='denomination_signup'),

    # --- Verification View (New OTP Page) ---
    path('verify-email/', VerifyEmailView.as_view(), name='verify_email'),

    # --- Application Management ---
    path('apply-denomination/', ApplyToDenominationView.as_view(), name='apply_denomination'),
    path('applications/', DenominationApplicationListView.as_view(), name='denomination_applications'),
    path('application/<int:pk>/action/', ApplicationActionView.as_view(), name='application_action'),
    path('application/<int:app_id>/cancel/', cancel_application, name='cancel_application'),
    path('application/<int:app_id>/revoke/', revoke_membership, name='revoke_membership'),

    # --- Finance ---
    path('finance-overview/', DenominationFinanceOverview.as_view(), name='denomination_finance_overview'),

    # Note: I removed the old 'activate/<uidb64>/<token>/' path
    # because you are now using the 'verify-email/' code entry page instead.
    path('my-church/edit/', MyChurchUpdateView.as_view(), name='my_church_edit'),

path(
    'my-denomination/edit/',
    MyDenominationUpdateView.as_view(),
    name='my_denomination_edit'
),
]