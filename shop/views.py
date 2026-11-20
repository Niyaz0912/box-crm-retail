import logging
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.permissions import owner_required

from . import services
from .analytics import build_analytics
from .excel import export_workbook, import_workbook, template_workbook
from .forms import ProductCreateForm, ProductEditForm
from .models import JournalEntry, Product

logger = logging.getLogger(__name__)


def _safe_next(request):
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return None


def _back(request):
    target = _safe_next(request)
    if target:
        return redirect(target)
    return redirect("shop:product_list")


def _wants_json(request) -> bool:
    """Модалки работают через fetch и ждут JSON, обычные формы — redirect."""
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return True
    return "application/json" in request.headers.get("accept", "")


def _product_payload(product: Product) -> dict:
    return {
        "id": product.pk,
        "name": product.name,
        "price": str(product.price),
        "purchase_price": str(product.purchase_price),
        "quantity": product.quantity,
        "status": product.status,
        "status_label": product.status_label,
    }


def _catalog_summary() -> dict:
    products = list(Product.objects.all())
    total_value = sum(
        (product.price * product.quantity for product in products), Decimal("0.00")
    )
    return {
        "count": len(products),
        "units": sum(product.quantity for product in products),
        "value": f"{total_value:.2f}",
    }


def _form_error(form) -> str:
    for errors in form.errors.values():
        if errors:
            return errors[0]
    return "Проверьте поля формы."


def _error_response(request, message: str, status: int = 400):
    if _wants_json(request):
        return JsonResponse({"ok": False, "error": message}, status=status)
    messages.error(request, message)
    return _back(request)


@login_required
def product_list(request):
    query = (request.GET.get("q") or "").strip()
    products = Product.objects.all()
    if query:
        # SQLite не сворачивает регистр кириллицы в icontains — ищем в Python.
        needle = query.casefold()
        products = [product for product in products if needle in product.name.casefold()]

    all_products = list(Product.objects.all())
    total_units = sum(product.quantity for product in all_products)
    total_value = sum((product.total for product in all_products), Decimal("0.00"))

    context = {
        "products": products,
        "query": query,
        "total_units": total_units,
        "total_value": total_value,
        "products_count": len(all_products),
        "reason_choices": JournalEntry.REASON_CHOICES,
        "payment_choices": JournalEntry.PAYMENT_CHOICES,
        "staff_options": get_user_model().objects.filter(is_active=True).order_by("username"),
    }
    return render(request, "shop/product_list.html", context)


@login_required
@require_POST
def product_sell(request, pk):
    raw_quantity = (request.POST.get("quantity") or "").strip()
    payment_method = request.POST.get("payment_method") or JournalEntry.PAYMENT_CASH

    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        return _error_response(request, "Введите целое количество.")

    try:
        product = services.sell(pk, quantity, payment_method, request.user)
    except Product.DoesNotExist:
        return _error_response(request, "Товар не найден.", status=404)
    except ValueError as error:
        return _error_response(request, str(error))

    payment_label = dict(JournalEntry.PAYMENT_CHOICES)[payment_method]
    message = (
        f"Продано: {product.name} · {quantity} шт · {payment_label} · "
        f"остаток {product.quantity} шт."
    )
    if _wants_json(request):
        return JsonResponse(
            {
                "ok": True,
                "message": message,
                "product": _product_payload(product),
                "summary": _catalog_summary(),
            }
        )
    messages.success(request, message)
    return _back(request)


@login_required
@require_POST
def product_arrive(request):
    product_id = request.POST.get("product_id")
    raw_quantity = (request.POST.get("quantity") or "").strip()

    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        return _error_response(request, "Товар не найден.", status=404)

    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        return _error_response(request, "Введите целое количество.")

    if quantity < 1 or quantity > 100000:
        return _error_response(request, "Количество должно быть от 1 до 100 000.")

    product = services.receive(product.pk, quantity, request.user)
    message = (
        f"Приход: +{quantity} шт · {product.name} · остаток {product.quantity} шт."
    )
    if _wants_json(request):
        return JsonResponse(
            {
                "ok": True,
                "message": message,
                "product": _product_payload(product),
                "summary": _catalog_summary(),
            }
        )
    messages.success(request, message)
    return _back(request)


@owner_required
@require_POST
def product_writeoff(request):
    product_id = request.POST.get("product_id")
    raw_quantity = (request.POST.get("quantity") or "").strip()
    reason = request.POST.get("reason") or ""
    responsible_id = (request.POST.get("responsible") or "").strip()

    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        return _error_response(request, "Товар не найден.", status=404)

    responsible = None
    if responsible_id:
        responsible = get_user_model().objects.filter(pk=responsible_id).first()
        if responsible is None:
            return _error_response(request, "Сотрудник не найден.")

    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        return _error_response(request, "Введите целое количество.")

    try:
        product = services.write_off(
            product.pk, quantity, reason, request.user, responsible=responsible
        )
    except ValueError as error:
        return _error_response(request, str(error))

    message = (
        f"Списано: {quantity} шт · {product.name} · остаток {product.quantity} шт."
    )
    if responsible is not None:
        message += f" · ответственный: {responsible.get_username()}"
    if _wants_json(request):
        return JsonResponse(
            {
                "ok": True,
                "message": message,
                "product": _product_payload(product),
                "summary": _catalog_summary(),
            }
        )
    messages.success(request, message)
    return _back(request)


