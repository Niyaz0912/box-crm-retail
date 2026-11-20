from django.db import transaction

from .models import JournalEntry, Product


def log_entry(
    product: Product,
    action: str,
    quantity: int,
    user,
    reason: str = "",
    payment_method: str = "",
    responsible=None,
) -> JournalEntry:
    """Создаёт запись журнала и фиксирует цены товара на момент операции."""
    return JournalEntry.objects.create(
        product=product,
        product_name=product.name,
        action=action,
        quantity=quantity,
        reason=reason,
        payment_method=payment_method,
        unit_price=product.price,
        unit_purchase_price=product.purchase_price,
        user=user,
        responsible=responsible,
    )


@transaction.atomic
def sell(product_id: int, quantity: int, payment_method: str, user) -> Product:
    """Списывает проданное количество и пишет продажу со способом оплаты."""
    if quantity < 1:
        raise ValueError("Количество должно быть положительным.")
    if quantity > 100000:
        raise ValueError("Количество должно быть от 1 до 100 000.")
    if payment_method not in dict(JournalEntry.PAYMENT_CHOICES):
        raise ValueError("Выберите способ оплаты.")

    product = Product.objects.select_for_update().get(pk=product_id)
    if quantity > product.quantity:
        raise ValueError(
            "Недостаточно товара на складе: "
            f"в наличии {product.quantity} шт."
        )

    product.quantity -= quantity
    product.save(update_fields=["quantity", "updated_at"])
    log_entry(
        product,
        JournalEntry.ACTION_SALE,
        quantity,
        user,
        payment_method=payment_method,
    )
    return product


@transaction.atomic
def receive(product_id: int, quantity: int, user) -> Product:
    if quantity < 1:
        raise ValueError("Количество должно быть положительным.")
    if quantity > 100000:
        raise ValueError("Количество должно быть от 1 до 100 000.")

    product = Product.objects.select_for_update().get(pk=product_id)
    product.quantity += quantity
    product.save(update_fields=["quantity", "updated_at"])
    log_entry(product, JournalEntry.ACTION_ARRIVAL, quantity, user)
    return product


@transaction.atomic
def write_off(
    product_id: int, quantity: int, reason: str, user, responsible=None
) -> Product:
    if quantity < 1:
        raise ValueError("Количество должно быть положительным.")
    if reason not in dict(JournalEntry.REASON_CHOICES):
        raise ValueError("Не выбрана причина списания.")

    product = Product.objects.select_for_update().get(pk=product_id)
    if quantity > product.quantity:
        raise ValueError(
            "Недостаточно товара на складе: "
            f"в наличии {product.quantity} шт."
        )

    product.quantity -= quantity
    product.save(update_fields=["quantity", "updated_at"])
    log_entry(
        product,
        JournalEntry.ACTION_WRITEOFF,
        quantity,
        user,
        reason,
        responsible=responsible,
    )
    return product
