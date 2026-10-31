"""Cliente de LLM.

O agente conversa com o modelo por um formato de mensagens neutro (dicts simples,
fáceis de salvar em banco); só este módulo conhece o SDK do Gemini. Trocar de
provedor significa escrever outra classe com o mesmo método `generate`.

Mensagens:
    {"role": "user", "text": str}
    {"role": "assistant", "text": str, "tool_calls": [{"name", "args", "signature"}]}
    {"role": "tool", "name": str, "result": dict}
"""

import base64
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from google import genai
from google.genai import errors, types

from emporio_agent import config

TEMPERATURE = 0.2  # atendimento factual: pouca criatividade
_RETRYABLE_CODES = {429, 500, 503}
_MAX_ATTEMPTS = 3


class ConfigError(RuntimeError):
    """Configuração ausente ou inválida (ex.: chave de API)."""


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    # Assinatura de "pensamento" que alguns modelos Gemini exigem de volta na chamada seguinte.
    signature: str | None = None


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    def generate(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse: ...


def to_gemini_contents(messages: list[dict[str, Any]]) -> list[types.Content]:
    """Converte o histórico neutro para o formato do Gemini.

    Respostas de várias tools seguidas viram um único turno do usuário, como o Gemini espera.
    """
    contents: list[types.Content] = []
    for message in messages:
        role = message["role"]
        if role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=message["text"])]))
        elif role == "assistant":
            parts = [types.Part(text=message["text"])] if message.get("text") else []
            for call in message.get("tool_calls", []):
                signature = base64.b64decode(call["signature"]) if call.get("signature") else None
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(name=call["name"], args=call["args"]),
                        thought_signature=signature,
                    )
                )
            contents.append(types.Content(role="model", parts=parts))
        elif role == "tool":
            part = types.Part(
                function_response=types.FunctionResponse(name=message["name"], response={"result": message["result"]})
            )
            if contents and contents[-1].role == "user" and contents[-1].parts[0].function_response:
                contents[-1].parts.append(part)
            else:
                contents.append(types.Content(role="user", parts=[part]))
        else:
            raise ValueError(f"papel de mensagem desconhecido: {role!r}")
    return contents


def parse_response(response: types.GenerateContentResponse) -> LLMResponse:
    """Extrai texto e chamadas de função da resposta, ignorando partes de raciocínio."""
    if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
        return LLMResponse()
    texts, calls = [], []
    for part in response.candidates[0].content.parts:
        if part.function_call:
            signature = base64.b64encode(part.thought_signature).decode() if part.thought_signature else None
            calls.append(ToolCall(part.function_call.name, dict(part.function_call.args or {}), signature))
        elif part.text and not part.thought:
            texts.append(part.text)
    return LLMResponse(text="".join(texts).strip(), tool_calls=calls)


class GeminiClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        api_key = api_key or config.GEMINI_API_KEY
        if not api_key:
            raise ConfigError(
                "GEMINI_API_KEY não definida. Copie .env.example para .env e preencha a chave "
                "(https://aistudio.google.com/apikey)."
            )
        self.model = model or config.GEMINI_MODEL
        self._client = genai.Client(api_key=api_key)

    def generate(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        declarations = [
            types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["parameters"])
            for t in tools
        ]
        generation_config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=TEMPERATURE,
            tools=[types.Tool(function_declarations=declarations)],
            # O loop de tools é do próprio agente (para registrar e limitar cada passo).
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = to_gemini_contents(messages)
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._client.models.generate_content(model=self.model, contents=contents, config=generation_config)
                return parse_response(response)
            except errors.APIError as exc:
                if exc.code not in _RETRYABLE_CODES or attempt == _MAX_ATTEMPTS:
                    raise
                time.sleep(2**attempt)
        raise AssertionError("inalcançável")
