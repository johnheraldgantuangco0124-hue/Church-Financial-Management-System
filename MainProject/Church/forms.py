# Church/forms.py
from django import forms
from django.contrib.auth import get_user_model
from .models import Church, Denomination, ChurchApplication

User = get_user_model()

class _AdminCredentialsMixin(forms.Form):
    admin_username = forms.CharField(label='Admin Username', min_length=3, max_length=150,
                                     widget=forms.TextInput(attrs={'class': 'form-control'}))
    admin_email = forms.EmailField(label='Admin Email',
                                   widget=forms.EmailInput(attrs={'class': 'form-control'}))
    admin_password = forms.CharField(label='Admin Password', min_length=6,
                                     widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    def clean_admin_username(self):
        uname = self.cleaned_data['admin_username']
        if User.objects.filter(username__iexact=uname).exists():
            raise forms.ValidationError("Username is already taken.")
        return uname

    def clean_admin_email(self):
        email = self.cleaned_data['admin_email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Email is already used.")
        return email


class ChurchSignupForm(forms.ModelForm, _AdminCredentialsMixin):
    class Meta:
        model = Church
        fields = ['name', 'province', 'municipality_or_city', 'barangay', 'purok']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'province': forms.TextInput(attrs={'class': 'form-control'}),
            'municipality_or_city': forms.TextInput(attrs={'class': 'form-control'}),
            'barangay': forms.TextInput(attrs={'class': 'form-control'}),
            'purok': forms.TextInput(attrs={'class': 'form-control'}),
        }


class DenominationSignupForm(forms.ModelForm, _AdminCredentialsMixin):
    class Meta:
        model = Denomination
        fields = ['name', 'contact_email', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_email': forms.EmailInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }


class DenominationChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        # This makes the ID part of the searchable text in the dropdown
        return f"ID: {obj.id} — {obj.name}"

class ChurchApplicationForm(forms.ModelForm):
    denomination = DenominationChoiceField(
        queryset=Denomination.objects.all(),
        widget=forms.Select(attrs={
            'class': 'form-control select2-search',  # Targeted by JS
            'style': 'width: 100%'
        }),
        label="Search Denomination (by ID or Name)"
    )

    class Meta:
        model = ChurchApplication
        fields = ['denomination']

class ChurchProfileForm(forms.ModelForm):
    class Meta:
        model = Church
        fields = [
            'name',
            'province',
            'municipality_or_city',
            'barangay',
            'purok',
            'accounting_lock_date',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter church name'}),
            'province': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter province'}),
            'municipality_or_city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter municipality or city'}),
            'barangay': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter barangay'}),
            'purok': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter purok'}),
            'accounting_lock_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

class DenominationForm(forms.ModelForm):
    class Meta:
        model = Denomination
        fields = ['name', 'description', 'contact_email']