# myapp/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, UserChangeForm
from django.contrib.auth import get_user_model
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from django import forms
from django.db.models import Q
from django.forms import formset_factory
from .models import OtherIncome, OtherIncomeCategory
from .models import BankAccount
from .models import Expense, ExpenseCategory
from django.views.generic import ListView
from django.forms import modelformset_factory, BaseModelFormSet
from .models import AccountingSettings
import re
import uuid
import calendar
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import NON_FIELD_ERRORS
from django.utils import timezone
from .models import CustomUser
from django.core.exceptions import ValidationError
from decimal import Decimal, InvalidOperation
from .models import CustomUser, Donations, DonationCategory
from django import forms
from django.core.exceptions import ValidationError
from django.db import connection
from .models import PendingReference
from django.apps import apps
from .models import HomePageContent
from .models import (
    MinistryBudget, BudgetReleaseRequest,
    BudgetExpense, ReleasedBudget,  ApprovedReleaseRequest,   # ← add this
    ReleasedBudget,
)
from django.db import transaction
from django.utils import timezone

# ====== Import your models ======
from .models import (
    CashBankMovement,
    DonationCategory,
    OtherIncomeCategory,
    ExpenseCategory,
    CustomUser,
    Tithe,
    Offering,
    Donations,
    OtherIncome,
    Expense,
)




class CustomUserRegistrationForm(UserCreationForm):
    ALLOWED_USER_TYPES = (
        CustomUser.UserType.MEMBER,
        CustomUser.UserType.PASTOR,
        CustomUser.UserType.TREASURER,
    )

    middle_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    birthdate = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )

    province = forms.CharField(widget=forms.HiddenInput(), required=True)
    municipality_or_city = forms.CharField(widget=forms.HiddenInput(), required=True)
    barangay = forms.CharField(widget=forms.HiddenInput(), required=True)

    purok = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Purok 3'})
    )

    year_term = forms.ChoiceField(
        choices=[('', 'Select Year Term')] + list(CustomUser.YearTerm.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    organization = forms.ChoiceField(
        choices=[('', 'Select Organization')] + list(CustomUser.Organization.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control'})
    )

    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = [
            'username',
            'first_name',
            'middle_name',
            'last_name',
            'province',
            'municipality_or_city',
            'barangay',
            'purok',
            'birthdate',
            'email',
            'user_type',
            'year_term',
            'organization',
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'user_type': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('request_user', None)
        super().__init__(*args, **kwargs)

        self.fields['password1'].widget.attrs.update({'class': 'form-control'})
        self.fields['password2'].widget.attrs.update({'class': 'form-control'})

        self.fields['user_type'].choices = [
            ('', 'Select User Type'),
            *[
                (value, label)
                for value, label in CustomUser.UserType.choices
                if value in self.ALLOWED_USER_TYPES
            ]
        ]
        self.fields['user_type'].widget.attrs.update({'class': 'form-control'})

        # Assign creator's church as early as possible
        if self.request_user:
            if getattr(self.request_user, 'church_id', None):
                self.instance.church = self.request_user.church
            if getattr(self.request_user, 'denomination_id', None):
                self.instance.denomination = self.request_user.denomination

    def clean_user_type(self):
        user_type = self.cleaned_data.get('user_type')

        if not user_type:
            raise forms.ValidationError("Please select a User Type.")

        if user_type not in self.ALLOWED_USER_TYPES:
            raise forms.ValidationError("This user type is not allowed for registration.")

        return user_type

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()

        if not email:
            return email

        with connection.cursor() as cursor:
            cursor.execute("CALL CheckEmailExists(%s, @email_count)", [email])

            try:
                while True:
                    try:
                        cursor.fetchall()
                    except Exception:
                        pass
                    if not cursor.nextset():
                        break
            except Exception:
                pass

            cursor.execute("SELECT @email_count")
            result = cursor.fetchone()

        if result and int(result[0] or 0) > 0:
            raise forms.ValidationError(
                f"The email '{email}' is already registered. Please use a different one."
            )

        return email

    def clean(self):
        cleaned_data = super().clean()

        user_type = cleaned_data.get('user_type')
        year_term = cleaned_data.get('year_term')
        organization = cleaned_data.get('organization')

        if user_type == CustomUser.UserType.TREASURER:
            if not year_term:
                self.add_error('year_term', "Treasurer must select a Year Term.")
            cleaned_data['organization'] = None

        elif user_type == CustomUser.UserType.MEMBER:
            if not organization:
                self.add_error('organization', "Member must select an Organization.")
            cleaned_data['year_term'] = None

        elif user_type == CustomUser.UserType.PASTOR:
            cleaned_data['year_term'] = None
            cleaned_data['organization'] = None

        # Friendly validation before model.clean()
        if user_type in self.ALLOWED_USER_TYPES and not getattr(self.instance, 'church_id', None):
            self.add_error(
                None,
                "The selected account type must belong to a church, but the current logged-in account has no church assigned."
            )

        return cleaned_data

    def _post_clean(self):
        # Assign again right before model validation
        if self.request_user:
            if getattr(self.request_user, 'church_id', None):
                self.instance.church = self.request_user.church
            if getattr(self.request_user, 'denomination_id', None):
                self.instance.denomination = self.request_user.denomination

        super()._post_clean()

    def _update_errors(self, errors):
        """
        Prevent Django from crashing when model.clean() returns errors
        for fields not present on the form, مثل 'church'.
        Convert them into non-field errors instead.
        """
        if hasattr(errors, "error_dict"):
            normalized = {}

            for field, field_errors in errors.error_dict.items():
                target_field = field if field in self.fields else NON_FIELD_ERRORS
                normalized.setdefault(target_field, []).extend(field_errors)

            for field, field_errors in normalized.items():
                if field == NON_FIELD_ERRORS:
                    self.add_error(None, field_errors)
                else:
                    self.add_error(field, field_errors)
            return

        super()._update_errors(errors)

    def save(self, commit=True):
        user = super().save(commit=False)

        if self.request_user:
            if getattr(self.request_user, 'church_id', None):
                user.church = self.request_user.church
            if getattr(self.request_user, 'denomination_id', None):
                user.denomination = self.request_user.denomination

        user.email = (self.cleaned_data.get('email') or '').strip().lower()

        if user.user_type == CustomUser.UserType.TREASURER:
            user.organization = None
        elif user.user_type == CustomUser.UserType.MEMBER:
            user.year_term = None
        elif user.user_type == CustomUser.UserType.PASTOR:
            user.year_term = None
            user.organization = None

        if commit:
            user.save()

        return user

# ——— 2. General Edit Form (The one that caused the error) ———
class CustomUserForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        # CRITICAL FIX: 'age' is removed from here.
        # You cannot edit 'age' because it is calculated automatically.
        fields = [
            'first_name', 'middle_name', 'last_name',
            'birthdate', 'province', 'municipality_or_city',
            'barangay', 'purok', 'profile_picture'
        ]
        # Note: If you want to display age as read-only, you do that in the HTML template,
        # not in the form fields list.

class CustomUserLoginForm(AuthenticationForm):
    username = forms.CharField(label="Username")
    password = forms.CharField(label="Password", widget=forms.PasswordInput)

class TitheForm(forms.ModelForm):
    class Meta:
        model = Tithe
        fields = ['amount', 'date', 'description','file']

    date = forms.DateField(widget=forms.DateInput(attrs={
        'type': 'date',
        'class': 'form-control',  # Optional, you can add a class for styling
    }))

class OfferingForm(forms.ModelForm):
    date = forms.DateField(
        widget=forms.DateInput(attrs={
            "type": "date",
            "class": "form-control",
        })
    )

    class Meta:
        model = Offering
        fields = ["user", "amount", "date", "description", "proof_document"]
        widgets = {
            "user": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0.01",
            }),
            "description": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Enter description",
            }),
            "proof_document": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": ".jpg,.jpeg,.png,.pdf",
            }),
        }
        labels = {
            "user": "Member",
            "amount": "Amount",
            "date": "Date",
            "description": "Description",
            "proof_document": "Proof Document",
        }
        help_texts = {
            "proof_document": "Upload JPG, PNG, or PDF of the tally sheet, envelope summary, or deposit slip.",
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        self.fields["user"].required = False
        self.fields["description"].required = False
        self.fields["proof_document"].required = False

        if user and hasattr(user, "church") and user.church:
            self.fields["user"].queryset = CustomUser.objects.filter(
                church=user.church,
                user_type="Member"
            )
        else:
            self.fields["user"].queryset = CustomUser.objects.none()

class SelectExpensesNumberForm(forms.Form):
    number_of_expenses = forms.IntegerField(min_value=1, label="Number of Expenses")


class ExpenseCategoryForm(forms.ModelForm):
    # UI-only field (maps into restricted_source + restricted_category_id)
    restricted_fund_key = forms.ChoiceField(
        required=False,
        label="Restricted Fund",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = ExpenseCategory
        fields = [
            'name',
            'description',
            'is_transfer',
            'is_system',
            'is_restricted',
            'restricted_fund_key',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Utilities, Maintenance, Outreach'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional description...'
            }),
            'is_transfer': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_system': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_restricted': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Build restricted fund choices per church
        choices = [("", "— Select restricted fund —")]
        church = getattr(self.user, "church", None) if self.user else None

        if church:
            d_qs = DonationCategory.objects.filter(church=church, is_restricted=True).order_by("name")
            o_qs = OtherIncomeCategory.objects.filter(church=church, is_restricted=True).order_by("name")

            for d in d_qs:
                choices.append((f"D:{d.id}", f"[Donation] {d.name}"))
            for o in o_qs:
                choices.append((f"I:{o.id}", f"[Other Income] {o.name}"))

        self.fields["restricted_fund_key"].choices = choices

        # Prefill when editing an existing restricted expense category
        if self.instance and getattr(self.instance, "is_restricted", False):
            if self.instance.restricted_source == "DONATION" and self.instance.restricted_category_id:
                self.initial["restricted_fund_key"] = f"D:{int(self.instance.restricted_category_id)}"
            elif self.instance.restricted_source == "OTHER_INCOME" and self.instance.restricted_category_id:
                self.initial["restricted_fund_key"] = f"I:{int(self.instance.restricted_category_id)}"

    def clean(self):
        cleaned = super().clean()
        is_res = cleaned.get("is_restricted", False)
        key = (cleaned.get("restricted_fund_key") or "").strip()

        if is_res:
            if not key or ":" not in key:
                raise forms.ValidationError("Please select a restricted fund for this category.")

            prefix, raw_id = key.split(":", 1)
            try:
                fund_id = int(raw_id)
            except ValueError:
                raise forms.ValidationError("Invalid restricted fund selection.")

            if prefix == "D":
                cleaned["restricted_source"] = "DONATION"
            elif prefix == "I":
                cleaned["restricted_source"] = "OTHER_INCOME"
            else:
                raise forms.ValidationError("Invalid restricted fund selection.")

            cleaned["restricted_category_id"] = fund_id
        else:
            cleaned["restricted_source"] = None
            cleaned["restricted_category_id"] = None

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        cd = self.cleaned_data

        obj.is_restricted = cd.get("is_restricted", False)
        obj.restricted_source = cd.get("restricted_source")
        obj.restricted_category_id = cd.get("restricted_category_id")

        if commit:
            obj.save()
        return obj


# ==========================================
# Expense Form (keeps your filtering + improves labels)
# ==========================================
BLOCKED_EXPENSE_CATEGORIES = [
    "Bank Deposit",
    "Bank Withdraw",
    "Budget Release - Bank",
    "Budget Release - Cash",
]


class ExpenseForm(forms.ModelForm):
    category = forms.ModelChoiceField(
        queryset=ExpenseCategory.objects.none(),
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Expense Category",
        empty_label="Select Category",
    )

    class Meta:
        model = Expense
        # include vendor so it is accepted and saved
        fields = ["amount", "category", "file", "expense_date", "description", "vendor"]
        widgets = {
            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "0.00",
                    "step": "0.01",
                }
            ),
            "file": forms.FileInput(attrs={"class": "form-control-file"}),
            "expense_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "description": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Optional details (e.g. Invoice #102)",
                }
            ),
            "vendor": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Vendor or payee name (optional)",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        queryset = ExpenseCategory.objects.all()

        if user and hasattr(user, "church") and user.church:
            queryset = queryset.filter(church=user.church)

        queryset = queryset.exclude(
            name__in=BLOCKED_EXPENSE_CATEGORIES
        ).order_by("name")

        self.fields["category"].queryset = queryset

        def label(cat):
            return f"{cat.name} (Restricted)" if getattr(cat, "is_restricted", False) else cat.name

        self.fields["category"].label_from_instance = label

    def clean_category(self):
        category = self.cleaned_data.get("category")

        if category and category.name in BLOCKED_EXPENSE_CATEGORIES:
            raise forms.ValidationError("This category is not allowed for expenses.")

        return category

