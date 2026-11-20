from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import ClientForm
from .models import Client


@login_required
def client_list(request):
    clients = Client.objects.all()
    return render(request, "core/client_list.html", {"clients": clients})


@login_required
def client_create(request):
    if request.method == "POST":
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            messages.success(request, f"Клиент добавлен: {client.name}")
            return redirect("core:client_list")
    else:
        form = ClientForm()
    return render(request, "core/client_form.html", {"form": form})


@login_required
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == "POST":
        name = client.name
        client.delete()
        messages.success(request, f"Клиент удалён: {name}")
        return redirect("core:client_list")
    return render(request, "core/client_confirm_delete.html", {"client": client})


@login_required
def switch_role(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    if request.method != "POST":
        return redirect("shop:product_list")

    role = request.POST.get("role")
    if role in ("owner", "seller"):
        request.session["view_as"] = role
        messages.info(request, "Режим: " + ("Владелец" if role == "owner" else "Продавец"))

    next_url = request.POST.get("next") or reverse("shop:product_list")
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse("shop:product_list")
    return redirect(next_url)
