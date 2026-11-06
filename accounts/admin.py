from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Role", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Role", {"fields": ("role",)}),)
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.must_change_password = True  # a new account has a password someone else chose
        super().save_model(request, obj, form, change)

    def user_change_password(self, request, id, form_url=""):
        response = super().user_change_password(request, id, form_url)
        # A successful change redirects. Whoever set the password, it is not yet the owner's own.
        if request.method == "POST" and response.status_code == 302 and str(request.user.pk) != str(id):
            CustomUser.objects.filter(pk=id).update(must_change_password=True)
        return response
