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


class OllamaConnectionForm(forms.Form):
    type = forms.ChoiceField(choices=AIConfiguration.Type.choices)
    integration = forms.ChoiceField(choices=AIConfiguration.Integration.choices)
    local_endpoint = forms.CharField(max_length=500, required=False)

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("type"),
            cleaned_data.get("integration"),
        ) != (AIConfiguration.Type.LOCAL, AIConfiguration.Integration.OLLAMA):
            raise forms.ValidationError("Teste disponível somente para Local / Ollama.")
        cleaned_data["local_endpoint"] = normalize_local_endpoint(
            cleaned_data.get("local_endpoint", "")
        )
        return cleaned_data
