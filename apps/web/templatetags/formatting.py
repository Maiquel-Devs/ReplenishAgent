from decimal import Decimal, InvalidOperation

from django import template


register = template.Library()


@register.filter
def brl(value):
    try:
        formatted = f"{Decimal(value):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return "-"
    localized = formatted.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {localized}"
