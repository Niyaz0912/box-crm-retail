from decimal import Decimal

from django.conf import settings
from django.db import models


class Product(models.Model):
    LOW_STOCK_THRESHOLD = 5

    name = models.CharField("Название", max_length=200, unique=True)
    price = models.DecimalField("Цена", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    purchase_price = models.DecimalField(
        "Закупочная цена", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    quantity = models.PositiveIntegerField("Количество", default=0)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def status(self) -> str:
        if self.quantity == 0:
            return "out"
        if self.quantity <= self.LOW_STOCK_THRESHOLD:
            return "low"
        return "ok"

    @property
    def status_label(self) -> str:
        return {"out": "Нет", "low": "Мало", "ok": "В наличии"}[self.status]

    @property
    def total(self) -> Decimal:
        return self.price * self.quantity


class JournalEntry(models.Model):
    ACTION_ARRIVAL = "arrival"
    ACTION_SALE = "sale"
    ACTION_WRITEOFF = "writeoff"
    ACTION_CHOICES = [
        (ACTION_ARRIVAL, "Приход"),
        (ACTION_SALE, "Продажа"),
        (ACTION_WRITEOFF, "Списание"),
    ]

    REASON_EXPIRED = "expired"
    REASON_DAMAGED = "damaged"
    REASON_SHORTAGE = "shortage"
    REASON_CHOICES = [
        (REASON_EXPIRED, "Просрочка"),
        (REASON_DAMAGED, "Бой"),
        (REASON_SHORTAGE, "Недостача"),
    ]

    PAYMENT_CASH = "cash"
    PAYMENT_CARD = "card"
    PAYMENT_CHOICES = [
        (PAYMENT_CASH, "Наличные"),
        (PAYMENT_CARD, "Безнал/Карта"),
    ]

    created_at = models.DateTimeField("Дата", auto_now_add=True, db_index=True)
    product = models.ForeignKey(
        Product,
        verbose_name="Товар",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_entries",
    )
    product_name = models.CharField("Название товара", max_length=200)
    action = models.CharField("Действие", max_length=16, choices=ACTION_CHOICES)
    quantity = models.PositiveIntegerField("Количество")
    reason = models.CharField(
        "Причина", max_length=16, choices=REASON_CHOICES, blank=True
    )
    payment_method = models.CharField(
        "Способ оплаты", max_length=8, choices=PAYMENT_CHOICES, blank=True
    )
    unit_price = models.DecimalField(
        "Цена за единицу",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Цена продажи на момент операции",
    )
    unit_purchase_price = models.DecimalField(
        "Закупка за единицу",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Закупочная цена на момент операции",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_entries",
    )
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Ответственный",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="responsible_journal_entries",
        help_text="Сотрудник, за которым числится недостача",
    )

    class Meta:
        verbose_name = "Запись журнала"
        verbose_name_plural = "Журнал операций"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_action_display()} · {self.product_name} · {self.quantity}"

    def save(self, *args, **kwargs):
        if self.product and not self.product_name:
            self.product_name = self.product.name
        super().save(*args, **kwargs)

    @property
    def signed_quantity(self) -> str:
        sign = "+" if self.action == self.ACTION_ARRIVAL else "−"
        return f"{sign}{self.quantity}"

    @property
    def payment_label(self) -> str:
        return self.get_payment_method_display() if self.payment_method else "—"

    @property
    def amount(self) -> Decimal:
        """Сумма операции по цене на момент её проведения."""
        if self.unit_price is None:
            return Decimal("0.00")
        return self.unit_price * self.quantity