class SelectDonationsNumberForm(forms.Form):
    number_of_donations = forms.IntegerField(min_value=1, label="Number of Donations")


class DonationsForm(forms.ModelForm):
    # Non-model helper fields
    run_ocr = forms.BooleanField(
        required=False,
        initial=False,
        label="Run OCR",
        help_text="Extract details from the uploaded receipt (image/PDF)."
    )

    ocr_text = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    donor_type = forms.ChoiceField(
        choices=Donations.DonorType.choices,
        required=True,
        initial=Donations.DonorType.ANONYMOUS,
        label="Donor Type",
        widget=forms.Select(attrs={
            "class": "form-select donor-type-select"
        })
    )

    class Meta:
        model = Donations
        fields = [
            "amount",
            "donations_type",
            "other_donations_type",
            "donations_date",
            "donor_type",
            "donor",
            "user",
            "file",
            "receipt_image",
        ]

    donations_type = forms.ModelChoiceField(
        queryset=DonationCategory.objects.none(),
        label="Donation Category",
        empty_label="Select Category...",
        widget=forms.Select(attrs={"class": "form-select"})
    )

    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        label="Amount",
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "placeholder": "0.00",
            "step": "0.01",
            "min": "0"
        })
    )

    donor = forms.CharField(
        required=False,
        label="Non-member Name",
        widget=forms.TextInput(attrs={
            "class": "form-control donor-name-input",
            "placeholder": "Enter non-member donor name"
        })
    )

    other_donations_type = forms.CharField(
        required=False,
        label="Description / Note",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Specific details (if needed)"
        })
    )

    donations_date = forms.DateField(
        label="Date",
        widget=forms.DateInput(attrs={
            "type": "date",
            "class": "form-control"
        })
    )

    user = forms.ModelChoiceField(
        queryset=forms.models.ModelChoiceField(queryset=None).queryset,
        required=False,
        label="Member / Pastor / Treasurer",
        widget=forms.Select(attrs={
            "class": "form-select donor-user-select"
        })
    )

    file = forms.FileField(
        required=False,
        label="Receipt File",
        widget=forms.ClearableFileInput(attrs={
            "class": "form-control",
            "accept": ".pdf,image/*"
        }),
        help_text="Upload PDF or image proof/receipt."
    )

    receipt_image = forms.ImageField(
        required=False,
        label="Receipt Image",
        widget=forms.ClearableFileInput(attrs={
            "class": "form-control",
            "accept": "image/*"
        }),
        help_text="Optional image version of the receipt."
    )

    def __init__(self, *args, **kwargs):
        current_user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if current_user and hasattr(current_user, "church") and current_user.church:
            self.fields["donations_type"].queryset = (
                DonationCategory.objects
                .filter(church=current_user.church)
                .order_by("name")
            )
        else:
            self.fields["donations_type"].queryset = DonationCategory.objects.none()

        user_model = Donations._meta.get_field("user").remote_field.model
        if current_user and hasattr(current_user, "church") and current_user.church:
            try:
                self.fields["user"].queryset = (
                    user_model.objects
                    .filter(
                        church=current_user.church,
                        user_type__in=["Member", "Pastor", "Treasurer"],
                        is_active=True
                    )
                    .order_by("first_name", "last_name", "username")
                )
            except Exception:
                self.fields["user"].queryset = (
                    user_model.objects
                    .filter(church=current_user.church)
                    .order_by("username")
                )
        else:
            self.fields["user"].queryset = user_model.objects.none()

        self.fields["user"].label_from_instance = lambda obj: (
            obj.get_full_name().strip() if hasattr(obj, "get_full_name") and obj.get_full_name().strip()
            else obj.username
        )

        self.fields["user"].help_text = "Shown only when donor type is Member."
        self.fields["donor"].help_text = "Shown only when donor type is Non-member."

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount <= 0:
            raise ValidationError("Amount must be greater than 0.")
        return amount

    def clean(self):
        cleaned_data = super().clean()

        dtype = cleaned_data.get("donations_type")
        other_specification = (cleaned_data.get("other_donations_type") or "").strip()

        donor_type = cleaned_data.get("donor_type")
        selected_user = cleaned_data.get("user")
        donor_name = (cleaned_data.get("donor") or "").strip()

        if dtype and "other" in dtype.name.lower() and not other_specification:
            self.add_error("other_donations_type", "Please specify the details for 'Other'.")

        if donor_type == Donations.DonorType.MEMBER:
            if not selected_user:
                self.add_error("user", "Please select a member, pastor, or treasurer.")
            else:
                cleaned_data["donor"] = (
                    selected_user.get_full_name().strip()
                    if hasattr(selected_user, "get_full_name") and selected_user.get_full_name().strip()
                    else selected_user.username
                )

        elif donor_type == Donations.DonorType.NON_MEMBER:
            if not donor_name:
                self.add_error("donor", "Please enter the non-member donor name.")
            cleaned_data["user"] = None
            cleaned_data["donor"] = donor_name

        elif donor_type == Donations.DonorType.ANONYMOUS:
            cleaned_data["user"] = None
            cleaned_data["donor"] = ""

        else:
            self.add_error("donor_type", "Invalid donor type selected.")

        return cleaned_data


