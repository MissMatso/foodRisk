from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm

from .models import CustomUser
from .passwords import generate_temporary_password


class CustomUserCreationForm(forms.ModelForm):
    """Admin-only form to register a new user account with a role (Use Case: Register User Account).

    The administrator does not choose or type a password. The system generates a
    one-time temporary password (kept on the form as ``temporary_password`` so the
    view can show it once), and the new user must replace it at first sign-in.
    """

    class Meta:
        model = CustomUser
        fields = ("username", "email", "first_name", "last_name", "role")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.temporary_password = None
        for field in self.fields.values():
            css = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            field.widget.attrs.update({"class": css})

    def save(self, commit=True):
        user = super().save(commit=False)
        self.temporary_password = generate_temporary_password()
        user.set_password(self.temporary_password)  # only the hash is stored
        user.must_change_password = True
        if commit:
            user.save()
        return user


class FoodRiskAuthenticationForm(AuthenticationForm):
    """Style Django's real authentication form for the sign-in page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"class": "form-control", "placeholder": "Your username", "autocomplete": "username"}
        )
        self.fields["password"].widget.attrs.update(
            {"class": "form-control", "placeholder": "Your password", "autocomplete": "current-password"}
        )


class StyledPasswordChangeForm(PasswordChangeForm):
    """Django's password change form, with the same input styling as the rest of the app."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})

    def clean(self):
        cleaned = super().clean()
        new_password, old_password = cleaned.get("new_password1"), cleaned.get("old_password")
        if new_password and old_password and new_password == old_password:
            # The old password is usually the temporary one an administrator handed out.
            self.add_error("new_password1", "Your new password must be different from your current password.")
        return cleaned
