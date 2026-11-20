from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect


def is_owner(request) -> bool:
    """Владелец — суперпользователь, который не переключился в режим продавца."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_superuser:
        return False
    return request.session.get("view_as", "owner") != "seller"


def owner_required(view):
    """Доступ только владельцу (учитывает «режим продавца» для админа)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_owner(request):
            messages.error(request, "Доступно только владельцу магазина.")
            return redirect("shop:product_list")
        return view(request, *args, **kwargs)

    return wrapper
