#!/usr/bin/env python
"""Создаёт администратора admin или сбрасывает ему пароль на admin123."""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 - не критично для работы скрипта
        pass

    try:
        import django
    except ImportError:
        print("Django не установлен.")
        print("Установите зависимости: pip install -r requirements.txt")
        return 1

    django.setup()

    from django.contrib.auth import get_user_model
    from django.core.management import call_command

    # На случай первого запуска: создаём таблицы, если их ещё нет.
    call_command("migrate", verbosity=0, interactive=False)

    User = get_user_model()
    username = "admin"
    user, created = User.objects.get_or_create(username=username)
    user.is_staff = True
    user.is_superuser = True
    user.is_active = True
    user.set_password("admin123")
    user.save()

    print("=" * 52)
    print(("Создан администратор" if created else "Пароль администратора обновлён"))
    print(f"  логин:  {username}")
    print("  пароль: admin123")
    print("=" * 52)
    print("Запуск: python manage.py runserver")
    print("Вход:   http://127.0.0.1:8000/accounts/login/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
