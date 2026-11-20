from django.db import models


class Client(models.Model):
    name = models.CharField("Имя", max_length=120)
    phone = models.CharField("Телефон", max_length=32)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенты"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.phone})"
