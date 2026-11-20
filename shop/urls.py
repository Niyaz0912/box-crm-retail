from django.urls import path

from . import views

app_name = "shop"

urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("journal/", views.journal, name="journal"),
    path("analytics/", views.analytics, name="analytics"),
    path("products/add/", views.product_add, name="product_add"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("products/<int:pk>/sell/", views.product_sell, name="product_sell"),
    path("products/arrive/", views.product_arrive, name="product_arrive"),
    path("products/writeoff/", views.product_writeoff, name="product_writeoff"),
    path("products/export/", views.export_products, name="export_products"),
    path("products/template/", views.export_template, name="export_template"),
    path("products/import/", views.import_products, name="import_products"),
]
