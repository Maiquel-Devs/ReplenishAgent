from django.contrib import admin

from .models import ProductSupplier, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "cnpj", "email", "phone", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "cnpj", "email")


@admin.register(ProductSupplier)
class ProductSupplierAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "supplier",
        "price",
        "lead_time_days",
        "is_preferred",
        "updated_at",
    )
    list_filter = ("is_preferred", "supplier")
    search_fields = ("product__name", "product__sku", "supplier__name", "supplier__cnpj")
    autocomplete_fields = ("product", "supplier")
