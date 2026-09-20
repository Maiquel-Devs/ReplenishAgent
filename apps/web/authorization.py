from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse


ADD_PRODUCT_PERMISSION = "products.add_product"
CHANGE_PRODUCT_PERMISSION = "products.change_product"
ADD_SUPPLIER_PERMISSION = "suppliers.add_supplier"
CHANGE_SUPPLIER_PERMISSION = "suppliers.change_supplier"
ADD_PRODUCT_SUPPLIER_PERMISSION = "suppliers.add_productsupplier"
ADD_STOCK_MOVEMENT_PERMISSION = "inventory.add_stockmovement"
ADD_PURCHASE_PROPOSAL_PERMISSION = "purchasing.add_purchaseproposal"
REVIEW_PROPOSAL_PERMISSION = "purchasing.review_purchaseproposal"
VIEW_AGENT_AUDIT_PERMISSION = "agent.view_agentexecution"
CONFIGURE_AI_PERMISSION = "agent.configure_ai"
ADMINISTRATION_PERMISSIONS = (
    REVIEW_PROPOSAL_PERMISSION,
    VIEW_AGENT_AUDIT_PERMISSION,
    CONFIGURE_AI_PERMISSION,
)


def permission_required(permission: str):
    def decorator(view: Callable[..., HttpResponse]):
        @login_required
        @wraps(view)
        def wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if not request.user.has_perm(permission):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def administration_required(view: Callable[..., HttpResponse]):
    @login_required
    @wraps(view)
    def wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not any(
            request.user.has_perm(permission)
            for permission in ADMINISTRATION_PERMISSIONS
        ):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped
