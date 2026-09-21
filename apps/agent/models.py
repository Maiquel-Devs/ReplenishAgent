from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .audit import AgentExecutionStatus, ToolExecutionStatus
from .local_endpoint import normalize_local_endpoint
from .tools import ToolPermission


class AIConfiguration(models.Model):
    """The single global, non-sensitive LLM selection."""

    class Type(models.TextChoices):
        LOCAL = "LOCAL", "Local"
        CLOUD = "CLOUD", "Nuvem"

    class Integration(models.TextChoices):
        OLLAMA = "ollama", "Ollama"
        MISTRAL = "mistral", "Mistral"

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    type = models.CharField(max_length=5, choices=Type.choices)
    integration = models.CharField(max_length=20, choices=Integration.choices)
    model = models.CharField(max_length=255)
    local_endpoint = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="agent_ai_singleton"),
            models.CheckConstraint(
                condition=(
                    models.Q(type="LOCAL", integration="ollama")
                    | models.Q(type="CLOUD", integration="mistral")
                ),
                name="agent_ai_supported_pair",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.pk != 1:
            raise ValidationError("Only one global AI configuration is supported.")
        if (self.type, self.integration) not in {
            (self.Type.LOCAL, self.Integration.OLLAMA),
            (self.Type.CLOUD, self.Integration.MISTRAL),
        }:
            raise ValidationError(
                {"integration": "Integração incompatível com o tipo selecionado."}
            )
        if self.type == self.Type.LOCAL:
            try:
                self.local_endpoint = normalize_local_endpoint(self.local_endpoint)
            except ValidationError as exc:
                raise ValidationError({"local_endpoint": exc.messages}) from exc
        elif self.local_endpoint:
            raise ValidationError(
                {"local_endpoint": "Endpoint permitido somente para runtime local."}
            )
        self.model = (self.model or "").strip()
        if not self.model:
            raise ValidationError({"model": "Informe o modelo."})
        if len(self.model) > 255:
            raise ValidationError({"model": "O modelo deve ter até 255 caracteres."})
        if any(character.isspace() or ord(character) < 32 for character in self.model):
            raise ValidationError({"model": "O modelo não pode conter espaços."})

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.get_type_display()} / {self.get_integration_display()}"


class AIConfigurationChange(models.Model):
    """Administrative change event, deliberately excluding credentials and model text."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    type = models.CharField(max_length=5)
    integration = models.CharField(max_length=20)
    is_active = models.BooleanField()
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-changed_at", "-pk")


class AgentExecution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="agent_executions",
        null=True,
        blank=True,
    )
    provider = models.CharField(max_length=100)
    model = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[(status.value, status.value) for status in AgentExecutionStatus],
        default=AgentExecutionStatus.RUNNING.value,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    user_request = models.TextField()
    final_response = models.TextField(blank=True)
    error_code = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ("-started_at",)
        indexes = [
            models.Index(
                fields=("status", "-started_at"), name="agent_exec_status_idx"
            ),
        ]
        permissions = [
            ("execute_agent_write", "Can execute Agent write tools"),
            ("configure_ai", "Can view and configure AI settings"),
        ]

    def __str__(self) -> str:
        return f"Agent execution {self.pk} ({self.status})"


class AgentToolExecution(models.Model):
    execution = models.ForeignKey(
        AgentExecution,
        on_delete=models.CASCADE,
        related_name="tool_executions",
    )
    tool_name = models.CharField(max_length=150)
    tool_call_id = models.CharField(max_length=255)
    permission_level = models.CharField(
        max_length=10,
        choices=[(permission.value, permission.value) for permission in ToolPermission],
        blank=True,
    )
    status = models.CharField(
        max_length=10,
        choices=[(status.value, status.value) for status in ToolExecutionStatus],
        default=ToolExecutionStatus.RUNNING.value,
    )
    arguments = models.JSONField(default=dict)
    result = models.JSONField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ("started_at", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("execution", "tool_call_id"),
                name="agent_tool_execution_call_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=("status", "-started_at"),
                name="agent_tool_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.tool_name} ({self.status})"