# ==========================================
# 3. ADMIN SETTINGS FORM (Add New Category)
# ==========================================
class DonationCategoryForm(forms.ModelForm):
    class Meta:
        model = DonationCategory
        # 1. Ensure 'is_restricted' is in the fields list
        fields = ['name', 'description', 'is_restricted']

        # 2. Define widgets here to apply Bootstrap classes cleanly
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Building Fund'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Brief details about this fund...'
            }),
            # This is the fix for the checkbox visibility:
            'is_restricted': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

class TreasurerLoginForm(AuthenticationForm):
    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        user = CustomUser.objects.filter(username=username).first()

        if user:
            if user.user_type != 'Treasurer':
                raise ValidationError("Only Treasurers are allowed to log in.")
        else:
            raise ValidationError("Invalid username or password.")

        return cleaned_data


class MemberLoginForm(AuthenticationForm):
    def clean(self):
        """
        Adds custom validation to ensure only Members can log in.
        """
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')

        # Authenticate user
        user = CustomUser.objects.filter(username=username).first()

        # Debugging: Print user details to verify behavior
        print(f"Debug: Username={username}, User={user}, User Type={user.user_type if user else 'N/A'}")

        # Validate user existence and type
        if user:
            if user.user_type != 'Member':
                raise ValidationError("Only Members are allowed to log in.")
        else:
            raise ValidationError("Invalid username or password.")

        return cleaned_data

class PastorLoginForm(AuthenticationForm):
    def clean(self):
        """
        Adds custom validation to ensure only Members can log in.
        """
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')

        # Authenticate user
        user = CustomUser.objects.filter(username=username).first()

        # Debugging: Print user details to verify behavior
        print(f"Debug: Username={username}, User={user}, User Type={user.user_type if user else 'N/A'}")

        # Validate user existence and type
        if user:
            if user.user_type != 'Pastor':
                raise ValidationError("Only Pastor are allowed to log in.")
        else:
            raise ValidationError("Invalid username or password.")

        return cleaned_data

class AdminLoginForm(AuthenticationForm):
    def clean(self):
        """
        Adds custom validation to ensure only Members can log in.
        """
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')

        # Authenticate user
        user = CustomUser.objects.filter(username=username).first()

        # Debugging: Print user details to verify behavior
        print(f"Debug: Username={username}, User={user}, User Type={user.user_type if user else 'N/A'}")

        # Validate user existence and type
        if user:
            if user.user_type != 'Admin':
                raise ValidationError("Only Admins are allowed to log in.")
        else:
            raise ValidationError("Invalid username or password.")

        return cleaned_data


class PastorListView(ListView):
    model = CustomUser
    template_name = 'pastor_list.html'
    context_object_name = 'pastor_users'

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'church') and user.church:
            return CustomUser.objects.filter(
                user_type='Pastor',
                church=user.church
            )
        return CustomUser.objects.none()

class TreasurerListView(ListView):
    model = CustomUser
    template_name = 'treasurer_list.html'  # Specify your template
    context_object_name = 'treasurer_users'  # Name of the context variable in the template

    def get_queryset(self):
        # Filter users where user_type is 'member'
        return CustomUser.objects.filter(user_type='treasurer')


