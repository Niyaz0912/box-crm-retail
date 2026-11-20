import logging
from decimal import Decimal, InvalidOperation
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .models import Product

logger = logging.getLogger(__name__)

HEADERS = ["Название", "Цена", "Закупка", "Количество"]
MAX_MONEY = Decimal("10000000.00")
ZERO = Decimal("0.00")
MAX_HEADER_SCAN = 15
MAX_SKIP_DETAILS = 50

NAME_KEYS = ("название", "наименование", "товар", "name", "product")
PRICE_KEYS = ("цена", "цена продажи", "price")
PURCHASE_KEYS = ("закупка", "закупочная цена", "закупочная", "purchase", "purchase_price")
QTY_KEYS = ("количество", "кол-во", "колво", "quantity", "qty")

CURRENCY_TOKENS = ("₽", "руб.", "руб", "р.", "шт.", "шт")


def _build_workbook(products: bool) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Товары"
    sheet.append(HEADERS)

    if products:
        for product in Product.objects.order_by("name"):
            sheet.append(
                [
                    product.name,
                    float(product.price),
                    float(product.purchase_price),
                    product.quantity,
                ]
            )

    header_font = Font(bold=True, color="1E3A8A")
    header_fill = PatternFill(fill_type="solid", fgColor="EEF4FF")
    for cell in sheet[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    sheet.row_dimensions[1].height = 22
    sheet.column_dimensions["A"].width = 40
    sheet.column_dimensions["B"].width = 14
    sheet.column_dimensions["C"].width = 14
    sheet.column_dimensions["D"].width = 14
    sheet.freeze_panes = "A2"
    if sheet.max_row > 1:
        sheet.auto_filter.ref = f"A1:D{sheet.max_row}"

    for row in sheet.iter_rows(min_row=2, min_col=2, max_col=3):
        for cell in row:
            cell.number_format = "#,##0.00"

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def export_workbook() -> BytesIO:
    return _build_workbook(products=True)


def template_workbook() -> BytesIO:
    """Пустой файл с правильными колонками — шаблон для заполнения."""
    return _build_workbook(products=False)


def _normalize_header(value) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower().replace("\ufeff", "")
    for token in CURRENCY_TOKENS:
        text = text.replace(token, " ")
    text = " ".join(text.split())
    return text.strip(" .,:;")


def _column_index(header, keys) -> int | None:
    normalized = [_normalize_header(cell) for cell in header]
    for index, title in enumerate(normalized):
        if title in keys:
            return index
    for index, title in enumerate(normalized):
        if title and any(title.startswith(key) for key in keys):
            return index
    return None


def _layout_from_header(header) -> dict:
    return {
        "name": _column_index(header, NAME_KEYS),
        "price": _column_index(header, PRICE_KEYS),
        "purchase": _column_index(header, PURCHASE_KEYS),
        "quantity": _column_index(header, QTY_KEYS),
    }


def _row_is_empty(row) -> bool:
    if row is None:
        return True
    for cell in row:
        if cell is None:
            continue
        if str(cell).strip():
            return False
    return True


def _looks_like_header(row) -> bool:
    layout = _layout_from_header(row)
    return layout["name"] is not None and layout["price"] is not None


def _reset_dimensions(sheet) -> None:
    """В read-only режиме размеры листа могут быть устаревшими и обрезать строки."""
    reset = getattr(sheet, "reset_dimensions", None)
    if callable(reset):
        reset()


def _find_header(sheet):
    """Ищет строку заголовков в первых строках листа. Возвращает (номер, колонки)."""
    rows = sheet.iter_rows(min_row=1, max_row=MAX_HEADER_SCAN, values_only=True)
    for number, row in enumerate(rows, start=1):
        if _row_is_empty(row):
            continue
        if _looks_like_header(row):
            return number, _layout_from_header(row)
    return None, None


def _data_rows_after_header(sheet, header_row: int) -> int:
    count = 0
    rows = sheet.iter_rows(
        min_row=header_row + 1,
        max_row=header_row + MAX_HEADER_SCAN,
        values_only=True,
    )
    for row in rows:
        if not _row_is_empty(row):
            count += 1
    return count


def _pick_sheet(workbook):
    """Лист с заголовками «Название/Цена» и данными; иначе — первый непустой лист."""
    candidates = []
    for sheet in workbook.worksheets:
        _reset_dimensions(sheet)
        header_row, layout = _find_header(sheet)
        if header_row is not None and layout is not None:
            candidates.append(
                (
                    _data_rows_after_header(sheet, header_row),
                    sheet,
                    header_row,
                    layout,
                )
            )

    for score, sheet, header_row, layout in candidates:
        if score > 0:
            return sheet, header_row, layout
    if candidates:
        _, sheet, header_row, layout = candidates[0]
        return sheet, header_row, layout

    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(min_row=1, max_row=MAX_HEADER_SCAN, values_only=True):
            if not _row_is_empty(row):
                return sheet, None, None

    return workbook.active, None, None


def _to_decimal(value) -> Decimal:
    """Цена/закупка в виде числа: поддерживает 1 234,56, 1234.56, «100 ₽»."""
    if isinstance(value, bool):
        raise InvalidOperation
    if isinstance(value, (int, float, Decimal)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise InvalidOperation
        return Decimal(str(value)).quantize(Decimal("0.01"))
    if value is None:
        raise InvalidOperation

    text = str(value).strip().lower()
    if not text:
        raise InvalidOperation

    for token in CURRENCY_TOKENS:
        text = text.replace(token, "")
    text = text.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if not text:
        raise InvalidOperation

    # На случай «1.234.56»: последняя точка — десятичная, остальные — разделители.
    if text.count(".") > 1:
        head, tail = text.rsplit(".", 1)
        text = head.replace(".", "") + "." + tail

    return Decimal(text).quantize(Decimal("0.01"))


def _cell(row, index):
    if index is None or index >= len(row):
        return None
    return row[index]


def _parse_quantity(value) -> int:
    if value is None or not str(value).strip():
        return 0
    try:
        number = _to_decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return 0
    if number < 0:
        return 0
    return int(number)


def import_workbook(file_obj) -> dict:
    """Импорт товаров из .xlsx.

    Ищет лист с заголовками, читает все строки, пропускает пустые.
    Существующим товарам обновляет цену и закупку (количество не трогает),
    новые создаёт. Каждая пропущенная строка попадает в отчёт с причиной.
    """
    workbook = load_workbook(file_obj, data_only=True, read_only=True)
    created = updated = skipped = total = 0
    skipped_rows = []

    def skip(row_number: int, name: str, reason: str) -> None:
        nonlocal skipped
        skipped += 1
        if len(skipped_rows) < MAX_SKIP_DETAILS:
            skipped_rows.append(
                {"row": row_number, "name": name or "—", "reason": reason}
            )
        logger.info(
            "Импорт Excel: строка %s (%s) пропущена: %s",
            row_number,
            name or "—",
            reason,
        )

    try:
        sheet, header_row, layout = _pick_sheet(workbook)
        if layout is None:
            layout = {"name": 0, "price": 1, "purchase": 2, "quantity": 3}

        start_row = 1 if header_row is None else header_row + 1
        rows = sheet.iter_rows(min_row=start_row, values_only=True)

        existing_products = {
            product.name.strip().casefold(): product for product in Product.objects.all()
        }

        for offset, row in enumerate(rows):
            row_number = start_row + offset
            if _row_is_empty(row):
                continue

            total += 1

            raw_name = _cell(row, layout["name"])
            name = str(raw_name or "").strip()
            if not name:
                skip(row_number, "", "пустое название")
                continue
            if len(name) > 200:
                skip(row_number, name[:60], "название длиннее 200 символов")
                continue

            try:
                price = _to_decimal(_cell(row, layout["price"]))
            except (InvalidOperation, TypeError, ValueError):
                skip(row_number, name, "цена не число")
                continue
            if price < 0 or price > MAX_MONEY:
                skip(row_number, name, "цена вне допустимого диапазона")
                continue

            purchase_price = None
            raw_purchase = _cell(row, layout["purchase"])
            if raw_purchase is not None and str(raw_purchase).strip():
                try:
                    purchase_price = _to_decimal(raw_purchase)
                except (InvalidOperation, TypeError, ValueError):
                    skip(row_number, name, "закупка не число")
                    continue
                if purchase_price < 0 or purchase_price > MAX_MONEY:
                    skip(row_number, name, "закупка вне допустимого диапазона")
                    continue

            existing = existing_products.get(name.casefold())
            effective_purchase = (
                purchase_price
                if purchase_price is not None
                else (existing.purchase_price if existing else ZERO)
            )
            if effective_purchase > price:
                skip(
                    row_number,
                    name,
                    "закупочная цена выше цены продажи",
                )
                continue

            quantity = _parse_quantity(_cell(row, layout["quantity"]))

            try:
                if existing:
                    changed_fields = []
                    if existing.price != price:
                        existing.price = price
                        changed_fields.append("price")
                    if (
                        purchase_price is not None
                        and existing.purchase_price != purchase_price
                    ):
                        existing.purchase_price = purchase_price
                        changed_fields.append("purchase_price")

                    if changed_fields:
                        existing.save(update_fields=[*changed_fields, "updated_at"])
                        updated += 1
                    else:
                        skip(row_number, name, "без изменений")
                else:
                    product = Product.objects.create(
                        name=name,
                        price=price,
                        purchase_price=(
                            purchase_price if purchase_price is not None else ZERO
                        ),
                        quantity=quantity,
                    )
                    existing_products[name.casefold()] = product
                    created += 1
            except Exception as error:  # noqa: BLE001 - одна строка не должна ломать импорт
                logger.exception("Импорт Excel: ошибка строки %s", row_number)
                skip(row_number, name, f"ошибка сохранения: {error}")
    finally:
        workbook.close()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total": total,
        "skipped_rows": skipped_rows,
    }
