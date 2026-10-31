"""Informações fixas da loja e horário de funcionamento (§1.2 e §2 do manual)."""

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import holidays

TIMEZONE = ZoneInfo("America/Campo_Grande")

# §2: segunda a sexta 09h-18h, sábado 09h-13h, domingo e feriados fechado.
_OPENING_HOURS: dict[int, tuple[time, time] | None] = {
    0: (time(9), time(18)),
    1: (time(9), time(18)),
    2: (time(9), time(18)),
    3: (time(9), time(18)),
    4: (time(9), time(18)),
    5: (time(9), time(13)),
    6: None,
}
_WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]

STORE = {
    "nome": "Empório da Música",
    "slogan": "Sua música começa aqui.",
    "fundacao": 2008,
    "endereco": "Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, CEP 79202-333",
    # O manual dá dois números: 3341-4444 (§1.2, "Telefone / WhatsApp") e 3321-4500 (§7, canal de WhatsApp).
    "telefone": "(67) 3341-4444",
    "whatsapp": "(67) 3321-4500",
    # O manual escreve o domínio com acento (empóriodamusica), que não é um endereço válido.
    "email": "contato@emporiodamusica.com.br",
    "horario_de_funcionamento": {
        "segunda a sexta-feira": "09:00 às 18:00",
        "sábado": "09:00 às 13:00",
        "domingo e feriados": "fechado",
    },
    "observacoes": [
        "O atendimento por WhatsApp segue o mesmo horário da loja, com resposta automática fora do expediente.",
        "Em datas especiais (Black Friday, aniversário da loja, Natal) o horário pode ser estendido; a loja avisa com antecedência.",
        "A loja trabalha exclusivamente com instrumentos musicais: não vende cordas, palhetas, cabos, cases, pedais nem amplificadores.",
        "Reclamações são registradas e encaminhadas ao responsável, com retorno em até 24 horas úteis.",
    ],
}

_YEAR_HOLIDAYS: dict[int, holidays.HolidayBase] = {}


def _holiday_name(day: date) -> str | None:
    """Feriado nacional ou de Mato Grosso do Sul, ou o aniversário de Campo Grande (26/08)."""
    if (day.month, day.day) == (8, 26):
        return "Aniversário de Campo Grande"
    if day.year not in _YEAR_HOLIDAYS:
        _YEAR_HOLIDAYS[day.year] = holidays.country_holidays("BR", subdiv="MS", years=day.year, language="pt_BR")
    return _YEAR_HOLIDAYS[day.year].get(day)


def _hours_on(day: date) -> tuple[time, time] | None:
    """Horário de funcionamento do dia, ou None se a loja estiver fechada."""
    return None if _holiday_name(day) else _OPENING_HOURS[day.weekday()]


def _describe_day(day: date, today: date) -> str:
    if day == today:
        return "hoje"
    if day == today + timedelta(days=1):
        return "amanhã"
    return _WEEKDAYS[day.weekday()]


def _next_opening(now: datetime) -> tuple[date, time]:
    for offset in range(0, 15):
        day = now.date() + timedelta(days=offset)
        hours = _hours_on(day)
        if hours and (offset > 0 or now.time() < hours[0]):
            return day, hours[0]
    raise RuntimeError("nenhum dia de funcionamento nos próximos 15 dias")


def store_status(now: datetime | None = None) -> dict[str, Any]:
    """Se a loja está aberta agora e, se não, quando abre de novo (horário de Campo Grande)."""
    now = now.astimezone(TIMEZONE) if now and now.tzinfo else (now or datetime.now(TIMEZONE)).replace(tzinfo=TIMEZONE)
    holiday = _holiday_name(now.date())
    hours = _hours_on(now.date())
    is_open = bool(hours and hours[0] <= now.time() < hours[1])
    status: dict[str, Any] = {
        "agora": f"{_WEEKDAYS[now.weekday()]}, {now:%d/%m/%Y %H:%M} (horário de Campo Grande)",
        "aberta_agora": is_open,
    }
    if holiday:
        status["feriado_hoje"] = holiday
    if hours:
        status["horario_de_hoje"] = f"{hours[0]:%H:%M} às {hours[1]:%H:%M}"
    else:
        status["horario_de_hoje"] = "fechada"
    if is_open:
        status["fecha_as"] = f"{hours[1]:%H:%M}"
    else:
        day, at = _next_opening(now)
        status["proxima_abertura"] = f"{_describe_day(day, now.date())}, {day:%d/%m}, às {at:%H:%M}"
    return status


def store_info(now: datetime | None = None) -> dict[str, Any]:
    """Dados de contato e horário da loja, com a situação atual (aberta ou fechada)."""
    return {**STORE, "situacao_atual": store_status(now)}
