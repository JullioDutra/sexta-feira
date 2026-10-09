"""Datas e horas em português do Brasil.

``interpretar_quando`` entende expressões faladas como "amanhã às 7h",
"daqui a 20 minutos", "sexta às 18:30", "dia 15 às 10h", "às 7 e meia da noite".
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from .texto import normalizar

DIAS = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
NOMES_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MESES = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]
NOMES_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
               "agosto", "setembro", "outubro", "novembro", "dezembro"]

_UNIDADES = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13,
    "quatorze": 14, "catorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17,
    "dezoito": 18, "dezenove": 19,
}
_DEZENAS = {"vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60}

_PERIODO_PADRAO = {"madrugada": 3, "cedo": 7, "manha": 8, "tarde": 15, "noite": 20}


def _palavras_para_numeros(texto: str) -> str:
    tokens = texto.split()
    saida: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _DEZENAS:
            valor = _DEZENAS[tok]
            if i + 2 < len(tokens) and tokens[i + 1] == "e" and tokens[i + 2] in _UNIDADES and _UNIDADES[tokens[i + 2]] < 10:
                valor += _UNIDADES[tokens[i + 2]]
                i += 3
            else:
                i += 1
            saida.append(str(valor))
        elif tok in _UNIDADES:
            saida.append(str(_UNIDADES[tok]))
            i += 1
        else:
            saida.append(tok)
            i += 1
    return " ".join(saida)


def _preparar(texto: str) -> str:
    t = normalizar(texto)
    t = t.replace("meio dia", "12:00").replace("meia noite", "meianoite")
    t = re.sub(r"\bmeia hora\b", "30 minutos", t)
    t = _palavras_para_numeros(t)
    t = re.sub(r"\b(\d+) horas? e meia\b", lambda m: f"{int(m.group(1)) * 60 + 30} minutos", t) if re.search(
        r"\b(daqui|em|dentro|apos|depois)\b", t) else t
    return t


def _relativo(t: str, agora: datetime) -> datetime | None:
    m = re.search(
        r"\b(?:daqui a|daqui ha|daqui|em|dentro de|apos|depois de)\s+(\d+(?:[.,]\d+)?)\s*"
        r"(segundos?|seg|s|minutos?|mins?|m|horas?|hrs?|hr|h|dias?|semanas?)\b"
        r"(?:\s*e\s*(\d+)\s*(minutos?|mins?|m|segundos?|seg|s)\b)?",
        t,
    )
    if not m:
        return None
    qtd = float(m.group(1).replace(",", "."))
    unidade = m.group(2)
    if unidade.startswith(("seg",)) or unidade == "s":
        delta = timedelta(seconds=qtd)
    elif unidade.startswith("m"):
        delta = timedelta(minutes=qtd)
    elif unidade.startswith("h"):
        delta = timedelta(hours=qtd)
    elif unidade.startswith("d"):
        delta = timedelta(days=qtd)
    else:
        delta = timedelta(weeks=qtd)
    if m.group(3):
        extra = float(m.group(3))
        delta += timedelta(seconds=extra) if m.group(4).startswith(("s",)) else timedelta(minutes=extra)
    return (agora + delta).replace(microsecond=0)


def _periodo(t: str) -> str | None:
    if re.search(r"\b(da|de) madrugada\b", t):
        return "madrugada"
    if re.search(r"\b(da|de|pela|na) manha\b", t):
        return "manha"
    if re.search(r"\bcedo\b", t):
        return "cedo"
    if re.search(r"\b(da|de|a|pela|na) tarde\b", t):
        return "tarde"
    if re.search(r"\b(da|de|a|pela|na) noite\b", t) or re.search(r"\bhoje a noite\b", t):
        return "noite"
    return None


def _hora(t: str) -> tuple[int, int, bool] | None:
    """Retorna (hora, minuto, formato_explicito)."""
    padroes = [
        (r"\b(\d{1,2}):(\d{2})\b", True),
        (r"\b(\d{1,2})h(\d{2})\b", True),
        (r"\b(\d{1,2})\s*(?:h|hs|hrs?|horas?)\b(?:\s*e\s*(\d{1,2})(?:\s*(?:min|minutos?))?\b)?(?:\s*e\s*(meia))?", True),
        (r"\b(?:as|a|ate|pras|para as|la pelas|pelas)\s+(\d{1,2})(?:\s+e\s+(meia|\d{1,2}))?\b(?!\s*/)", False),
        (r"\b(\d{1,2})\s+e\s+(meia)\b", False),
    ]
    for padrao, explicito in padroes:
        m = re.search(padrao, t)
        if not m:
            continue
        h = int(m.group(1))
        minutos = 0
        grupos = [g for g in m.groups()[1:] if g]
        for g in grupos:
            minutos = 30 if g == "meia" else int(g)
        if h > 24 or minutos > 59:
            continue
        return (0 if h == 24 else h), minutos, explicito
    return None


def _data(t: str, agora: datetime) -> tuple[date | None, int | None, bool]:
    """Retorna (data, dia_da_semana_alvo, forcar_proxima_semana)."""
    hoje = agora.date()
    if "depois de amanha" in t:
        return hoje + timedelta(days=2), None, False
    if re.search(r"\bamanha\b", t):
        return hoje + timedelta(days=1), None, False
    if re.search(r"\bhoje\b", t):
        return hoje, None, False

    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        dia, mes = int(m.group(1)), int(m.group(2))
        ano = int(m.group(3)) if m.group(3) else agora.year
        if ano < 100:
            ano += 2000
        try:
            d = date(ano, mes, dia)
        except ValueError:
            return None, None, False
        if not m.group(3) and d < hoje:
            d = date(ano + 1, mes, dia)
        return d, None, False

    m = re.search(r"\b(?:dia\s+)?(\d{1,2})\s+de\s+(" + "|".join(MESES) + r")(?:\s+de\s+(\d{4}))?\b", t)
    if m:
        dia, mes = int(m.group(1)), MESES.index(m.group(2)) + 1
        ano = int(m.group(3)) if m.group(3) else agora.year
        try:
            d = date(ano, mes, dia)
        except ValueError:
            return None, None, False
        if not m.group(3) and d < hoje:
            d = date(ano + 1, mes, dia)
        return d, None, False

    m = re.search(r"\b(proxima|proximo)?\s*(" + "|".join(DIAS) + r")(?:\s*feira)?(\s+que vem)?\b", t)
    if m:
        alvo = DIAS.index(m.group(2))
        return None, alvo, bool(m.group(1) or m.group(3))

    m = re.search(r"\bdia\s+(\d{1,2})\b", t)
    if m:
        dia = int(m.group(1))
        ano, mes = agora.year, agora.month
        for _ in range(13):
            try:
                d = date(ano, mes, dia)
                if d >= hoje:
                    return d, None, False
            except ValueError:
                pass
            mes += 1
            if mes > 12:
                mes, ano = 1, ano + 1
        return None, None, False
    return None, None, False


def _ajustar_periodo(h: int, periodo: str | None) -> int:
    if periodo in ("tarde", "noite") and 1 <= h < 12:
        return h + 12
    if periodo in ("manha", "madrugada", "cedo") and h == 12:
        return 0
    return h


def interpretar_quando(texto: str, agora: datetime | None = None) -> datetime | None:
    """Converte uma expressão de tempo em ``datetime`` local (sem fuso). ``None`` se não entender."""
    agora = (agora or datetime.now()).replace(microsecond=0)
    bruto = (texto or "").strip()
    if not bruto:
        return None

    # 1) ISO 8601 (o modelo de IA às vezes manda assim)
    try:
        iso = datetime.fromisoformat(bruto.replace("Z", "+00:00"))
        if iso.tzinfo is not None:
            iso = iso.astimezone().replace(tzinfo=None)
        return iso
    except ValueError:
        pass

    t = _preparar(bruto)

    # 2) Relativo: "daqui a 20 minutos"
    rel = _relativo(t, agora)
    if rel:
        return rel

    periodo = _periodo(t)
    meianoite = "meianoite" in t
    hora = (0, 0, True) if meianoite else _hora(t)
    d, dia_semana, proxima = _data(t, agora)

    if d is None and dia_semana is None and hora is None:
        if periodo:  # "hoje à noite" sem hora -> horário padrão do período
            hora = (_PERIODO_PADRAO[periodo], 0, True)
        else:
            return _dateparser(bruto, agora)

    if hora is None:
        h, minuto, explicito = _PERIODO_PADRAO.get(periodo or "", 9), 0, True
    else:
        h, minuto, explicito = hora
        h = _ajustar_periodo(h, periodo)
    ambigua = periodo is None and 1 <= h <= 11

    if dia_semana is not None:
        dias_ate = (dia_semana - agora.weekday()) % 7
        # "sexta" / "próxima sexta" / "sexta que vem" = a primeira sexta que vier;
        # se hoje já é o dia pedido, só vale hoje se o horário ainda não passou.
        if dias_ate == 0:
            hoje_no_horario = datetime.combine(agora.date(), time(h, minuto))
            if proxima or hoje_no_horario <= agora:
                dias_ate = 7
        d = agora.date() + timedelta(days=dias_ate)

    if d is None:
        candidato = datetime.combine(agora.date(), time(h, minuto))
        if meianoite and candidato <= agora:
            candidato += timedelta(days=1)
        elif candidato <= agora:
            if ambigua and candidato + timedelta(hours=12) > agora:
                candidato += timedelta(hours=12)
            else:
                candidato += timedelta(days=1)
        return candidato

    candidato = datetime.combine(d, time(h, minuto))
    if meianoite and d == agora.date():
        candidato += timedelta(days=1)
    if d == agora.date() and candidato <= agora and ambigua and candidato + timedelta(hours=12) > agora:
        candidato += timedelta(hours=12)
    return candidato


def _dateparser(texto: str, agora: datetime) -> datetime | None:
    try:
        import dateparser  # opcional
    except ImportError:
        return None
    resultado = dateparser.parse(
        texto,
        languages=["pt"],
        settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": agora, "RETURN_AS_TIMEZONE_AWARE": False},
    )
    if resultado and resultado > agora:
        return resultado.replace(microsecond=0)
    return None


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------

def formatar_hora(dt: datetime) -> str:
    if dt.minute == 0 and dt.hour == 0:
        return "meia-noite"
    if dt.minute == 0 and dt.hour == 12:
        return "meio-dia"
    return f"{dt.hour}h" if dt.minute == 0 else f"{dt.hour}h{dt.minute:02d}"


def data_extenso(dt: datetime | date) -> str:
    return f"{NOMES_DIAS[dt.weekday()]}, {dt.day} de {NOMES_MESES[dt.month - 1]} de {dt.year}"


def descrever_quando(dt: datetime, agora: datetime | None = None) -> str:
    agora = agora or datetime.now()
    delta = dt - agora
    if timedelta(0) <= delta < timedelta(minutes=1):
        segundos = max(1, round(delta.total_seconds()))
        return f"daqui a {segundos} segundos"
    if timedelta(0) <= delta < timedelta(hours=1):
        minutos = max(1, round(delta.total_seconds() / 60))
        return f"daqui a {minutos} minuto" + ("s" if minutos != 1 else "")
    dias = (dt.date() - agora.date()).days
    hora = formatar_hora(dt)
    prep = {"meia-noite": "à", "meio-dia": "ao"}.get(hora, "às")
    if dias == 0:
        return f"hoje {prep} {hora}"
    if dias == 1:
        return f"amanhã {prep} {hora}"
    if 1 < dias < 7:
        return f"{NOMES_DIAS[dt.weekday()]} {prep} {hora}"
    return f"{dt.day:02d}/{dt.month:02d} {prep} {hora}"


def saudacao(agora: datetime | None = None) -> str:
    h = (agora or datetime.now()).hour
    if 5 <= h < 12:
        return "Bom dia"
    if 12 <= h < 18:
        return "Boa tarde"
    return "Boa noite"
