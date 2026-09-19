from django.contrib import admin

from .models import Inventory, StockMovement


class ReadOnlyInventoryAdmin(admin.ModelAdmin):
    """Keep inventory history and current state writable only by the service."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Inventory)
class InventoryAdmin(ReadOnlyInventoryAdmin):
    list_display = ("product", "current_quantity", "updated_at")
    search_fields = ("product__name", "product__sku")
    list_select_related = ("product",)
    readonly_fields = ("product", "current_quantity", "updated_at")


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyInventoryAdmin):
    list_display = ("product", "type", "quantity", "occurred_at")
    list_filter = ("type", "occurred_at")
    search_fields = ("product__name", "product__sku", "note")
    list_select_related = ("product",)
    readonly_fields = ("product", "type", "quantity", "occurred_at", "note")
