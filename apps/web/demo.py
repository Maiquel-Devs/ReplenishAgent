"""Local demonstration accounts. Never use these credentials in production."""

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
