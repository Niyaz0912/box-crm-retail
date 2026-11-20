from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core import views as core_views

admin.site.site_header = "BoxCRM"
admin.site.site_title = "BoxCRM"
admin.site.index_title = "Управление магазином"

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("switch-role/", core_views.switch_role, name="switch_role"),
    path("clients/", include("core.urls")),
    path("", include("shop.urls")),
]
