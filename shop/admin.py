from django.contrib import admin

from .models import JournalEntry, Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "purchase_price", "quantity")
    search_fields = ("name",)
    list_editable = ("price", "purchase_price")
    ordering = ("name",)


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "product_name",
        "action",
        "quantity",
        "amount_display",
        "reason",
        "payment_method",
        "user",
        "responsible",
    )
    list_filter = ("action", "reason", "payment_method")
    search_fields = ("product_name",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "created_at",
        "unit_price",
        "unit_purchase_price",
    )

    @admin.display(description="Сумма, ₽")
    def amount_display(self, obj):
        if obj.action != JournalEntry.ACTION_SALE:
            return "—"
        return f"{obj.amount:.2f}"
