from typing import Any

from apps.agent.audit_django import DjangoAgentAuditRecorder
from apps.agent.authorization import tool_context_for_user
from apps.agent.core import ReplenishAgent
from apps.agent.providers import FakeLLMProvider, LLMResponse
from apps.agent.tools import create_default_tool_registry


PREVIEW_RESPONSE = (
    "A interface do Agent está pronta. A conexão com o provider será "
    "habilitada em uma próxima etapa."
)


def run_preview_agent(*, user: Any, message: str) -> str:
    """Run the existing Agent with a deterministic provider and no external I/O."""
    provider = FakeLLMProvider([LLMResponse(content=PREVIEW_RESPONSE)])
    agent = ReplenishAgent(
        provider=provider,
        tools=create_default_tool_registry(),
        context=tool_context_for_user(user),
        audit=DjangoAgentAuditRecorder(),
    )
    return agent.run(message)