class RoleAwareAuthenticationForm(AuthenticationForm):
    """
    Single login form (no role gating). We only ask for username/password.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # cosmetics only
        self.fields["username"].widget.attrs.update({
            "placeholder": "Enter your username", "autofocus": "autofocus"
        })
        self.fields["password"].widget.attrs.update({
            "placeholder": "Enter your password"
        })


from django import forms
from .models import Ministry


class MinistryForm(forms.ModelForm):
    class Meta:
        model = Ministry
        # Added 'assigned_requester' to fields
        fields = ["name", "code", "description", "assigned_requester", "is_active"]

        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'assigned_requester': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'assigned_requester': 'Assigned Leader / Requester'
        }

    def __init__(self, *args, **kwargs):
        # 1. Extract the request object passed from the view
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        # 2. FILTER USERS BY CHURCH
        # Only show users that belong to the same church as the logged-in admin
        if self.request and hasattr(self.request.user, 'church') and self.request.user.church:
            current_church_id = self.request.user.church.id

            # Filter queryset for the assigned_requester field
            self.fields['assigned_requester'].queryset = CustomUser.objects.filter(
                church_id=current_church_id
            ).order_by('last_name', 'first_name')

            # Optional: Customize how users appear in the dropdown (e.g., "Doe, John")
            self.fields['assigned_requester'].label_from_instance = lambda \
                obj: f"{obj.get_full_name()} ({obj.username})"
        else:
            # Fallback: If no church context (e.g. superuser), maybe show all or none
            # Usually safer to show none to prevent cross-church assignment errors
            self.fields['assigned_requester'].queryset = CustomUser.objects.none()

    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        # Ensure we have the user/church context
        if self.request and self.request.user.is_authenticated:
            church = self.request.user.church

            # Filter by Name AND Church (Case-insensitive)
            qs = Ministry.objects.filter(name__iexact=name, church=church)

            # Exclude the current instance if we are editing
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError("A ministry with this name already exists in your church.")

        return name

    def clean_code(self):
        code = self.cleaned_data["code"].strip().lower()

        if self.request and self.request.user.is_authenticated:
            church = self.request.user.church

            # Filter by Code AND Church
            qs = Ministry.objects.filter(code__iexact=code, church=church)

            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError("A ministry with this code already exists in your church.")

        return code


def _normalize_amount(value):
    """Helper to strip currency symbols, commas, and spaces."""
    if not value:
        return None
    if isinstance(value, (int, float, Decimal)):
        return value
    return re.sub(r"[^\d\.\-]", "", str(value)).strip()


MONTH_CHOICES = [
    (0, 'Whole Year (Lump Sum)'),
    (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
    (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
    (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December'),
]


class BudgetForm(forms.ModelForm):
    BUDGET_TYPE_CHOICES = [
        ('Yearly', 'Yearly Pool (One amount for the whole year)'),
        ('Monthly', 'Monthly Basis (Resets every month)'),
    ]

    budget_scope = forms.ChoiceField(
        choices=BUDGET_TYPE_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'btn-check'}),
        initial='Yearly',
        label="Budget Style"
    )

    repeat_for_year = forms.BooleanField(
        required=False,
        label="Create for all 12 months?",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    class Meta:
        model = MinistryBudget
        fields = ["ministry", "year", "month", "amount_allocated", "is_active"]
        widgets = {
            'ministry': forms.Select(attrs={'class': 'form-select'}),
            'year': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'YYYY', 'min': '2020'}),
            'month': forms.Select(attrs={'class': 'form-select'}),
            'amount_allocated': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0.00'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }
        help_texts = {
            'is_active': 'Uncheck to close this budget.'
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        self.selected_year = kwargs.pop('selected_year', None)
        self.selected_month = kwargs.pop('selected_month', None)

        super().__init__(*args, **kwargs)

        church = getattr(getattr(self.request, "user", None), "church", None)

        # --- FIX: POPULATE THE MONTH DROPDOWN PROPERLY ---
        month_choices = [('', 'Select Specific Month')] + [(i, calendar.month_name[i]) for i in range(1, 13)]
        self.fields['month'].choices = month_choices
        self.fields['month'].required = False

        if not self.instance.pk and not self.initial.get('year'):
            self.fields['year'].initial = self.selected_year or datetime.now().year

        # --- FORCE SCOPE AND MONTH ON LOAD ---
        if self.instance and self.instance.pk:
            actual_scope = 'Yearly' if self.instance.month == 0 else 'Monthly'

            # Force BOTH the initial dict and the field initial to guarantee UI rendering
            self.initial['budget_scope'] = actual_scope
            self.fields['budget_scope'].initial = actual_scope

            self.initial['month'] = self.instance.month
            self.fields['month'].initial = self.instance.month

            self.fields['repeat_for_year'].label = "Apply changes to all 12 months?"
        else:
            scope = self.initial.get('budget_scope', 'Yearly')
            self.initial['budget_scope'] = scope
            self.fields['budget_scope'].initial = scope
        # -----------------------------------------------------------

        # Determine current scope for blocking/filtering logic
        current_scope = self.data.get('budget_scope') if self.is_bound else self.initial.get('budget_scope')

        # Filter ministry queryset
        if church:
            base_qs = Ministry.objects.filter(church=church, is_active=True).order_by('name')

            year = self._coerce_int(
                self.data.get('year') if self.is_bound else self.initial.get('year'),
                fallback=self.selected_year or datetime.now().year
            )

            month = self._coerce_int(
                self.data.get('month') if self.is_bound else self.initial.get('month'),
                fallback=self.selected_month
            )

            blocked_ids = self._get_blocked_ministry_ids(
                church=church, year=year, month=month, scope=current_scope
            )

            # In edit mode, keep current ministry selectable
            if self.instance and self.instance.pk and self.instance.ministry_id:
                blocked_ids.discard(self.instance.ministry_id)

            self.fields["ministry"].queryset = base_qs.exclude(id__in=blocked_ids)
        else:
            self.fields["ministry"].queryset = Ministry.objects.none()

    def _coerce_int(self, value, fallback=None):
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def _get_blocked_ministry_ids(self, *, church, year, month, scope):
        if not church or not year:
            return set()

        qs = MinistryBudget.objects.filter(church=church, year=year)

        if scope == 'Yearly':
            qs = qs.filter(Q(month=0) | Q(month__gte=1, month__lte=12))
        else:
            if month not in range(1, 13):
                return set()
            qs = qs.filter(Q(month=month) | Q(month=0))

        return set(qs.values_list("ministry_id", flat=True))

    def clean(self):
        cleaned = super().clean()

        church = getattr(getattr(self.request, "user", None), "church", None)
        ministry = cleaned.get("ministry")
        year = cleaned.get("year")
        month = cleaned.get("month")
        scope = cleaned.get("budget_scope")
        repeat = bool(cleaned.get("repeat_for_year"))
        amount = cleaned.get("amount_allocated")

        if not church or not ministry:
            return cleaned

        if year is None:
            self.add_error("year", "Year is required.")
            return cleaned

        if amount is not None and amount < 0:
            self.add_error("amount_allocated", "Allocated amount cannot be negative.")

        is_edit = self.instance and self.instance.pk is not None
        qs = MinistryBudget.objects.filter(church=church, ministry=ministry, year=year)

        # Always exclude the current record so it doesn't conflict with itself
        if is_edit:
            qs = qs.exclude(pk=self.instance.pk)

        # =========================================
        # 1. YEARLY POOL
        # =========================================
        if scope == 'Yearly':
            cleaned['month'] = 0
            if 'month' in self._errors:
                del self._errors['month']

            if qs.filter(month=0).exists():
                self.add_error('ministry', "A yearly pool already exists for this ministry and year.")

            # CREATE MODE ONLY: Block creating Yearly if Monthly exists.
            # (Allows switching during Edit mode)
            if not is_edit and qs.filter(month__gte=1, month__lte=12).exists():
                self.add_error(
                    'budget_scope',
                    "Cannot add Yearly Pool: monthly budgets already exist for this ministry and year."
                )

            return cleaned

        # =========================================
        # 2. MONTHLY BASIS
        # =========================================
        if repeat:
            cleaned['month'] = 1
            if 'month' in self._errors:
                del self._errors['month']

            # Enforce batch continuity in edit mode
            if is_edit and self.instance.month in range(1, 13):
                if ministry != self.instance.ministry or year != self.instance.year:
                    self.add_error(
                        'repeat_for_year',
                        "When applying changes to all 12 months, ministry and year must remain the same."
                    )
            return cleaned

        if not month or month == 0:
            self.add_error('month', "Please select a specific month.")
            return cleaned

        # CREATE MODE ONLY: Block creating Monthly if Yearly exists.
        # (Allows switching during Edit mode)
        if not is_edit and qs.filter(month=0).exists():
            self.add_error(
                'budget_scope',
                "Cannot add Monthly budget: a Yearly Pool already exists for this ministry and year."
            )

        if qs.filter(month=month).exists():
            self.add_error('month', "A budget for this ministry, year, and month already exists.")

        return cleaned

# Helper function (usually placed in utils.py or views.py, but fine here if imported)
def _normalize_amount(value):
    """Removes commas from currency inputs (e.g. '1,000' -> '1000')"""
    if not value:
        return None
    if isinstance(value, (int, float, Decimal)):
        return value
    return str(value).replace(',', '').strip()

# --- Updated Form ---
class BudgetReleaseRequestForm(forms.ModelForm):
    class Meta:
        model = BudgetReleaseRequest
        fields = ["budget", "date_released", "amount", "remarks"]
        widgets = {
            "date_released": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "remarks": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "amount": forms.TextInput(attrs={"class": "form-control", "placeholder": "0.00"}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        self.physical_cash = kwargs.pop("physical_cash", Decimal("0.00"))
        self.bank_balance = kwargs.pop("bank_balance", Decimal("0.00"))
        self.total_available_funds = kwargs.pop("total_available_funds", Decimal("0.00"))
        super().__init__(*args, **kwargs)

        self.fields["budget"].queryset = MinistryBudget.objects.none()

        if self.request and self.request.user.is_authenticated and getattr(self.request.user, "church_id", None):
            user = self.request.user
            church = user.church

            today = timezone.localdate()
            current_year = today.year
            current_month = today.month

            qs = MinistryBudget.objects.filter(
                church=church,
                is_active=True,
                year=current_year,
                month__in=[current_month, 0],
            )

            privileged_roles = ["Admin", "ChurchAdmin", "Treasurer"]

            if user.user_type not in privileged_roles:
                qs = qs.filter(ministry__assigned_requester=user)

                if not qs.exists():
                    self.fields["budget"].empty_label = f"No active budgets found for {today.strftime('%B %Y')}"
                    self.fields["budget"].widget.attrs["disabled"] = "disabled"
                    self.fields["budget"].help_text = "You do not have a budget allocated for the current month."

            self.fields["budget"].queryset = qs.select_related(
                "ministry", "balance_account"
            ).order_by("ministry__name")

            self.fields["budget"].label_from_instance = lambda obj: (
                f"{obj.ministry.name} "
                f"({calendar.month_name[obj.month] if obj.month in range(1, 13) else 'Yearly Pool'}) "
                f"— Avail: ₱{Decimal(obj.current_balance or 0):,.2f}"
            )

    def clean_amount(self):
        raw = self.data.get("amount", self.cleaned_data.get("amount"))

        if raw in (None, ""):
            raise ValidationError("Amount is required.")

        if isinstance(raw, str):
            raw = raw.replace(",", "").strip()

        try:
            amount = Decimal(raw)
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError("Enter a valid amount.")

        if amount <= 0:
            raise ValidationError("Amount must be greater than 0.")

        return amount

    def clean(self):
        cleaned = super().clean()
        budget = cleaned.get("budget")
        amount = cleaned.get("amount")

        if not budget or amount is None:
            return cleaned

        if not self.request or not self.request.user.is_authenticated:
            raise ValidationError("Authentication is required.")

        user = self.request.user
        privileged_roles = ["Admin", "ChurchAdmin", "Treasurer"]

        # ---------------------------------------------------------
        # SECURITY CHECK: assigned requester only
        # ---------------------------------------------------------
        if user.user_type not in privileged_roles:
            actual_leader = getattr(budget.ministry, "assigned_requester", None)

            if actual_leader != user:
                raise ValidationError(
                    f"⛔ SECURITY DENIED: You are not the assigned leader for {budget.ministry.name}. "
                    "You cannot request funds from this budget."
                )

        # ---------------------------------------------------------
        # TIME CHECK: only current year/current month or yearly pool
        # ---------------------------------------------------------
        today = timezone.localdate()

        if budget.year != today.year:
            raise ValidationError(
                f"Error: You cannot request funds for a different year ({budget.year})."
            )

        if budget.month != 0 and budget.month != today.month:
            month_name = calendar.month_name[budget.month] if budget.month in range(1, 13) else "Yearly Pool"
            raise ValidationError(
                f"Error: You cannot request funds for a different month ({month_name})."
            )

        # ---------------------------------------------------------
        # CHECK 1: MINISTRY WALLET BALANCE
        # ---------------------------------------------------------
        if hasattr(budget, "balance_account") and budget.balance_account:
            ministry_balance = Decimal(str(budget.balance_account.current_amount or 0))
        else:
            ministry_balance = Decimal("0.00")

        if amount > ministry_balance:
            raise ValidationError(
                f"Insufficient Funds in Ministry Wallet. "
                f"Available: ₱{ministry_balance:,.2f}. Requested: ₱{amount:,.2f}."
            )

        # ---------------------------------------------------------
        # CHECK 2: TOTAL AVAILABLE FUNDS (passed from view)
        # ---------------------------------------------------------
        if amount > self.total_available_funds:
            raise ValidationError(
                f"Insufficient Total Available Funds. "
                f"Physical Cash: ₱{self.physical_cash:,.2f}. "
                f"Bank Balance: ₱{self.bank_balance:,.2f}. "
                f"Total Available: ₱{self.total_available_funds:,.2f}. "
                f"Requested: ₱{amount:,.2f}."
            )

        return cleaned

# =========================================================
# 1. THE SINGLE ROW FORM (Simplifies the inputs)
# =========================================================
def _normalize_amount(value):
    """
    Normalize currency-like inputs into a plain numeric string.
    Examples:
      "₱ 1,234.50" -> "1234.50"
      "1,234"      -> "1234"
    """
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    s = str(value).strip()
    s = s.replace("₱", "").replace(",", "").replace(" ", "")
    # keep digits, dot, minus
    s = re.sub(r"[^\d\.\-]", "", s)
    return s.strip()


# =========================================================
# 1) EXPENSE FORM (Single Row)
# =========================================================
class BudgetExpenseForm(forms.ModelForm):
    class Meta:
        model = BudgetExpense
        fields = ["date_incurred", "description", "amount", "paid_from", "receipt_proof"]
        widgets = {
            "date_incurred": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "description": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g., Jollibee Receipt"
            }),
            "amount": forms.TextInput(attrs={
                "class": "form-control text-end expense-amount",
                "placeholder": "0.00"
            }),
            "paid_from": forms.Select(attrs={"class": "form-select"}),
            "receipt_proof": forms.FileInput(attrs={"class": "form-control form-control-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["paid_from"].label = "Paid From"
        self.fields["paid_from"].help_text = (
            "Choose whether this expense was paid through Physical Cash or Bank."
        )

    def _get_release_church(self):
        release = getattr(self, "release_instance", None)
        if release:
            return getattr(release, "church", None)

        # fallback if editing existing instance
        if getattr(self.instance, "release_id", None):
            return getattr(self.instance.release, "church", None)

        return None

    def _get_lock_date(self, church):
        if church and hasattr(church, "accounting_settings") and church.accounting_settings:
            return church.accounting_settings.lock_date
        return None

    def _get_allowed_max_date(self, church):
        """
        Lock-aware max date:
        - normal case: today
        - if today is still within/at the lock date, allow the next open date
        """
        today = timezone.localdate()
        lock_date = self._get_lock_date(church)

        if lock_date and today <= lock_date:
            return lock_date + timedelta(days=1)

        return today

    def clean_amount(self):
        field_name = self.add_prefix("amount")
        raw_value = self.data.get(field_name)

        norm = _normalize_amount(raw_value)
        if not norm:
            raise ValidationError("Amount is required.")

        try:
            amount = Decimal(str(norm))
        except (InvalidOperation, ValueError):
            raise ValidationError("Enter a valid amount.")

        if amount <= Decimal("0.00"):
            raise ValidationError("Amount must be greater than 0.")

        return amount

    def clean_paid_from(self):
        paid_from = self.cleaned_data.get("paid_from")

        valid_choices = {
            BudgetExpense.PAID_CASH,
            BudgetExpense.PAID_BANK,
        }

        if paid_from not in valid_choices:
            raise ValidationError("Please choose a valid payment source.")

        return paid_from

    def clean_date_incurred(self):
        """
        Matches your current view rule:
        - block dates on or before lock_date
        - allow only dates strictly after lock_date
        """
        d = self.cleaned_data.get("date_incurred")
        if not d:
            return d

        church = self._get_release_church()
        lock_date = self._get_lock_date(church)

        if lock_date and d <= lock_date:
            raise ValidationError(
                f"PERIOD LOCKED: Books are closed on or before {lock_date}. "
                f"You cannot add/edit entries dated {d}."
            )

        return d

    def clean(self):
        cleaned = super().clean()

        d = cleaned.get("date_incurred")
        paid_from = cleaned.get("paid_from")
        church = self._get_release_church()

        # lock-aware future-date validation
        if d and church:
            allowed_max_date = self._get_allowed_max_date(church)

            if d > allowed_max_date:
                self.add_error(
                    "date_incurred",
                    f"Date cannot be later than {allowed_max_date}."
                )
        elif d and d > timezone.localdate():
            # fallback in case church is unavailable
            self.add_error("date_incurred", "Date cannot be in the future.")

        # require bank setup if paid from bank
        if paid_from == BudgetExpense.PAID_BANK and church:
            bank_exists = BankAccount.objects.filter(church=church).exists()
            if not bank_exists:
                self.add_error(
                    "paid_from",
                    "No bank account is configured. Please set up bank settings first."
                )

        return cleaned


# =========================================================
# 2) FORMSET VALIDATION (C2-Safe)
# =========================================================
class BaseBudgetExpenseFormSet(BaseModelFormSet):
    def clean(self):
        """
        ✅ Policy C2-safe:
        After add/edit/delete, the FINAL total receipts for this release
        must not exceed the released amount.

        Works for:
          - new receipts
          - editing existing receipts
          - deleting receipts
          - liquidated and unliquidated releases
        """
        if any(self.errors):
            return

        release = getattr(self, "release_instance", None)
        if not release:
            return

        amount_released = Decimal(release.amount or 0)
        final_total_spent = Decimal("0.00")

        for form in self.forms:
            # Skip deleted forms
            if self.can_delete and self._should_delete_form(form):
                continue

            if not form.cleaned_data:
                continue

            amt = form.cleaned_data.get("amount")
            if amt:
                final_total_spent += amt

        if final_total_spent > amount_released:
            raise ValidationError(
                f"OVER BUDGET: Total receipts will be ₱{final_total_spent:,.2f}, "
                f"but released amount is only ₱{amount_released:,.2f}."
            )


# =========================================================
# 3) FORMSET FACTORY
# =========================================================
BudgetExpenseFormSet = modelformset_factory(
    BudgetExpense,
    form=BudgetExpenseForm,
    formset=BaseBudgetExpenseFormSet,
    extra=1,
    can_delete=True
)

class PendingReferenceForm(forms.ModelForm):
    class Meta:
        model = PendingReference
        fields = ['reference_number', 'date', 'amount', 'name', 'file']

    date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'})
    )

class ThankYouLetterForm(forms.Form):
    # A simple textarea for the thank-you letter message
    message = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 6}), label="Thank You Message")


class HomeContentForm(forms.ModelForm):
    class Meta:
        model = HomePageContent
        fields = ['title', 'subtitle', 'hero_image']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter homepage title'
            }),
            'subtitle': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Enter subtitle, mission statement, or Bible verse'
            }),
            'hero_image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }


class BankInfoForm(forms.ModelForm):
    # Added Image Field specifically for Identity Verification
    verification_image = forms.ImageField(
        required=True,
        label="Proof of Account Ownership",
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Upload a photo of your Passbook or Online Profile showing these details."
    )

    class Meta:
        model = BankAccount
        # We handle Name and Number here. Balance is handled in the other form.
        fields = ['bank_name', 'account_name', 'account_number', 'verification_image']
        widgets = {
            'bank_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. BDO, BPI, Metrobank'}),
            'account_name': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'e.g. Living Stone Church Main'}),
            'account_number': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'Enter Official Account Number'}),
        }

    def clean_account_number(self):
        """
        Validate that the account number looks real.
        """
        account_number = self.cleaned_data.get('account_number')

        if not account_number:
            return account_number

        # 1. Clean format (remove dashes/spaces)
        clean_number = account_number.replace('-', '').replace(' ', '')

        # 2. Check digits
        if not clean_number.isdigit():
            raise forms.ValidationError("Invalid Format: Account number must contain only digits (0-9).")

        # 3. Check Length
        if len(clean_number) < 10 or len(clean_number) > 16:
            raise forms.ValidationError(
                f"Invalid Length: Account number is {len(clean_number)} digits. It should be between 10 and 16 digits.")

        # 4. Uniqueness Check
        if BankAccount.objects.filter(account_number=clean_number).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This account number is already registered in the system.")

        return clean_number


# --- FORM 2: BANK DASHBOARD (Money Only) ---
# Used in: ManageBankView (Update Balance)
class BankBalanceForm(forms.ModelForm):
    verification_image = forms.ImageField(
        required=True,
        label="Current Balance Proof",
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Upload a recent screenshot of the total balance."
    )

    class Meta:
        model = BankAccount
        fields = ['current_balance', 'verification_image']
        widgets = {
            'current_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


# --- FORM 3: DEPOSIT (Transaction Only) ---
# Used in: BankDepositView
class BankDepositForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        label="Amount to Deposit",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    deposit_date = forms.DateField(
        label="Date of Deposit",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        initial=timezone.now().date
    )
    # CHANGE: Made required=True so AI can check it
    proof_image = forms.ImageField(
        label="Deposit Slip / Screenshot",
        required=True,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Required for AI Fraud Detection."
    )
    notes = forms.CharField(
        required=False,
        label="Notes (Optional)",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Deposit from Sunday Offering'})
    )


class BankWithdrawForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        label="Amount to Withdraw",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    withdraw_date = forms.DateField(
        label="Date of Withdrawal",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        initial=timezone.now().date
    )
    proof_image = forms.ImageField(
        label="Withdrawal Receipt / Screenshot",
        required=True,
        widget=forms.FileInput(attrs={'class': 'form-control'}),
        help_text="Required for AI Fraud Detection."
    )
    notes = forms.CharField(
        required=False,
        label="Notes (Optional)",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Withdraw for event supplies'
        })
    )

class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(
        label="Enter your registered email",
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'name@example.com'})
    )

class ResetPasswordConfirmForm(forms.Form):
    code = forms.CharField(
        label="Verification Code",
        max_length=6,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 123456'})
    )
    new_password = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'New Password'})
    )
    confirm_password = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'})
    )

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("new_password")
        p2 = cleaned_data.get("confirm_password")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data

class LooseOfferingForm(forms.Form):
    date = forms.DateField(
        label="Service Date",
        widget=forms.DateInput(attrs={
            "type": "date",
            "class": "form-control",
        })
    )

    loose_total = forms.DecimalField(
        label="Total Loose Offering (Basket)",
        min_value=0,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            "class": "form-control form-control-lg",
            "placeholder": "0.00",
            "step": "0.01",
            "min": "0",
        })
    )

    proof_document = forms.FileField(
        required=False,
        label="Batch Proof Document",
        widget=forms.ClearableFileInput(attrs={
            "class": "form-control",
            "accept": ".jpg,.jpeg,.png,.pdf",
        }),
        help_text="Upload JPG, PNG, or PDF of the tally sheet, envelope summary, or deposit slip."
    )

    ocr_text = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    def clean_loose_total(self):
        value = self.cleaned_data.get("loose_total")
        if value is None:
            return 0
        return value

    def clean_proof_document(self):
        uploaded_file = self.cleaned_data.get("proof_document")
        if not uploaded_file:
            return uploaded_file

        allowed_exts = {".jpg", ".jpeg", ".png", ".pdf"}
        name = uploaded_file.name.lower()

        if "." not in name:
            raise forms.ValidationError("Invalid file type. Please upload JPG, PNG, or PDF.")

        ext = name[name.rfind("."):]
        if ext not in allowed_exts:
            raise forms.ValidationError("Unsupported file type. Please upload JPG, PNG, or PDF.")

        return uploaded_file


class EnvelopeOfferingForm(forms.Form):
    PAYMENT_TYPE_CHOICES = [
        ("Cash", "Cash"),
        ("Check", "Check"),
        ("GCash", "GCash"),
    ]

    date = forms.DateField(
        required=False,
        label="Date",
        widget=forms.DateInput(attrs={
            "type": "date",
            "class": "form-control form-control-sm",
        })
    )

    member = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        required=False,
        label="Member",
        widget=forms.Select(attrs={
            "class": "form-select form-select-sm",
        })
    )

    amount = forms.DecimalField(
        min_value=0,
        decimal_places=2,
        required=False,
        label="Amount",
        widget=forms.NumberInput(attrs={
            "class": "form-control form-control-sm",
            "placeholder": "0.00",
            "step": "0.01",
            "min": "0",
        })
    )

    type = forms.ChoiceField(
        choices=PAYMENT_TYPE_CHOICES,
        initial="Cash",
        label="Type",
        widget=forms.Select(attrs={
            "class": "form-select form-select-sm",
        })
    )

    check_number = forms.CharField(
        required=False,
        label="Check Number",
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-sm",
            "placeholder": "Check no.",
        })
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if user and hasattr(user, "church") and user.church:
            self.fields["member"].queryset = CustomUser.objects.filter(
                church=user.church,
                user_type="Member"
            ).order_by("last_name", "first_name")
        else:
            self.fields["member"].queryset = CustomUser.objects.none()

    def clean(self):
        cleaned_data = super().clean()

        member = cleaned_data.get("member")
        amount = cleaned_data.get("amount")
        offering_type = cleaned_data.get("type")
        check_number = (cleaned_data.get("check_number") or "").strip()
        date = cleaned_data.get("date")

        # Detect if row has any content at all
        has_any_value = any([
            member,
            amount not in (None, ""),
            bool(date),
            bool(check_number),
            bool(offering_type and offering_type != "Cash"),
        ])

        # Fully blank row is allowed
        if not has_any_value:
            return cleaned_data

        # If row is being used, member + amount are required
        if not member:
            self.add_error("member", "Please select a member for this envelope entry.")

        if amount in (None, ""):
            self.add_error("amount", "Please enter an amount for this envelope entry.")
        elif amount <= 0:
            self.add_error("amount", "Amount must be greater than zero.")

        # If payment type is Check, require check number
        if offering_type == "Check" and not check_number:
            self.add_error("check_number", "Check number is required when payment type is Check.")

        # If not Check, clear check number
        if offering_type != "Check":
            cleaned_data["check_number"] = ""

        return cleaned_data


EnvelopeFormSet = formset_factory(
    EnvelopeOfferingForm,
    extra=15,
    can_delete=False
)



class AccountingLockForm(forms.ModelForm):
    class Meta:
        model = AccountingSettings
        fields = ['lock_date']
        widgets = {
            'lock_date': forms.DateInput(
                attrs={
                    'type': 'date',
                    'class': 'form-control',
                    'style': 'max-width: 300px; margin: 0 auto;'
                }
            )
        }
        labels = {
            'lock_date': 'Lock Date (Close Books Until)'
        }


class OtherIncomeCategoryForm(forms.ModelForm):
    class Meta:
        model = OtherIncomeCategory
        # 1. Added 'is_restricted' to fields
        fields = ['name', 'description', 'is_restricted']

        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Facility Rental, Grants'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Brief details about this income source...'
            }),
            # 2. Added widget for the checkbox to style it correctly
            'is_restricted': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }


class OtherIncomeForm(forms.ModelForm):
    # Non-model field (toggle only)
    run_ocr = forms.BooleanField(
        required=False,
        initial=False,
        label="Run OCR",
        help_text="Extract details from the uploaded receipt (image/PDF)."
    )

    SYSTEM_BLOCKED_CATEGORY_NAMES = {
        "budget return",
    }

    class Meta:
        model = OtherIncome
        fields = ["amount", "income_type", "date", "description", "file", "receipt_image"]

        widgets = {
            "amount": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "0.00",
                "step": "0.01",
                "min": "0"
            }),
            "income_type": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "description": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Optional details (e.g. Check #123, Donor Name)"
            }),

            # model fields
            "file": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": ".pdf,image/*"
            }),
            "receipt_image": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "image/*"
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if self.user and hasattr(self.user, "church") and self.user.church:
            self.fields["income_type"].queryset = (
                OtherIncomeCategory.objects
                .filter(church=self.user.church)
                .exclude(name__iexact="Budget Return")
                .order_by("name")
            )
        else:
            self.fields["income_type"].queryset = OtherIncomeCategory.objects.none()

        # uploads optional
        self.fields["file"].required = False
        self.fields["receipt_image"].required = False

    def clean_income_type(self):
        income_type = self.cleaned_data.get("income_type")

        if income_type:
            normalized_name = (income_type.name or "").strip().lower()
            if normalized_name in self.SYSTEM_BLOCKED_CATEGORY_NAMES:
                raise ValidationError(
                    "Budget Return is system-generated and cannot be added manually."
                )

        return income_type

User = get_user_model()

MAX_UPLOAD_MB = 5
ALLOWED_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}


class BankMovementUnifiedForm(forms.Form):
    date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )

    amount = forms.DecimalField(
        min_value=Decimal("0.01"),
        decimal_places=2,
        max_digits=12,
        widget=forms.NumberInput(attrs={"class": "form-control"})
    )

    direction = forms.ChoiceField(
        choices=CashBankMovement.Direction.choices,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    source_type = forms.ChoiceField(
        choices=CashBankMovement.SourceType.choices,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    memo = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"})
    )

    reference_no = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"})
    )

    proof_file = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control"})
    )

    donations_type = forms.ModelChoiceField(
        queryset=DonationCategory.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    donor_type = forms.ChoiceField(
        choices=Donations.DonorType.choices,
        required=False,
        initial=Donations.DonorType.ANONYMOUS,
        widget=forms.Select(attrs={"class": "form-select donor-type-select"})
    )

    donor = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"})
    )

    other_donations_type = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"})
    )

    donation_member = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    income_type = forms.ModelChoiceField(
        queryset=OtherIncomeCategory.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    income_description = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"})
    )

    expense_category = forms.ModelChoiceField(
        queryset=ExpenseCategory.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    expense_description = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        church = getattr(user, "church", None)

        removed_directions = {
            CashBankMovement.Direction.CASH_TO_BANK,
            CashBankMovement.Direction.BANK_TO_CASH,
            CashBankMovement.Direction.BANK_TO_BANK,
        }
        self.fields["direction"].choices = [
            (value, label)
            for value, label in self.fields["direction"].choices
            if value not in removed_directions
        ]

        transfer_only_value = getattr(CashBankMovement.SourceType, "TRANSFER_ONLY", None)
        if transfer_only_value:
            self.fields["source_type"].choices = [
                (value, label)
                for value, label in self.fields["source_type"].choices
                if value != transfer_only_value
            ]

        if church:
            self.fields["donations_type"].queryset = (
                DonationCategory.objects.filter(church=church).order_by("name")
            )

            self.fields["income_type"].queryset = (
                OtherIncomeCategory.objects.filter(church=church).order_by("name")
            )

            self.fields["expense_category"].queryset = (
                ExpenseCategory.objects.filter(church=church)
                .exclude(
                    Q(name__iexact="Bank Deposit") |
                    Q(name__iexact="Bank Withdraw") |
                    Q(name__iexact="Budget Release - Bank") |
                    Q(name__iexact="Budget Release - Cash")
                )
                .order_by("name")
            )

            self.fields["donation_member"].queryset = (
                User.objects.filter(
                    church=church,
                    is_active=True,
                    user_type__in=["Member", "Pastor", "Treasurer"],
                ).order_by("first_name", "last_name", "username")
            )
        else:
            self.fields["donations_type"].queryset = DonationCategory.objects.none()
            self.fields["income_type"].queryset = OtherIncomeCategory.objects.none()
            self.fields["expense_category"].queryset = ExpenseCategory.objects.none()
            self.fields["donation_member"].queryset = User.objects.none()

        self.fields["donation_member"].label_from_instance = lambda obj: (
            obj.get_full_name().strip()
            if hasattr(obj, "get_full_name") and obj.get_full_name().strip()
            else obj.username
        )

    def clean_proof_file(self):
        f = self.cleaned_data.get("proof_file")
        if not f:
            return f

        if f.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise ValidationError(f"File too large. Max {MAX_UPLOAD_MB} MB.")

        ct = getattr(f, "content_type", "") or ""
        if ct not in ALLOWED_CONTENT_TYPES:
            raise ValidationError("Invalid file type. Only PDF/JPG/PNG are allowed.")

        return f

    def clean(self):
        cleaned = super().clean()

        direction = cleaned.get("direction")
        source_type = cleaned.get("source_type")
        proof = cleaned.get("proof_file")

        donor_type = cleaned.get("donor_type") or Donations.DonorType.ANONYMOUS
        donor = (cleaned.get("donor") or "").strip()
        donation_member = cleaned.get("donation_member")

        other_donations_type = (cleaned.get("other_donations_type") or "").strip()
        income_description = (cleaned.get("income_description") or "").strip()
        expense_description = (cleaned.get("expense_description") or "").strip()
        memo = (cleaned.get("memo") or "").strip()
        reference_no = (cleaned.get("reference_no") or "").strip()

        cleaned["memo"] = memo
        cleaned["reference_no"] = reference_no
        cleaned["other_donations_type"] = other_donations_type
        cleaned["income_description"] = income_description
        cleaned["expense_description"] = expense_description

        disallowed_directions = {
            CashBankMovement.Direction.CASH_TO_BANK,
            CashBankMovement.Direction.BANK_TO_CASH,
            CashBankMovement.Direction.BANK_TO_BANK,
        }
        if direction in disallowed_directions:
            self.add_error("direction", "This transaction direction is no longer allowed.")
            return cleaned

        bank_affecting = {
            CashBankMovement.Direction.DIRECT_BANK_RECEIPT,
            CashBankMovement.Direction.BANK_PAID_EXPENSE,
        }
        if direction in bank_affecting and not proof:
            self.add_error("proof_file", "Proof file is required for this transaction.")

        if direction == CashBankMovement.Direction.BANK_PAID_EXPENSE:
            cleaned["source_type"] = CashBankMovement.SourceType.EXPENSE
            source_type = cleaned["source_type"]

        if direction == CashBankMovement.Direction.DIRECT_BANK_RECEIPT:
            allowed = {
                CashBankMovement.SourceType.DONATION,
                CashBankMovement.SourceType.OTHER_INCOME,
                CashBankMovement.SourceType.TITHE,
                CashBankMovement.SourceType.OFFERING,
            }
            if source_type not in allowed:
                self.add_error(
                    "source_type",
                    "Direct to Bank (Income) must be Donation, Other Income, Tithe, or Offering."
                )

        if (
            direction == CashBankMovement.Direction.DIRECT_BANK_RECEIPT
            and source_type == CashBankMovement.SourceType.DONATION
        ):
            if not cleaned.get("donations_type"):
                self.add_error(
                    "donations_type",
                    "Donation category is required for direct bank donation."
                )

            if donor_type == Donations.DonorType.MEMBER:
                if not donation_member:
                    self.add_error(
                        "donation_member",
                        "Please select a member, pastor, or treasurer."
                    )
                else:
                    full_name = (
                        donation_member.get_full_name().strip()
                        if hasattr(donation_member, "get_full_name") and donation_member.get_full_name().strip()
                        else donation_member.username
                    )
                    cleaned["donor"] = full_name

            elif donor_type == Donations.DonorType.NON_MEMBER:
                if not donor:
                    self.add_error("donor", "Please enter the non-member donor name.")
                cleaned["donation_member"] = None
                cleaned["donor"] = donor

            elif donor_type == Donations.DonorType.ANONYMOUS:
                cleaned["donation_member"] = None
                cleaned["donor"] = ""

            else:
                self.add_error("donor_type", "Invalid donor type selected.")

            if cleaned.get("donations_type") and "other" in cleaned["donations_type"].name.lower():
                if not other_donations_type:
                    self.add_error(
                        "other_donations_type",
                        "Please specify the details for 'Other'."
                    )

            cleaned["income_type"] = None
            cleaned["income_description"] = ""
            cleaned["expense_category"] = None
            cleaned["expense_description"] = ""

        elif (
            direction == CashBankMovement.Direction.DIRECT_BANK_RECEIPT
            and source_type == CashBankMovement.SourceType.OTHER_INCOME
        ):
            if not cleaned.get("income_type"):
                self.add_error(
                    "income_type",
                    "Other income category is required for direct bank income."
                )

            cleaned["donations_type"] = None
            cleaned["donor_type"] = Donations.DonorType.ANONYMOUS
            cleaned["donor"] = ""
            cleaned["other_donations_type"] = ""
            cleaned["donation_member"] = None
            cleaned["expense_category"] = None
            cleaned["expense_description"] = ""

        elif (
            direction == CashBankMovement.Direction.DIRECT_BANK_RECEIPT
            and source_type == CashBankMovement.SourceType.TITHE
        ):
            cleaned["donations_type"] = None
            cleaned["donor_type"] = Donations.DonorType.ANONYMOUS
            cleaned["donor"] = ""
            cleaned["other_donations_type"] = ""
            cleaned["income_type"] = None
            cleaned["income_description"] = ""
            cleaned["expense_category"] = None
            cleaned["expense_description"] = ""

        elif (
            direction == CashBankMovement.Direction.DIRECT_BANK_RECEIPT
            and source_type == CashBankMovement.SourceType.OFFERING
        ):
            cleaned["donations_type"] = None
            cleaned["donor_type"] = Donations.DonorType.ANONYMOUS
            cleaned["donor"] = ""
            cleaned["other_donations_type"] = ""
            cleaned["income_type"] = None
            cleaned["income_description"] = ""
            cleaned["expense_category"] = None
            cleaned["expense_description"] = ""

        elif (
            direction == CashBankMovement.Direction.BANK_PAID_EXPENSE
            and source_type == CashBankMovement.SourceType.EXPENSE
        ):
            if not cleaned.get("expense_category"):
                self.add_error(
                    "expense_category",
                    "Expense category is required for bank-paid expense."
                )

            cleaned["donations_type"] = None
            cleaned["donor_type"] = Donations.DonorType.ANONYMOUS
            cleaned["donor"] = ""
            cleaned["other_donations_type"] = ""
            cleaned["donation_member"] = None
            cleaned["income_type"] = None
            cleaned["income_description"] = ""

        return cleaned

User = get_user_model()

class DirectBankReceiptForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    amount = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2, max_digits=12,
                                widget=forms.NumberInput(attrs={"class": "form-control"}))

    source_type = forms.ChoiceField(
        choices=[
            (CashBankMovement.SourceType.TITHE, "Tithe"),
            (CashBankMovement.SourceType.OFFERING, "Offering"),
            (CashBankMovement.SourceType.DONATION, "Donation"),
            (CashBankMovement.SourceType.OTHER_INCOME, "Other Income"),
        ],
        widget=forms.Select(attrs={"class": "form-select"})
    )

    memo = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    reference_no = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    proof_image = forms.ImageField(required=True, widget=forms.ClearableFileInput(attrs={"class": "form-control"}))

    # Donation fields
    donations_type = forms.ModelChoiceField(queryset=DonationCategory.objects.none(), required=False,
                                            widget=forms.Select(attrs={"class": "form-select"}))
    donor = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    donation_member = forms.ModelChoiceField(queryset=User.objects.none(), required=False,
                                            widget=forms.Select(attrs={"class": "form-select"}))

    # Other income fields
    income_type = forms.ModelChoiceField(queryset=OtherIncomeCategory.objects.none(), required=False,
                                        widget=forms.Select(attrs={"class": "form-select"}))
    income_description = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        church = getattr(user, "church", None)
        if church:
            self.fields["donations_type"].queryset = DonationCategory.objects.filter(church=church).order_by("name")
            self.fields["income_type"].queryset = OtherIncomeCategory.objects.filter(church=church).order_by("name")
            self.fields["donation_member"].queryset = User.objects.filter(church=church).order_by("username")

    def clean(self):
        cleaned = super().clean()
        st = cleaned.get("source_type")

        if st == CashBankMovement.SourceType.DONATION and not cleaned.get("donations_type"):
            self.add_error("donations_type", "Donation category is required.")
        if st == CashBankMovement.SourceType.OTHER_INCOME and not cleaned.get("income_type"):
            self.add_error("income_type", "Other income category is required.")

        return cleaned

class ExpenseFraudDetectionSettingsForm(forms.ModelForm):
    class Meta:
        model = AccountingSettings
        fields = [
            "enable_expense_fraud_detection",
            "enable_other_income_fraud_detection",
            "enable_donation_fraud_detection",
            "enable_tithe_fraud_detection",
            "enable_offering_fraud_detection",
        ]
        widgets = {
            "enable_expense_fraud_detection": forms.CheckboxInput(
                attrs={"class": "custom-control-input"}
            ),
            "enable_other_income_fraud_detection": forms.CheckboxInput(
                attrs={"class": "custom-control-input"}
            ),
            "enable_donation_fraud_detection": forms.CheckboxInput(
                attrs={"class": "custom-control-input"}
            ),
            "enable_tithe_fraud_detection": forms.CheckboxInput(
                attrs={"class": "custom-control-input"}
            ),
            "enable_offering_fraud_detection": forms.CheckboxInput(
                attrs={"class": "custom-control-input"}
            ),
        }
        labels = {
            "enable_expense_fraud_detection": "Enable Expense Fraud Detection",
            "enable_other_income_fraud_detection": "Enable Other Income Fraud Detection",
            "enable_donation_fraud_detection": "Enable Donation Fraud Detection",
            "enable_tithe_fraud_detection": "Enable Tithe Fraud Detection",
            "enable_offering_fraud_detection": "Enable Offering Fraud Detection",
        }

