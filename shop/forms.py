from decimal import Decimal

from django import forms

from .models import Product


class ProductFormBase(forms.ModelForm):
    """Общая валидация названия и цен для создания и редактирования."""

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Введите название товара.")
        # SQLite не сворачивает регистр кириллицы в iexact, поэтому сравниваем в Python.
        key = name.casefold()
        for product in Product.objects.exclude(pk=self.instance.pk):
            if product.name.strip().casefold() == key:
                raise forms.ValidationError("Товар с таким названием уже есть.")
        return name

    def clean_price(self):
        price = self.cleaned_data.get("price")
        if price is None or price < Decimal("0"):
            raise forms.ValidationError("Цена не может быть отрицательной.")
        return price

    def clean_purchase_price(self):
        purchase_price = self.cleaned_data.get("purchase_price")
        if purchase_price is None or purchase_price < Decimal("0"):
            raise forms.ValidationError("Закупочная цена не может быть отрицательной.")
        return purchase_price

    def clean(self):
        cleaned = super().clean()
        price = cleaned.get("price")
        purchase_price = cleaned.get("purchase_price")
        if (
            price is not None
            and purchase_price is not None
            and purchase_price > price
        ):
            self.add_error(
                "purchase_price",
                "Закупочная цена не может быть выше цены продажи.",
            )
        return cleaned


class ProductCreateForm(ProductFormBase):
    class Meta:
        model = Product
        fields = ["name", "price", "purchase_price", "quantity"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Например, Блокнот А6"}
            ),
            "price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
            "purchase_price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
            "quantity": forms.NumberInput(
                attrs={"class": "form-control", "step": "1", "min": "0"}
            ),
        }


class ProductEditForm(ProductFormBase):
    class Meta:
        model = Product
        fields = ["name", "price", "purchase_price"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
            "purchase_price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
        }
