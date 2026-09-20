from django.http import HttpRequest

from .authorization import (
    ADMINISTRATION_PERMISSIONS,
    CONFIGURE_AI_PERMISSION,
    REVIEW_PROPOSAL_PERMISSION,
    VIEW_AGENT_AUDIT_PERMISSION,
)


ACTIVE_SECTION_BY_URL = {
    "dashboard": "dashboard",
    "agent_chat": "agent",
    "product_list": "products",
    "product_create": "products",
    "product_detail": "products",
    "product_update": "products",
    "supplier_list": "suppliers",
    "supplier_create": "suppliers",
    "supplier_detail": "suppliers",
    "supplier_update": "suppliers",
    "product_supplier_list": "suppliers",
    "product_supplier_create": "suppliers",
    "inventory_list": "inventory",
    "movement_list": "movements",
    "movement_create": "movements",
    "replenishment_analysis": "replenishment",
    "proposal_create_from_analysis": "replenishment",
    "proposal_list": "proposals",
    "proposal_detail": "proposals",
    "pending_proposals": "pending_proposals",
    "proposal_approve": "pending_proposals",
    "proposal_reject": "pending_proposals",
    "administration_overview": "administration",
    "ai_configuration": "ai_configuration",
    "agent_audit_list": "audit",
    "agent_audit_detail": "audit",
}


def application_navigation(request: HttpRequest) -> dict:
    if not request.user.is_authenticated:
        return {"app_navigation": None}

    can_configure_ai = request.user.has_perm(CONFIGURE_AI_PERMISSION)
    can_review_proposals = request.user.has_perm(REVIEW_PROPOSAL_PERMISSION)
    can_view_audit = request.user.has_perm(VIEW_AGENT_AUDIT_PERMISSION)
    is_administrator = any(
        request.user.has_perm(permission) for permission in ADMINISTRATION_PERMISSIONS
    )
    resolver_match = request.resolver_match
    url_name = resolver_match.url_name if resolver_match else None

    return {
        "app_navigation": {
            "active_section": ACTIVE_SECTION_BY_URL.get(url_name),
            "can_configure_ai": can_configure_ai,
            "can_review_proposals": can_review_proposals,
            "can_view_audit": can_view_audit,
            "show_administration": is_administrator,
            "role_label": "Administrador" if is_administrator else "Operador",
        }
    }
