"""Расчёт аналитики для владельца: финансы, товары, продавцы, контроль списаний."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import JournalEntry, Product

PERIODS = [
    ("today", "Сегодня"),
    ("week", "Неделя"),
    ("month", "Месяц"),
]
LOW_STOCK_THRESHOLD = Product.LOW_STOCK_THRESHOLD
SUSPICIOUS_SHORTAGE_LIMIT = Decimal("1000.00")
ZERO = Decimal("0.00")


def _bounds(period: str):
    """Границы периода: сегодня, последние 7 дней или последние 30 дней."""
    now = timezone.localtime()
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return start_today - timedelta(days=6), None
    if period == "month":
        return start_today - timedelta(days=29), None
    return start_today, start_today + timedelta(days=1)


def _sale_unit_price(entry: JournalEntry) -> Decimal:
    """Цена продажи на момент операции (снимок), иначе текущая цена товара."""
    if entry.unit_price is not None:
        return entry.unit_price
    if entry.product is not None:
        return entry.product.price
    return ZERO


def _unit_cost(entry: JournalEntry) -> Decimal:
    """Закупочная цена на момент операции (снимок), иначе текущая закупка."""
    if entry.unit_purchase_price is not None:
        return entry.unit_purchase_price
    if entry.product is not None:
        return entry.product.purchase_price
    return ZERO


def _shortage_unit_value(entry: JournalEntry) -> Decimal:
    """Недостачу считаем по закупке; если закупка не задана — по цене продажи."""
    cost = _unit_cost(entry)
    if cost > 0:
        return cost
    price = _sale_unit_price(entry)
    if price > 0:
        return price
    if entry.product is not None:
        return entry.product.price
    return ZERO


def build_analytics(period: str = "today") -> dict:
    periods = dict(PERIODS)
    if period not in periods:
        period = "today"

    start, end = _bounds(period)
    entries = (
        JournalEntry.objects.select_related("product", "user", "responsible")
        .filter(created_at__gte=start)
        .order_by("-created_at")
    )
    if end is not None:
        entries = entries.filter(created_at__lt=end)
    entries = list(entries)

    revenue = ZERO
    cost = ZERO
    units_sold = 0
    sales_count = 0
    payment = {
        JournalEntry.PAYMENT_CASH: {"total": ZERO, "count": 0},
        JournalEntry.PAYMENT_CARD: {"total": ZERO, "count": 0},
        "other": {"total": ZERO, "count": 0},
    }
    sold_products: dict = {}
    sellers: dict = {}
    shortages: dict = {}
    sold_ids: set = set()
    sold_names: set = set()
    missing_purchase: set = set()

    for entry in entries:
        if entry.action == JournalEntry.ACTION_SALE:
            sales_count += 1
            units_sold += entry.quantity

            unit_price = _sale_unit_price(entry)
            unit_cost = _unit_cost(entry)
            amount = unit_price * entry.quantity
            revenue += amount
            cost += unit_cost * entry.quantity

            method = (
                entry.payment_method
                if entry.payment_method in payment
                else "other"
            )
            payment[method]["total"] += amount
            payment[method]["count"] += 1

            if entry.product_id:
                key = ("id", entry.product_id)
                display_name = entry.product.name
                sold_ids.add(entry.product_id)
                if entry.product.purchase_price <= 0:
                    missing_purchase.add(key)
            else:
                key = ("name", entry.product_name)
                display_name = entry.product_name
            sold_names.add(entry.product_name)
            sold_names.add(display_name)

            product_row = sold_products.setdefault(
                key,
                {"name": display_name, "quantity": 0, "revenue": ZERO},
            )
            product_row["quantity"] += entry.quantity
            product_row["revenue"] += amount

            user = entry.user
            user_key = user.pk if user else None
            seller_row = sellers.setdefault(
                user_key,
                {
                    "name": user.get_username() if user else "—",
                    "is_owner": bool(user and user.is_superuser),
                    "amount": ZERO,
                    "checks": 0,
                    "units": 0,
                },
            )
            seller_row["amount"] += amount
            seller_row["checks"] += 1
            seller_row["units"] += entry.quantity

        elif (
            entry.action == JournalEntry.ACTION_WRITEOFF
            and entry.reason == JournalEntry.REASON_SHORTAGE
        ):
            # Недостача числится за ответственным сотрудником, иначе — за тем, кто списал.
            user = entry.responsible or entry.user
            user_key = user.pk if user else None
            shortage_row = shortages.setdefault(
                user_key,
                {
                    "name": user.get_username() if user else "—",
                    "is_owner": bool(user and user.is_superuser),
                    "amount": ZERO,
                    "count": 0,
                    "units": 0,
                },
            )
            shortage_row["amount"] += _shortage_unit_value(entry) * entry.quantity
            shortage_row["count"] += 1
            shortage_row["units"] += entry.quantity

    profit = revenue - cost
    margin = (profit / revenue * 100) if revenue > 0 else ZERO
    avg_check = (revenue / sales_count) if sales_count else ZERO

    top_products = sorted(
        sold_products.values(),
        key=lambda row: (-row["quantity"], -row["revenue"], row["name"].lower()),
    )[:5]

    dead_products = [
        product
        for product in Product.objects.all()
        if product.pk not in sold_ids and product.name not in sold_names
    ]
    dead_products.sort(key=lambda product: (-product.quantity, -product.total, product.name))
    dead_products = dead_products[:5]

    low_stock = list(
        Product.objects.filter(
            quantity__gt=0, quantity__lte=LOW_STOCK_THRESHOLD
        ).order_by("quantity", "name")
    )

    seller_rows = sorted(
        sellers.values(),
        key=lambda row: (-row["amount"], row["name"].lower()),
    )
    shortage_rows = sorted(
        shortages.values(),
        key=lambda row: (-row["amount"], row["name"].lower()),
    )
    for row in shortage_rows:
        row["suspicious"] = row["amount"] > SUSPICIOUS_SHORTAGE_LIMIT

    return {
        "period": period,
        "period_label": periods[period],
        "periods": PERIODS,
        "finance": {
            "revenue": revenue,
            "cost": cost,
            "profit": profit,
            "margin": margin,
            "sales_count": sales_count,
            "units_sold": units_sold,
            "avg_check": avg_check,
            "cash": payment[JournalEntry.PAYMENT_CASH],
            "card": payment[JournalEntry.PAYMENT_CARD],
            "other": payment["other"],
            "missing_purchase_count": len(missing_purchase),
        },
        "top_products": top_products,
        "dead_products": dead_products,
        "low_stock": low_stock,
        "low_stock_threshold": LOW_STOCK_THRESHOLD,
        "sellers": seller_rows,
        "sellers_total": {
            "amount": sum((row["amount"] for row in seller_rows), ZERO),
            "checks": sum(row["checks"] for row in seller_rows),
        },
        "shortages": shortage_rows,
        "shortage_limit": SUSPICIOUS_SHORTAGE_LIMIT,
        "has_suspicious": any(row["suspicious"] for row in shortage_rows),
    }
