"""Busca no manual de políticas da loja.

O manual (`data/politicas_da_loja.md`) é dividido por seção e subseção, e cada
trecho vira um documento do índice BM25. A busca é lexical: o texto é pequeno,
e o trecho certo costuma ter as mesmas palavras da pergunta (troca, frete,
parcela...). Devolve sempre o número da seção para a resposta poder citar a regra.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from emporio_agent.config import DATA_DIR
from emporio_agent.formatting import tokens

MANUAL = DATA_DIR / "politicas_da_loja.md"
DEFAULT_TOP_K = 3

_HEADING = re.compile(r"^#{2,3} (\d{1,2}(?:\.\d{1,2})?)\.? (.+)$")
_STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
    "e", "ou", "que", "se", "por", "para", "com", "sem", "ao", "aos", "eu", "me", "meu", "minha",
    "voce", "posso", "pode", "podem", "qual", "quais", "como", "quando", "tem", "ter", "ser", "e",
}
# Palavras comuns da pergunta que não aparecem no manual com a mesma raiz.
_SYNONYMS = {"hora": "horario", "abre": "horario", "fecha": "horario", "aberto": "horario", "fechado": "horario"}


@dataclass(frozen=True)
class Section:
    number: str
    title: str
    text: str

    @property
    def index_text(self) -> str:
        return f"{self.title} {self.title} {self.text}"  # o título pesa mais que o corpo


def _keywords(text: str) -> list[str]:
    """Palavras da busca; o prefixo de 5 letras junta 'devolver', 'devolução', 'devoluções'."""
    return [_SYNONYMS.get(t, t)[:5] for t in tokens(text) if t not in _STOPWORDS]


def parse_manual(markdown: str) -> list[Section]:
    sections: list[Section] = []
    number = title = None
    body: list[str] = []

    def flush() -> None:
        if number and "\n".join(body).strip():
            sections.append(Section(number, title, "\n".join(body).strip()))

    for line in markdown.splitlines():
        heading = _HEADING.match(line)
        if heading:
            flush()
            number, title, body = heading.group(1), heading.group(2).strip(), []
        elif number:
            body.append(line)
    flush()
    return sections


class PolicySearch:
    def __init__(self, sections: list[Section]):
        self.sections = sections
        self._bm25 = BM25Okapi([_keywords(s.index_text) for s in sections])

    def search(self, question: str, top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
        words = _keywords(question)
        if not words:
            return []
        scores = self._bm25.get_scores(words)
        ranked = sorted(zip(scores, self.sections), key=lambda pair: pair[0], reverse=True)
        return [
            {"secao": s.number, "titulo": s.title, "texto": s.text}
            for score, s in ranked[:top_k]
            if score > 0
        ]


@lru_cache(maxsize=1)
def load_policy_search(path: Path = MANUAL) -> PolicySearch:
    return PolicySearch(parse_manual(path.read_text(encoding="utf-8")))


def consult_policies(question: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    """Trechos do manual mais relevantes para a pergunta."""
    found = load_policy_search().search(question, top_k)
    if not found:
        return {
            "encontrado": False,
            "mensagem": (
                "O manual não cobre esse assunto. Não invente a regra: diga ao cliente que vai "
                "confirmar com a gerência (§10 do manual)."
            ),
        }
    return {"encontrado": True, "trechos": found}