@owner_required
def product_add(request):
    if request.method == "POST":
        form = ProductCreateForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                product = form.save()
                if product.quantity > 0:
                    services.log_entry(
                        product,
                        JournalEntry.ACTION_ARRIVAL,
                        product.quantity,
                        request.user,
                    )
            messages.success(request, f"Товар добавлен: {product.name}")
            return redirect("shop:product_list")
    else:
        form = ProductCreateForm()
    return render(
        request,
        "shop/product_form.html",
        {"form": form, "title": "Новый товар", "is_edit": False},
    )


@owner_required
@require_POST
def product_edit(request, pk):
    """Редактирование из модального окна: JSON-ответ без перезагрузки страницы."""
    product = get_object_or_404(Product, pk=pk)
    form = ProductEditForm(request.POST, instance=product)
    if not form.is_valid():
        if _wants_json(request):
            errors = {
                field: field_errors[0]
                for field, field_errors in form.errors.items()
                if field != "__all__" and field_errors
            }
            return JsonResponse(
                {
                    "ok": False,
                    "error": _form_error(form),
                    "errors": errors,
                },
                status=400,
            )
        messages.error(request, f"Не удалось сохранить товар: {_form_error(form)}")
        return redirect("shop:product_list")

    product = form.save()
    message = f"Товар обновлён: {product.name}"
    if _wants_json(request):
        return JsonResponse(
            {
                "ok": True,
                "message": message,
                "product": _product_payload(product),
                "summary": _catalog_summary(),
            }
        )
    messages.success(request, message)
    return redirect("shop:product_list")


@owner_required
@require_POST
def product_delete(request, pk):
    """Удаление из модального окна: JSON-ответ без перезагрузки страницы."""
    product = get_object_or_404(Product, pk=pk)
    deleted_id = product.pk
    name = product.name
    product.delete()
    message = f"Товар удалён: {name}"
    if _wants_json(request):
        return JsonResponse(
            {
                "ok": True,
                "message": message,
                "deleted_id": deleted_id,
                "summary": _catalog_summary(),
            }
        )
    messages.success(request, message)
    return redirect("shop:product_list")


@owner_required
def journal(request):
    period = request.GET.get("period", "today")
    now = timezone.localtime()
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == "yesterday":
        start = start_today - timedelta(days=1)
        end = start_today
    elif period == "week":
        start = start_today - timedelta(days=6)
        end = None
    elif period == "month":
        start = start_today - timedelta(days=29)
        end = None
    else:
        period = "today"
        start = start_today
        end = start_today + timedelta(days=1)

    entries = (
        JournalEntry.objects.select_related("product", "user")
        .filter(created_at__gte=start)
    )
    if end is not None:
        entries = entries.filter(created_at__lt=end)
    entries = entries[:500]

    context = {
        "entries": entries,
        "period": period,
        "periods": [
            ("today", "Сегодня"),
            ("yesterday", "Вчера"),
            ("week", "За неделю"),
            ("month", "За месяц"),
        ],
    }
    return render(request, "shop/journal.html", context)


@owner_required
def analytics(request):
    period = request.GET.get("period", "today")
    context = build_analytics(period)
    return render(request, "shop/analytics.html", context)


@login_required
def export_products(request):
    stream = export_workbook()
    response = HttpResponse(
        stream.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    filename = f"boxcrm-products-{timezone.localdate():%Y%m%d}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@owner_required
def export_template(request):
    stream = template_workbook()
    response = HttpResponse(
        stream.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="boxcrm-template.xlsx"'
    return response


@owner_required
def import_products(request):
    result = None
    if request.method == "POST":
        upload = request.FILES.get("file")
        if upload is None:
            messages.error(request, "Выберите файл .xlsx.")
        elif not upload.name.lower().endswith(".xlsx"):
            messages.error(request, "Поддерживаются только файлы .xlsx.")
        else:
            try:
                imported = import_workbook(upload)
            except Exception as error:  # noqa: BLE001 - показываем причину пользователю
                messages.error(request, f"Не удалось прочитать файл: {error}")
            else:
                logger.info(
                    "Импорт Excel: всего %s, создано %s, обновлено %s, пропущено %s",
                    imported["total"],
                    imported["created"],
                    imported["updated"],
                    imported["skipped"],
                )
                # Отчёт показываем после redirect, чтобы F5 не повторял загрузку.
                request.session["import_result"] = imported
                return redirect("shop:import_products")
    else:
        result = request.session.pop("import_result", None)

    return render(request, "shop/import.html", {"result": result})
