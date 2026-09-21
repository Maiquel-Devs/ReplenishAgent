from __future__ import annotations

import json

from apps.agent.providers import LLMMessage, LLMProvider, LLMRole

from .audit import (
    AgentAuditRecorder,
    AgentExecutionStatus,
    NoOpAgentAuditRecorder,
)
from .tools import ToolExecutionContext, ToolExecutionPolicy, ToolRegistry


SYSTEM_PROMPT = """Você é o ReplenishAgent, assistente de reposição de estoque.
Conversa e pedidos sem dados do sistema: responda diretamente, sem Tools.
Para dados reais, use Tools READ; para análises e cálculos, use Tools COMPUTE.
Nunca invente estoque, fornecedor, consumo, risco ou quantidade de reposição.
Se pedir análise ou necessidade de reposição, chame calcular_reposicao antes de responder.
Não conclua reposição com consultar_consumo isolado.
Após calcular_reposicao, use o summary da Tool para explicar estoque, risco e quantidade.
Quantidade recomendada maior que zero indica reposição.
Não confunda planning_days (horizonte) com stock_coverage_days (cobertura); cite valores da Tool.
Estoque current_quantity igual a 0 significa zero unidades, não dado ausente.
minimum_stock é estoque mínimo; reorder_point é ponto de reposição. Não troque esses valores.
Se souber só o nome, passe name à Tool adequada; nunca invente IDs.
Omita argumentos opcionais desconhecidos; não envie null, texto "null" ou zero como placeholder.
Use WRITE somente se o usuário pedir explicitamente para criar uma proposta.
Analisar ou recomendar compra não autoriza criar proposta. Propostas ficam pendentes.
Ações críticas exigem aprovação humana; o backend decide a autorização final."""


class AgentError(Exception):
    """Base exception exposed by the Agent core."""


class AgentIterationLimitError(AgentError):
    """Raised when the provider does not produce a final answer in time."""


class ReplenishAgent:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        tools: ToolRegistry,
        policy: ToolExecutionPolicy | None = None,
        context: ToolExecutionContext | None = None,
        audit: AgentAuditRecorder | None = None,
        max_iterations: int = 8,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        if not isinstance(provider, LLMProvider):
            raise TypeError("provider must implement LLMProvider.")
        if not isinstance(tools, ToolRegistry):
            raise TypeError("tools must be a ToolRegistry.")
        if (
            isinstance(max_iterations, bool)
            or not isinstance(max_iterations, int)
            or max_iterations <= 0
        ):
            raise ValueError("max_iterations must be a positive integer.")
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("system_prompt must be a non-empty string.")
        self.provider = provider
        self.tools = tools
        self.policy = policy or ToolExecutionPolicy()
        self.context = context or ToolExecutionContext()
        self.audit = audit or NoOpAgentAuditRecorder()
        self.max_iterations = max_iterations
        self.system_prompt = system_prompt

    def run(self, user_message: str) -> str:
        if not isinstance(user_message, str) or not user_message.strip():
            raise ValueError("user_message must be a non-empty string.")

        execution = self.audit.start(
            context=self.context,
            provider=type(self.provider).__name__,
            model=str(getattr(self.provider, "model", "") or ""),
            user_request=user_message,
        )
        try:
            return self._run_loop(user_message, execution)
        except AgentIterationLimitError:
            self.audit.fail(
                execution,
                status=AgentExecutionStatus.LIMIT_REACHED,
                error_code="iteration_limit",
            )
            raise
        except Exception:
            self.audit.fail(
                execution,
                status=AgentExecutionStatus.FAILED,
                error_code="agent_error",
            )
            raise

    def _run_loop(self, user_message: str, execution: object) -> str:
        messages = [
            LLMMessage(role=LLMRole.SYSTEM, content=self.system_prompt),
            LLMMessage(role=LLMRole.USER, content=user_message),
        ]
        definitions = self.tools.definitions()

        for iteration in range(self.max_iterations):
            response = self.provider.generate(messages, definitions)
            if not response.tool_calls:
                final_response = response.content or ""
                self.audit.complete(
                    execution,
                    final_response=final_response,
                )
                return final_response

            if iteration == self.max_iterations - 1:
                raise AgentIterationLimitError(
                    "The Agent reached its maximum number of iterations."
                )

            messages.append(
                LLMMessage(
                    role=LLMRole.ASSISTANT,
                    content=response.content or "",
                    tool_calls=response.tool_calls,
                )
            )
            for call in response.tool_calls:
                permission = self.tools.permission_for(call.name)
                result = self.audit.execute_tool(
                    execution,
                    call=call,
                    permission_level=permission.value if permission else "",
                    operation=lambda call=call: self.tools.execute(
                        call,
                        policy=self.policy,
                        context=self.context,
                    ),
                )
                messages.append(
                    LLMMessage(
                        role=LLMRole.TOOL,
                        content=json.dumps(
                            result,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        tool_call_id=call.id,
                        tool_name=call.name,
                    )
                )

        raise AgentIterationLimitError(
            "The Agent reached its maximum number of iterations."
        )
