"""Loop do agente: o modelo decide quando consultar as tools e o código as executa.

O histórico é uma lista de mensagens neutras (ver `llm.py`) alterada no lugar,
para quem chama poder persistir só o que foi acrescentado em cada turno.
"""

from pathlib import Path
from typing import Any

from emporio_agent.llm import LLMClient
from emporio_agent.tools import ToolBox

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"
MAX_STEPS = 6  # idas ao modelo por mensagem do cliente, para não girar em falso
FALLBACK_REPLY = (
    "Desculpe, tive um problema para concluir essa consulta agora. Pode repetir a pergunta? "
    "Se preferir, fale com a equipe pelo WhatsApp (67) 3321-4500."
)


class Agent:
    def __init__(self, llm: LLMClient, toolbox: ToolBox, system_prompt: str | None = None, max_steps: int = MAX_STEPS):
        self.llm = llm
        self.toolbox = toolbox
        self.system_prompt = system_prompt if system_prompt is not None else SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        self.max_steps = max_steps

    def _system(self) -> str:
        """Prompt do sistema com a data e hora atuais, necessárias para prazos e horário."""
        now = self.toolbox.informacoes_da_loja()["situacao_atual"]["agora"]
        return f"{self.system_prompt.rstrip()}\n\nAgora: {now}."

    def respond(self, history: list[dict[str, Any]], user_text: str) -> str:
        """Responde a uma mensagem do cliente e acrescenta o turno inteiro a `history`."""
        history.append({"role": "user", "text": user_text})
        system = self._system()
        for _ in range(self.max_steps):
            response = self.llm.generate(system, history, self.toolbox.declarations)
            if not response.tool_calls:
                reply = response.text or FALLBACK_REPLY
                history.append({"role": "assistant", "text": reply})
                return reply
            history.append(
                {
                    "role": "assistant",
                    "text": response.text,
                    "tool_calls": [{"name": c.name, "args": c.args, "signature": c.signature} for c in response.tool_calls],
                }
            )
            for call in response.tool_calls:
                history.append({"role": "tool", "name": call.name, "result": self.toolbox.call(call.name, call.args)})
        history.append({"role": "assistant", "text": FALLBACK_REPLY})
        return FALLBACK_REPLY
