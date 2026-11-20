from decimal import Decimal

from django.core.management.base import BaseCommand

from core.models import Client
from shop.models import JournalEntry, Product


class Command(BaseCommand):
    help = "Заполняет базу демо-товарами, клиентами и примерами операций."

    def handle(self, *args, **options):
        if Product.objects.exists():
            self.stdout.write(self.style.WARNING("Товары уже есть — пропускаю товары."))
        else:
            # name, цена, закупка, количество
            products = [
                ("Ручка", Decimal("30.00"), Decimal("18.00"), 20),
                ("Тетрадь", Decimal("25.00"), Decimal("14.00"), 50),
                ("Мыло", Decimal("150.00"), Decimal("95.00"), 10),
                ("Порошок", Decimal("300.00"), Decimal("210.00"), 5),
                ("Блокнот", Decimal("90.00"), Decimal("55.00"), 3),
            ]
            for name, price, purchase_price, quantity in products:
                Product.objects.create(
                    name=name,
                    price=price,
                    purchase_price=purchase_price,
                    quantity=quantity,
                )
            self.stdout.write(self.style.SUCCESS(f"Создано товаров: {len(products)}"))

        if Client.objects.exists():
            self.stdout.write(self.style.WARNING("Клиенты уже есть — пропускаю клиентов."))
        else:
            clients = [
                ("Иван Петров", "+7 999 123-45-67"),
                ("Анна Смирнова", "+7 912 555-10-20"),
            ]
            for name, phone in clients:
                Client.objects.create(name=name, phone=phone)
            self.stdout.write(self.style.SUCCESS(f"Создано клиентов: {len(clients)}"))

        if not JournalEntry.objects.exists():
            product = Product.objects.filter(name="Ручка").first()
            if product:
                JournalEntry.objects.create(
                    product=product,
                    product_name=product.name,
                    action=JournalEntry.ACTION_ARRIVAL,
                    quantity=product.quantity,
                    unit_price=product.price,
                    unit_purchase_price=product.purchase_price,
                    user=None,
                )
                self.stdout.write(self.style.SUCCESS("Добавлена стартовая запись журнала."))

            # Пара демо-продаж, чтобы вкладка «Аналитика» не была пустой.
            demo_sales = [
                ("Ручка", 5, JournalEntry.PAYMENT_CASH),
                ("Мыло", 2, JournalEntry.PAYMENT_CARD),
            ]
            for name, quantity, payment in demo_sales:
                sold = Product.objects.filter(name=name).first()
                if sold is None or sold.quantity < quantity:
                    continue
                sold.quantity -= quantity
                sold.save(update_fields=["quantity", "updated_at"])
                JournalEntry.objects.create(
                    product=sold,
                    product_name=sold.name,
                    action=JournalEntry.ACTION_SALE,
                    quantity=quantity,
                    payment_method=payment,
                    unit_price=sold.price,
                    unit_purchase_price=sold.purchase_price,
                    user=None,
                )
            self.stdout.write(self.style.SUCCESS("Добавлены демо-продажи."))
