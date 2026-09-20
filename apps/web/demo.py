"""Local demonstration accounts. Never use these credentials in production."""

from apps.agent.authorization import AGENT_WRITE_PERMISSION

from .authorization import (
    ADD_PRODUCT_PERMISSION,
    ADD_PRODUCT_SUPPLIER_PERMISSION,
    ADD_PURCHASE_PROPOSAL_PERMISSION,
    ADD_STOCK_MOVEMENT_PERMISSION,
    ADD_SUPPLIER_PERMISSION,
    ADMINISTRATION_PERMISSIONS,
    CHANGE_PRODUCT_PERMISSION,
    CHANGE_SUPPLIER_PERMISSION,
)


DEMO_OPERATOR_PERMISSIONS = (
    ADD_PRODUCT_PERMISSION,
    CHANGE_PRODUCT_PERMISSION,
    ADD_SUPPLIER_PERMISSION,
    CHANGE_SUPPLIER_PERMISSION,
    ADD_PRODUCT_SUPPLIER_PERMISSION,
    ADD_STOCK_MOVEMENT_PERMISSION,
    ADD_PURCHASE_PROPOSAL_PERMISSION,
)
DEMO_ADMIN_PERMISSIONS = (
    *DEMO_OPERATOR_PERMISSIONS,
    AGENT_WRITE_PERMISSION,
    *ADMINISTRATION_PERMISSIONS,
)

DEMO_PASSWORD = "123456"
DEMO_ACCOUNTS = (
    {
        "label": "Admin",
        "username": "admin",
        "password": DEMO_PASSWORD,
        "is_admin": True,
    },
    {
        "label": "Usuário",
        "username": "usuario",
        "password": DEMO_PASSWORD,
        "is_admin": False,
    },
)
