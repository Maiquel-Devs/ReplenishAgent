from typing import Any

from apps.agent.audit_django import DjangoAgentAuditRecorder
from apps.agent.authorization import tool_context_for_user
from apps.agent.core import ReplenishAgent
from apps.agent.providers import LLMProvider, create_llm_provider
from apps.agent.tools import create_default_tool_registry


def run_agent(*, user: Any, message: str, provider: LLMProvider | None = None) -> str:
    selected_provider = provider if provider is not None else create_llm_provider()
    agent = ReplenishAgent(
        provider=selected_provider,
        tools=create_default_tool_registry(),
        context=tool_context_for_user(user),
        audit=DjangoAgentAuditRecorder(),
    )
    return agent.run(message)
