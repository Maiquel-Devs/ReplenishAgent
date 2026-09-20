from django.contrib.auth.forms import AuthenticationForm


INVALID_CREDENTIALS_MESSAGE = (
    "Não foi possível entrar com as credenciais informadas."
)


class ReplenishAuthenticationForm(AuthenticationForm):
    error_messages = {
        "invalid_login": INVALID_CREDENTIALS_MESSAGE,
        "inactive": INVALID_CREDENTIALS_MESSAGE,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Usuário"
        self.fields["username"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "username",
                "autofocus": True,
                "placeholder": "Seu usuário",
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "current-password",
                "placeholder": "Sua senha",
            }
        )
