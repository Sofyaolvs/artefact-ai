"""Formatação de valores e normalização de texto para busca."""

import re
import unicodedata


def format_brl(cents: int) -> str:
    """59990 -> 'R$ 599,90'; 219900 -> 'R$ 2.199,00'."""
    reais, centavos = divmod(cents, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"


def normalize(text: str) -> str:
    """Minúsculas e sem acentos: 'Violões' -> 'violoes'."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def stem(token: str) -> str:
    """Singulariza de forma grosseira ('violoes' -> 'violao', 'baixos' -> 'baixo')."""
    if token.endswith("oes") and len(token) > 4:
        return token[:-3] + "ao"
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def tokens(text: str) -> list[str]:
    """Palavras normalizadas e singularizadas de um texto."""
    return [stem(t) for t in re.findall(r"[a-z0-9]+", normalize(text))]
