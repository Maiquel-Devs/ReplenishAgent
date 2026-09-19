from django.contrib import admin

from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "minimum_stock", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "sku")
