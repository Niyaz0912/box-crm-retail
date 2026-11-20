from django import forms

from .models import Client


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["name", "phone"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Иван Петров"}),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "+7 (999) 123-45-67"}
            ),
        }

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) < 10 or len(digits) > 15:
            raise forms.ValidationError("Телефон должен содержать от 10 до 15 цифр.")
        return phone
