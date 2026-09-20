from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from .audit import AgentExecutionStatus, ToolExecutionStatus
from .tools import ToolPermission


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
            models.Index(fields=("status", "-started_at"), name="agent_exec_status_idx"),
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
