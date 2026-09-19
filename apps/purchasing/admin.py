from django.contrib import admin

from .models import PurchaseProposal


@admin.register(PurchaseProposal)
class PurchaseProposalAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "supplier",
        "quantity",
        "unit_price",
        "total_price",
        "risk_level",
        "status",
        "created_at",
        "reviewed_at",
    )
    list_filter = ("status", "risk_level", "created_at", "reviewed_at")
    search_fields = (
        "product__name",
        "product__sku",
        "supplier__name",
        "supplier__cnpj",
    )
    list_select_related = ("product", "supplier")
    readonly_fields = (
        "product",
        "supplier",
        "quantity",
        "unit_price",
        "total_price",
        "risk_level",
        "status",
        "created_at",
        "updated_at",
        "reviewed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
