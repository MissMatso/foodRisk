from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("users/<int:pk>/status/", views.UserStatusView.as_view(), name="user_status"),
    path("users/<int:pk>/reset-password/", views.UserPasswordResetView.as_view(), name="user_password_reset"),
    path("users/<int:pk>/role/", views.UserRoleView.as_view(), name="user_role"),
    path("password/change/", views.PasswordChangeFlowView.as_view(), name="password_change"),
    path("password/change/done/", views.PasswordChangeFinishedView.as_view(), name="password_change_done"),
    path("login/", views.CustomLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.UserRegisterView.as_view(), name="register"),
    path("users/", views.UserListView.as_view(), name="user_list"),
]
