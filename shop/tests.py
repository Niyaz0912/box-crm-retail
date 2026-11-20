import re
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from . import services
from .excel import HEADERS, import_workbook
from .models import JournalEntry, Product


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
)
class ShopTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser(
            "owner", "owner@example.com", "secret123"
        )
        self.seller = User.objects.create_user(
            "seller", "seller@example.com", "secret123"
        )
        self.product = Product.objects.create(
            name="Ручка",
            price=Decimal("100.00"),
            purchase_price=Decimal("60.00"),
            quantity=30,
        )
        self.product_pk = self.product.pk
        self.client.force_login(self.owner)

    def post_json(self, url, data=None):
        return self.client.post(
            url,
            data or {},
            headers={"x-requested-with": "XMLHttpRequest"},
        )

    def workbook(self, rows, headers=None, title="Товары"):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = title
        sheet.append(headers if headers is not None else HEADERS)
        for row in rows:
            sheet.append(row)
        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)
        return stream

    def csrf_client(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        page = client.get(reverse("shop:product_list"))
        match = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode("utf-8")
        )
        self.assertIsNotNone(match)
        return client, match.group(1)


class SaleTests(ShopTestCase):
    def test_sell_writes_quantity_and_payment(self):
        response = self.post_json(
            reverse("shop:product_sell", args=[self.product_pk]),
            {"quantity": "25", "payment_method": "card"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 5)

        entry = JournalEntry.objects.get(action=JournalEntry.ACTION_SALE)
        self.assertEqual(entry.quantity, 25)
        self.assertEqual(entry.payment_method, JournalEntry.PAYMENT_CARD)
        self.assertEqual(entry.unit_price, Decimal("100.00"))
        self.assertEqual(entry.unit_purchase_price, Decimal("60.00"))
        self.assertEqual(payload["product"]["quantity"], 5)
        self.assertEqual(payload["summary"]["units"], 5)

    def test_sell_fails_when_not_enough_stock(self):
        response = self.post_json(
            reverse("shop:product_sell", args=[self.product_pk]),
            {"quantity": "50", "payment_method": "cash"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("Недостаточно товара на складе", payload["error"])

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 30)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_sell_fails_when_stock_is_zero(self):
        Product.objects.filter(pk=self.product_pk).update(quantity=0)

        response = self.post_json(
            reverse("shop:product_sell", args=[self.product_pk]),
            {"quantity": "1", "payment_method": "cash"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("в наличии 0 шт", response.json()["error"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 0)

    def test_sell_requires_known_payment_method(self):
        response = self.post_json(
            reverse("shop:product_sell", args=[self.product_pk]),
            {"quantity": "1", "payment_method": "crypto"},
        )

        self.assertEqual(response.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 30)

    def test_sell_rejects_non_integer_quantity(self):
        response = self.post_json(
            reverse("shop:product_sell", args=[self.product_pk]),
            {"quantity": "два", "payment_method": "cash"},
        )

        self.assertEqual(response.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 30)

    def test_sell_ajax_passes_csrf_like_browser(self):
        client, token = self.csrf_client()

        response = client.post(
            reverse("shop:product_sell", args=[self.product_pk]),
            {
                "csrfmiddlewaretoken": token,
                "quantity": "2",
                "payment_method": "cash",
            },
            headers={
                "x-csrf-token": token,
                "x-requested-with": "XMLHttpRequest",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 28)


class ProductEditTests(ShopTestCase):
    def test_edit_updates_fields_without_page_reload(self):
        response = self.post_json(
            reverse("shop:product_edit", args=[self.product_pk]),
            {"name": "Ручка синяя", "price": "120.50", "purchase_price": "70.00"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["product"]["name"], "Ручка синяя")

        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Ручка синяя")
        self.assertEqual(self.product.price, Decimal("120.50"))
        self.assertEqual(self.product.purchase_price, Decimal("70.00"))
        self.assertEqual(self.product.quantity, 30)

    def test_edit_rejects_purchase_price_above_sale_price(self):
        response = self.post_json(
            reverse("shop:product_edit", args=[self.product_pk]),
            {"name": "Ручка", "price": "100.00", "purchase_price": "150.00"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("purchase_price", payload["errors"])
        self.assertEqual(
            payload["errors"]["purchase_price"],
            "Закупочная цена не может быть выше цены продажи.",
        )

        self.product.refresh_from_db()
        self.assertEqual(self.product.purchase_price, Decimal("60.00"))

    def test_edit_allows_purchase_price_equal_to_sale_price(self):
        response = self.post_json(
            reverse("shop:product_edit", args=[self.product_pk]),
            {"name": "Ручка", "price": "100.00", "purchase_price": "100.00"},
        )

        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.purchase_price, Decimal("100.00"))

    def test_edit_reports_duplicate_name(self):
        Product.objects.create(name="Тетрадь", price=Decimal("25.00"))

        response = self.post_json(
            reverse("shop:product_edit", args=[self.product_pk]),
            {"name": "тетрадь", "price": "100.00", "purchase_price": "60.00"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("name", payload["errors"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Ручка")

    def test_edit_get_is_not_allowed(self):
        response = self.client.get(
            reverse("shop:product_edit", args=[self.product_pk])
        )
        self.assertEqual(response.status_code, 405)

    def test_seller_cannot_edit(self):
        self.client.force_login(self.seller)
        response = self.post_json(
            reverse("shop:product_edit", args=[self.product_pk]),
            {"name": "Взлом", "price": "1.00", "purchase_price": "0.00"},
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Ручка")


class ProductDeleteTests(ShopTestCase):
    def test_delete_removes_product_and_keeps_journal(self):
        services.sell(self.product_pk, 1, JournalEntry.PAYMENT_CASH, self.owner)

        response = self.post_json(
            reverse("shop:product_delete", args=[self.product_pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted_id"], self.product_pk)
        self.assertFalse(Product.objects.filter(pk=self.product_pk).exists())
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(JournalEntry.objects.get().product_name, "Ручка")

    def test_delete_get_is_not_allowed(self):
        response = self.client.get(
            reverse("shop:product_delete", args=[self.product_pk])
        )
        self.assertEqual(response.status_code, 405)

    def test_seller_cannot_delete(self):
        self.client.force_login(self.seller)
        response = self.post_json(
            reverse("shop:product_delete", args=[self.product_pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.filter(pk=self.product_pk).exists())

    def test_delete_ajax_passes_csrf_like_browser(self):
        client, token = self.csrf_client()
        response = client.post(
            reverse("shop:product_delete", args=[self.product_pk]),
            {"csrfmiddlewaretoken": token},
            headers={
                "x-csrf-token": token,
                "x-requested-with": "XMLHttpRequest",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(pk=self.product_pk).exists())


class ProductListMarkupTests(ShopTestCase):
    def test_list_uses_modals_and_ajax_urls(self):
        response = self.client.get(reverse("shop:product_list"))
        html = response.content.decode("utf-8")

        for modal_id in ("sellModal", "editModal", "deleteModal"):
            self.assertIn(f'id="{modal_id}"', html)
        for form_action in ("sell", "edit", "delete"):
            self.assertIn(f'data-ajax-form="{form_action}"', html)

        self.assertIn(
            f'data-sell-url="{reverse("shop:product_sell", args=[self.product_pk])}"',
            html,
        )
        self.assertIn(
            f'data-edit-url="{reverse("shop:product_edit", args=[self.product_pk])}"',
            html,
        )
        self.assertIn(
            f'data-delete-url="{reverse("shop:product_delete", args=[self.product_pk])}"',
            html,
        )

        # Кнопки не должны быть ссылками на старые страницы.
        self.assertNotIn(
            f'href="{reverse("shop:product_edit", args=[self.product_pk])}"', html
        )
        self.assertNotIn(
            f'href="{reverse("shop:product_delete", args=[self.product_pk])}"', html
        )

    def test_zero_stock_sell_button_is_clickable_with_warning(self):
        Product.objects.filter(pk=self.product_pk).update(quantity=0)

        response = self.client.get(reverse("shop:product_list"))
        html = response.content.decode("utf-8")

        self.assertIn("btn-sell--out", html)
        self.assertIn('data-product-qty="0"', html)
        self.assertNotIn('disabled title="Товар закончился"', html)
        self.assertIn('id="sell-stock-warning"', html)

    def test_template_download_button_is_present(self):
        products = self.client.get(reverse("shop:product_list"))
        self.assertContains(products, "Скачать шаблон Excel")
        self.assertContains(
            products, reverse("shop:export_template")
        )

        import_page = self.client.get(reverse("shop:import_products"))
        self.assertContains(import_page, "Скачать шаблон Excel")
        self.assertContains(
            import_page, reverse("shop:export_template")
        )

    def test_assets_are_versioned_to_bypass_browser_cache(self):
        response = self.client.get(reverse("shop:product_list"))
        html = response.content.decode("utf-8")

        self.assertIn("app.js?v=", html)
        self.assertIn("app.css?v=", html)

    def test_seller_sees_no_purchase_or_owner_buttons(self):
        self.client.force_login(self.seller)
        response = self.client.get(reverse("shop:product_list"))

        self.assertNotContains(response, "Закупка")
        self.assertNotContains(response, 'data-bs-target="#editModal"')
        self.assertNotContains(response, 'data-bs-target="#deleteModal"')

    def test_search_ignores_cyrillic_case(self):
        response = self.client.get(reverse("shop:product_list"), {"q": "ручка"})
        self.assertContains(response, "Ручка")


class ExcelImportTests(ShopTestCase):
    def test_import_four_new_rows_all_created(self):
        stream = self.workbook(
            [
                ["Импорт 1", 100, 60, 5],
                ["Импорт 2", 200, 120, 6],
                ["Импорт 3", 300, 180, 7],
                ["Импорт 4", 400, 240, 8],
            ]
        )

        result = import_workbook(stream)

        self.assertEqual(result["created"], 4)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["total"], 4)
        self.assertEqual(Product.objects.filter(name__startswith="Импорт").count(), 4)

        created = Product.objects.get(name="Импорт 3")
        self.assertEqual(created.price, Decimal("300.00"))
        self.assertEqual(created.purchase_price, Decimal("180.00"))
        self.assertEqual(created.quantity, 7)

    def test_import_counts_each_of_four_rows(self):
        # 1 существующий + 3 новых: в отчёте должно быть 4 обработанных строки.
        stream = self.workbook(
            [
                ["Ручка", 120, 70, 999],
                ["Новый 1", 50, 25, 10],
                ["Новый 2", 60, 30, 20],
                ["Новый 3", 70, 35, 30],
            ]
        )

        result = import_workbook(stream)

        self.assertEqual(result["total"], 4)
        self.assertEqual(result["created"], 3)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(Product.objects.count(), 4)

    def test_import_invalid_price_is_skipped_with_reason(self):
        stream = self.workbook(
            [
                ["Битая", "не число", 10, 1],
                ["Норм", 100, 50, 2],
            ]
        )

        result = import_workbook(stream)

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["skipped_rows"][0]["row"], 2)
        self.assertIn("цена", result["skipped_rows"][0]["reason"])
        self.assertTrue(Product.objects.filter(name="Норм").exists())
        self.assertFalse(Product.objects.filter(name="Битая").exists())

    def test_import_purchase_above_price_is_skipped(self):
        stream = self.workbook([["Дорого", 100, 150, 1]])

        result = import_workbook(stream)

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertIn("выше цены", result["skipped_rows"][0]["reason"])
        self.assertFalse(Product.objects.filter(name="Дорого").exists())

    def test_import_purchase_equal_price_is_allowed(self):
        stream = self.workbook([["Ровно", 100, 100, 1]])

        result = import_workbook(stream)

        self.assertEqual(result["created"], 1)
        self.assertTrue(Product.objects.filter(name="Ровно").exists())

    def test_import_updates_existing_and_keeps_quantity(self):
        stream = self.workbook([["Ручка", 120, 70, 999]])

        result = import_workbook(stream)

        self.product.refresh_from_db()
        self.assertEqual(result["updated"], 1)
        self.assertEqual(self.product.price, Decimal("120.00"))
        self.assertEqual(self.product.purchase_price, Decimal("70.00"))
        self.assertEqual(self.product.quantity, 30)

    def test_import_does_not_erase_purchase_with_empty_cell(self):
        stream = self.workbook([["Ручка", 130, None, 5]])

        result = import_workbook(stream)

        self.product.refresh_from_db()
        self.assertEqual(result["updated"], 1)
        self.assertEqual(self.product.price, Decimal("130.00"))
        self.assertEqual(self.product.purchase_price, Decimal("60.00"))
        self.assertEqual(self.product.quantity, 30)

    def test_import_skips_empty_rows(self):
        stream = self.workbook(
            [
                ["Первый", 10, 5, 1],
                [None, None, None, None],
                ["Второй", 20, 10, 2],
            ]
        )

        result = import_workbook(stream)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["skipped"], 0)

    def test_import_handles_title_row_before_header(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Прайс-лист магазина"])
        sheet.append(HEADERS)
        for name in ("A", "B", "C", "D"):
            sheet.append([name, 10, 5, 1])
        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)

        result = import_workbook(stream)

        self.assertEqual(result["created"], 4)
        self.assertEqual(result["total"], 4)

    def test_import_reads_second_worksheet(self):
        workbook = Workbook()
        info = workbook.active
        info.title = "Инструкция"
        info.append(["Просто текст без таблицы"])

        data = workbook.create_sheet("Товары")
        data.append(HEADERS)
        for name in ("A", "B", "C", "D"):
            data.append([name, 10, 5, 1])

        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)

        result = import_workbook(stream)

        self.assertEqual(result["created"], 4)
        self.assertEqual(Product.objects.filter(name__in=["A", "B", "C", "D"]).count(), 4)

    def test_import_prefers_sheet_with_data_over_empty_sheet(self):
        workbook = Workbook()
        empty = workbook.active
        empty.title = "Пустая таблица"
        empty.append(HEADERS)

        data = workbook.create_sheet("Данные")
        data.append(HEADERS)
        data.append(["Товар", 100, 50, 2])

        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)

        result = import_workbook(stream)

        self.assertEqual(result["created"], 1)
        self.assertTrue(Product.objects.filter(name="Товар").exists())

    def test_import_tolerates_currency_and_spaces(self):
        stream = self.workbook(
            [["Товар", "1 200,50", "800", "3"]],
            headers=["Название", "Цена, ₽", "Закупка", "Кол-во"],
        )

        result = import_workbook(stream)

        self.assertEqual(result["created"], 1)
        product = Product.objects.get(name="Товар")
        self.assertEqual(product.price, Decimal("1200.50"))
        self.assertEqual(product.purchase_price, Decimal("800.00"))
        self.assertEqual(product.quantity, 3)

    def test_import_header_is_case_and_space_insensitive(self):
        stream = self.workbook(
            [["Товар", 100, 50, 2]],
            headers=[" название ", "ЦЕНА", " Закупка ", "Количество"],
        )

        result = import_workbook(stream)

        self.assertEqual(result["created"], 1)

    def test_import_without_header_uses_positional_columns(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Без заголовка", 100, 50, 2])
        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)

        result = import_workbook(stream)

        self.assertEqual(result["created"], 1)
        product = Product.objects.get(name="Без заголовка")
        self.assertEqual(product.price, Decimal("100.00"))
        self.assertEqual(product.quantity, 2)

    def test_import_empty_name_is_skipped(self):
        stream = self.workbook([[None, 100, 50, 1]])

        result = import_workbook(stream)

        self.assertEqual(result["skipped"], 1)
        self.assertIn("название", result["skipped_rows"][0]["reason"])

    def test_import_invalid_purchase_is_skipped(self):
        stream = self.workbook([["Товар", 100, "abc", 1]])

        result = import_workbook(stream)

        self.assertEqual(result["skipped"], 1)
        self.assertIn("закупка", result["skipped_rows"][0]["reason"])


class ExcelViewTests(ShopTestCase):
    def upload(self, stream, filename="products.xlsx"):
        return SimpleUploadedFile(
            filename,
            stream.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_import_view_shows_full_report(self):
        stream = self.workbook(
            [
                ["Импорт 1", 100, 60, 5],
                ["Импорт 2", 200, 120, 6],
                ["Импорт 3", 300, 180, 7],
                ["Импорт 4", 400, 240, 8],
            ]
        )

        response = self.client.post(
            reverse("shop:import_products"),
            {"file": self.upload(stream)},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        result = response.context["result"]
        self.assertEqual(result["created"], 4)
        self.assertEqual(result["total"], 4)
        self.assertContains(response, "Всего строк: 4")
        self.assertContains(response, "Создано: 4")
        self.assertContains(response, "Пропущено: 0")

    def test_import_view_shows_skip_reason(self):
        stream = self.workbook([["Битая", "abc", 10, 1], ["Норм", 100, 50, 1]])

        response = self.client.post(
            reverse("shop:import_products"),
            {"file": self.upload(stream)},
            follow=True,
        )

        self.assertContains(response, "цена не число")
        self.assertContains(response, "Пропущено: 1")

    def test_import_view_rejects_non_xlsx(self):
        upload = SimpleUploadedFile("products.csv", b"a,b,c", content_type="text/csv")

        response = self.client.post(
            reverse("shop:import_products"), {"file": upload}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Поддерживаются только файлы .xlsx")

    def test_import_view_is_owner_only(self):
        self.client.force_login(self.seller)
        response = self.client.get(reverse("shop:import_products"))
        self.assertEqual(response.status_code, 302)

    def test_export_contains_new_columns(self):
        response = self.client.get(reverse("shop:export_products"))

        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content))
        sheet = workbook.active
        self.assertEqual([cell.value for cell in sheet[1]], HEADERS)
        self.assertEqual(sheet["A2"].value, "Ручка")
        self.assertEqual(sheet["B2"].value, 100)
        self.assertEqual(sheet["C2"].value, 60)
        self.assertEqual(sheet["D2"].value, 30)

    def test_template_has_only_headers(self):
        response = self.client.get(reverse("shop:export_template"))

        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content))
        sheet = workbook.active
        self.assertEqual([cell.value for cell in sheet[1]], HEADERS)
        self.assertEqual(sheet.max_row, 1)


class AnalyticsTests(ShopTestCase):
    def setUp(self):
        super().setUp()
        self.product_a = self.product
        self.product_b = Product.objects.create(
            name="Тетрадь",
            price=Decimal("50.00"),
            purchase_price=Decimal("20.00"),
            quantity=2,
        )
        self.product_c = Product.objects.create(
            name="Мыло",
            price=Decimal("200.00"),
            purchase_price=Decimal("120.00"),
            quantity=100,
        )

    def test_finance_and_sellers(self):
        services.sell(self.product_a.pk, 10, JournalEntry.PAYMENT_CASH, self.seller)
        services.sell(self.product_a.pk, 5, JournalEntry.PAYMENT_CARD, self.seller)
        services.sell(self.product_a.pk, 1, JournalEntry.PAYMENT_CASH, self.owner)

        response = self.client.get(reverse("shop:analytics"), {"period": "week"})
        self.assertEqual(response.status_code, 200)

        finance = response.context["finance"]
        self.assertEqual(finance["revenue"], Decimal("1600.00"))
        self.assertEqual(finance["cost"], Decimal("960.00"))
        self.assertEqual(finance["profit"], Decimal("640.00"))
        self.assertEqual(finance["cash"]["total"], Decimal("1100.00"))
        self.assertEqual(finance["cash"]["count"], 2)
        self.assertEqual(finance["card"]["total"], Decimal("500.00"))
        self.assertEqual(finance["card"]["count"], 1)
        self.assertEqual(finance["sales_count"], 3)

        sellers = {row["name"]: row for row in response.context["sellers"]}
        self.assertEqual(sellers["seller"]["amount"], Decimal("1500.00"))
        self.assertEqual(sellers["seller"]["checks"], 2)
        self.assertEqual(sellers["owner"]["amount"], Decimal("100.00"))

    def test_old_sales_are_outside_period(self):
        services.sell(self.product_a.pk, 4, JournalEntry.PAYMENT_CASH, self.seller)

        old_entry = JournalEntry.objects.get(action=JournalEntry.ACTION_SALE)
        JournalEntry.objects.filter(pk=old_entry.pk).update(
            created_at=timezone.now() - timedelta(days=40)
        )

        week = self.client.get(reverse("shop:analytics"), {"period": "week"})
        self.assertEqual(week.context["finance"]["revenue"], Decimal("0.00"))

        month = self.client.get(reverse("shop:analytics"), {"period": "month"})
        self.assertEqual(month.context["finance"]["revenue"], Decimal("0.00"))

    def test_top_products_and_dead_stock(self):
        services.sell(self.product_a.pk, 3, JournalEntry.PAYMENT_CASH, self.seller)
        services.sell(self.product_a.pk, 2, JournalEntry.PAYMENT_CASH, self.seller)
        services.sell(self.product_c.pk, 1, JournalEntry.PAYMENT_CARD, self.seller)

        context = self.client.get(
            reverse("shop:analytics"), {"period": "week"}
        ).context

        top = context["top_products"]
        self.assertEqual(top[0]["name"], "Ручка")
        self.assertEqual(top[0]["quantity"], 5)

        dead_names = [product.name for product in context["dead_products"]]
        self.assertIn("Тетрадь", dead_names)
        self.assertNotIn("Ручка", dead_names)

        low_stock_names = [product.name for product in context["low_stock"]]
        self.assertEqual(low_stock_names, ["Тетрадь"])

    def test_shortage_over_limit_is_flagged(self):
        expensive = Product.objects.create(
            name="Холодильник",
            price=Decimal("5000.00"),
            purchase_price=Decimal("1200.00"),
            quantity=10,
        )
        services.write_off(
            expensive.pk,
            2,
            JournalEntry.REASON_SHORTAGE,
            self.owner,
            responsible=self.seller,
        )

        response = self.client.get(reverse("shop:analytics"), {"period": "week"})
        rows = response.context["shortages"]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "seller")
        self.assertEqual(rows[0]["amount"], Decimal("2400.00"))
        self.assertEqual(rows[0]["units"], 2)
        self.assertTrue(rows[0]["suspicious"])
        self.assertTrue(response.context["has_suspicious"])
        self.assertContains(response, "row-suspicious")

    def test_small_shortage_is_not_flagged(self):
        services.write_off(
            self.product_c.pk,
            1,
            JournalEntry.REASON_SHORTAGE,
            self.owner,
            responsible=self.seller,
        )

        response = self.client.get(reverse("shop:analytics"), {"period": "week"})
        rows = response.context["shortages"]

        self.assertEqual(rows[0]["amount"], Decimal("120.00"))
        self.assertFalse(rows[0]["suspicious"])
        self.assertFalse(response.context["has_suspicious"])

    def test_shortage_without_responsible_counts_for_performer(self):
        services.write_off(
            self.product_c.pk, 1, JournalEntry.REASON_SHORTAGE, self.owner
        )

        context = self.client.get(
            reverse("shop:analytics"), {"period": "week"}
        ).context
        self.assertEqual(context["shortages"][0]["name"], "owner")

    def test_seller_cannot_open_analytics(self):
        self.client.force_login(self.seller)
        response = self.client.get(reverse("shop:analytics"))
        self.assertEqual(response.status_code, 302)


class ValidationAndBrandingTests(ShopTestCase):
    def test_login_page_uses_boxcrm_brand_and_logo(self):
        self.client.logout()
        response = self.client.get(reverse("login"))

        self.assertContains(response, "BoxCRM")
        self.assertContains(response, "boxcrm-logo.png")

    def test_journal_shows_payment_method(self):
        services.sell(self.product_pk, 1, JournalEntry.PAYMENT_CARD, self.owner)

        response = self.client.get(reverse("shop:journal"))
        self.assertContains(response, "Безнал/Карта")

    def test_add_product_saves_purchase_price(self):
        response = self.client.post(
            reverse("shop:product_add"),
            {
                "name": "Блокнот",
                "price": "90.00",
                "purchase_price": "55.00",
                "quantity": "4",
            },
        )

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name="Блокнот")
        self.assertEqual(product.purchase_price, Decimal("55.00"))
        entry = JournalEntry.objects.get(action=JournalEntry.ACTION_ARRIVAL)
        self.assertEqual(entry.unit_price, Decimal("90.00"))
        self.assertEqual(entry.unit_purchase_price, Decimal("55.00"))

    def test_add_product_rejects_purchase_above_price(self):
        response = self.client.post(
            reverse("shop:product_add"),
            {
                "name": "Странный",
                "price": "100.00",
                "purchase_price": "150.00",
                "quantity": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Закупочная цена не может быть выше цены продажи.")
        self.assertFalse(Product.objects.filter(name="Странный").exists())

    def test_writeoff_assigns_responsible_employee(self):
        response = self.client.post(
            reverse("shop:product_writeoff"),
            {
                "product_id": self.product_pk,
                "quantity": "2",
                "reason": JournalEntry.REASON_SHORTAGE,
                "responsible": self.seller.pk,
            },
        )

        self.assertEqual(response.status_code, 302)
        entry = JournalEntry.objects.get(action=JournalEntry.ACTION_WRITEOFF)
        self.assertEqual(entry.responsible, self.seller)
        self.assertEqual(entry.reason, JournalEntry.REASON_SHORTAGE)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 28)

    def test_writeoff_cannot_exceed_stock(self):
        response = self.post_json(
            reverse("shop:product_writeoff"),
            {
                "product_id": self.product_pk,
                "quantity": "50",
                "reason": JournalEntry.REASON_SHORTAGE,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Недостаточно товара на складе", response.json()["error"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 30)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_arrival_updates_stock(self):
        response = self.client.post(
            reverse("shop:product_arrive"),
            {"product_id": self.product_pk, "quantity": "5"},
        )

        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 35)
