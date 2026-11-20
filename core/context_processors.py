from django.conf import settings


def roles(request):
    """Флаги ролей для шаблонов: владелец, режим продавца, переключатель."""
    user = getattr(request, "user", None)
    can_switch = bool(user and user.is_authenticated and user.is_superuser)

    if can_switch:
        view_as = request.session.get("view_as", "owner")
        if view_as not in ("owner", "seller"):
            view_as = "owner"
    else:
        view_as = "seller"

    return {
        "is_owner": can_switch and view_as == "owner",
        "can_switch_role": can_switch,
        "view_as": view_as,
    }


def assets(request):
    """Версия статики для сброса кеша браузера после обновления продукта."""
    return {"asset_version": getattr(settings, "ASSET_VERSION", "1")}
