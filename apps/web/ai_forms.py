"""Form for the global, non-sensitive AI selection."""

from django import forms

from apps.agent.local_endpoint import normalize_local_endpoint
from apps.agent.models import AIConfiguration

from .forms import BootstrapFormMixin


class AIConfigurationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = AIConfiguration
        fields = ("type", "integration", "local_endpoint", "model", "is_active")
        labels = {
            "type": "Tipo",
            "integration": "Runtime ou provider",
            "local_endpoint": "Endpoint do Ollama",
            "model": "Modelo",
            "is_active": "Configuração ativa",
        }
        widgets = {
            "local_endpoint": forms.URLInput(
                attrs={"placeholder": "http://host.docker.internal:11434"}
            ),
            "model": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "placeholder": "Informe o identificador do modelo",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()

    def clean_model(self):
        return self.cleaned_data["model"].strip()


class AIConnectionForm(forms.Form):
    type = forms.ChoiceField(choices=AIConfiguration.Type.choices)
    integration = forms.ChoiceField(choices=AIConfiguration.Integration.choices)
    local_endpoint = forms.CharField(max_length=500, required=False)
    model = forms.CharField(max_length=255, required=False)

    def clean(self):
        cleaned_data = super().clean()
        selected = (
            cleaned_data.get("type"),
            cleaned_data.get("integration"),
        )
        if selected == (AIConfiguration.Type.LOCAL, AIConfiguration.Integration.OLLAMA):
            cleaned_data["local_endpoint"] = normalize_local_endpoint(
                cleaned_data.get("local_endpoint", "")
            )
        elif selected == (
            AIConfiguration.Type.CLOUD,
            AIConfiguration.Integration.MISTRAL,
        ):
            model = cleaned_data.get("model", "").strip()
            if not model:
                self.add_error("model", "Informe o modelo Mistral.")
            elif any(character.isspace() or ord(character) < 32 for character in model):
                self.add_error("model", "Informe um identificador de modelo válido.")
            cleaned_data["model"] = model
            cleaned_data["local_endpoint"] = ""
        else:
            raise forms.ValidationError("Combinação de IA inválida.")
        return cleaned_data
