"""Converte o manual de políticas (PDF) em Markdown, uma única vez.

Usa o `pdftotext -raw` (poppler): os extratores de PDF em Python testados
(pypdf) quebram o texto em uma palavra por linha e embaralham as tabelas. O
Markdown gerado é versionado em `data/politicas_da_loja.md` e é ele que o
agente indexa em tempo de execução, então o poppler só é necessário para
refazer a conversão.

Uso: python scripts/pdf_to_markdown.py
"""

import re
import subprocess
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PDF = DATA_DIR / "politicas_da_loja.pdf"
OUT = DATA_DIR / "politicas_da_loja.md"

_RUNNING_HEADER = "Empório da Música Manual de Políticas e Procedimentos"
_PAGE_FOOTER = re.compile(r"^Página \d+$")
_SECTION = re.compile(r"^(\d{1,2})\. (\S.*)$")
_SUBSECTION = re.compile(r"^(\d{1,2}\.\d{1,2}) (\S.*)$")


def convert(text: str) -> str:
    lines = []
    next_section = 1
    for raw in text.replace("​", "").splitlines():
        line = raw.strip()
        if not line or line == _RUNNING_HEADER or _PAGE_FOOTER.match(line):
            continue
        section = _SECTION.match(line)
        # Só vira título o número esperado na sequência: isso diferencia a
        # seção "7." dos itens numerados "1." a "5." do fluxo de atendimento (§7.2).
        if section and int(section.group(1)) == next_section:
            lines += ["", f"## {section.group(1)}. {section.group(2)}", ""]
            next_section += 1
        elif next_section == 1:
            continue  # capa do manual; endereço e telefone repetem na seção 1.2
        elif _SUBSECTION.match(line):
            lines += ["", f"### {line}", ""]
        elif line.startswith("•"):
            lines.append("- " + line.removeprefix("•").strip())
        else:
            lines.append(line)
    return "# Manual de Políticas e Procedimentos — Empório da Música\n" + "\n".join(lines).strip("\n") + "\n"


def main() -> None:
    text = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", "-raw", str(PDF), "-"],
        capture_output=True, check=True, encoding="utf-8",
    ).stdout
    OUT.write_text(convert(text), encoding="utf-8")
    print(f"gerado {OUT}")


if __name__ == "__main__":
    main()
