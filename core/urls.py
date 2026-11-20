from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.client_list, name="client_list"),
    path("add/", views.client_create, name="client_add"),
    path("<int:pk>/delete/", views.client_delete, name="client_delete"),
]
