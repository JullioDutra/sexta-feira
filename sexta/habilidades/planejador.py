"""Planejamento: "planeja meu dia", revisão do dia e plano da semana.

O dia é montado assim:
1. compromissos da agenda, lembretes com horário e o almoço são blocos fixos;
2. as tarefas pendentes entram nos horários livres por urgência (atrasadas, prazo, prioridade);
3. tarefa longa é dividida em blocos de até 90 min; a cada ~90 min de trabalho entra uma pausa de 15.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..util.tempo import formatar_hora
from .tarefas import ESTIMATIVA_PADRAO, chave_urgencia

BLOCO_MAX_MIN = 90
PAUSA_MIN = 15
MINIMO_MIN = 20  # sobra de tempo menor que isso não recebe tarefa


@dataclass
class Bloco:
    inicio: datetime
    fim: datetime
    titulo: str
    tipo: str            # "evento", "lembrete", "almoco", "tarefa", "pausa"
    tarefa_id: int | None = None
    extra: dict = field(default_factory=dict)

    def para_dict(self) -> dict:
        return {"inicio": self.inicio.strftime("%H:%M"), "fim": self.fim.strftime("%H:%M"), "titulo": self.titulo,
                "tipo": self.tipo, "tarefa_id": self.tarefa_id, "minutos": int((self.fim - self.inicio).total_seconds() // 60),
                **self.extra}


def _hora(texto: str, dia: date) -> datetime:
    h, m = (int(x) for x in texto.split(":"))
    return datetime.combine(dia, datetime.min.time()).replace(hour=h, minute=m)


def _arredondar(momento: datetime, minutos: int = 15) -> datetime:
    resto = momento.minute % minutos
    base = momento.replace(second=0, microsecond=0)
    return base if resto == 0 and momento.second == 0 else base + timedelta(minutes=minutos - resto)


def planejar_dia(agora: datetime, tarefas: list[dict], fixos: list[Bloco], inicio_expediente: str = "09:00",
                 fim_expediente: str = "18:00", almoco: str | None = "12:00-13:00") -> tuple[list[Bloco], list[dict]]:
    """Devolve (blocos em ordem, tarefas que não couberam)."""
    dia = agora.date()
    comeco = max(_hora(inicio_expediente, dia), _arredondar(agora))
    fim = _hora(fim_expediente, dia)
    blocos = [b for b in fixos if b.fim > comeco and b.inicio < fim]
    if almoco:
        a_ini, a_fim = (_hora(x, dia) for x in almoco.split("-"))
        if a_fim > comeco and not any(b.inicio < a_fim and b.fim > a_ini for b in blocos):
            blocos.append(Bloco(max(a_ini, comeco), a_fim, "Almoço", "almoco"))
    blocos.sort(key=lambda b: b.inicio)

    # horários livres entre os blocos fixos
    livres: list[list[datetime]] = []
    cursor = comeco
    for b in blocos:
        if b.inicio > cursor:
            livres.append([cursor, b.inicio])
        cursor = max(cursor, b.fim)
    if cursor < fim:
        livres.append([cursor, fim])

    fila = []
    for t in sorted([t for t in tarefas if t["status"] != "feito"], key=chave_urgencia):
        fila.append([t, int(t.get("estimativa") or ESTIMATIVA_PADRAO)])
    sobras: list[dict] = []
    trabalhado = 0  # minutos seguidos de trabalho (para a pausa)
    novos: list[Bloco] = []
    for intervalo in livres:
        inicio_livre, fim_livre = intervalo
        trabalhado = 0
        while fila and (fim_livre - inicio_livre) >= timedelta(minutes=MINIMO_MIN):
            if trabalhado and BLOCO_MAX_MIN - trabalhado < MINIMO_MIN:  # hora da pausa
                if (fim_livre - inicio_livre) < timedelta(minutes=PAUSA_MIN + MINIMO_MIN):
                    break
                novos.append(Bloco(inicio_livre, inicio_livre + timedelta(minutes=PAUSA_MIN), "Pausa", "pausa"))
                inicio_livre += timedelta(minutes=PAUSA_MIN)
                trabalhado = 0
                continue
            tarefa, restante = fila[0]
            disponivel = int((fim_livre - inicio_livre).total_seconds() // 60)
            duracao = min(restante, BLOCO_MAX_MIN - trabalhado if trabalhado else BLOCO_MAX_MIN, disponivel)
            if duracao < MINIMO_MIN and restante > duracao:
                break
            parte = "" if duracao >= int(tarefa.get("estimativa") or ESTIMATIVA_PADRAO) else " (parte)"
            novos.append(Bloco(inicio_livre, inicio_livre + timedelta(minutes=duracao), tarefa["titulo"] + parte, "tarefa",
                               tarefa["id"], {"prioridade": tarefa.get("prioridade"), "prazo_texto": tarefa.get("prazo_texto", "")}))
            inicio_livre += timedelta(minutes=duracao)
            trabalhado += duracao
            fila[0][1] -= duracao
            if fila[0][1] <= 0:
                fila.pop(0)
    sobras = [t for t, _ in fila]
    return sorted(blocos + novos, key=lambda b: b.inicio), sobras


def resumo_do_plano(blocos: list[Bloco], sobras: list[dict]) -> str:
    tarefas = [b for b in blocos if b.tipo == "tarefa"]
    compromissos = [b for b in blocos if b.tipo in ("evento", "lembrete")]
    if not tarefas and not compromissos:
        return "Seu dia está livre: nenhuma tarefa pendente nem compromisso."
    partes = []
    if compromissos:
        partes.append("Compromissos: " + "; ".join(f"{b.titulo} às {formatar_hora(b.inicio)}" for b in compromissos[:3]) + ".")
    if tarefas:
        primeiros = "; ".join(f"{formatar_hora(b.inicio)}, {b.titulo}" for b in tarefas[:3])
        partes.append(f"Montei {len(tarefas)} blocos de trabalho. Começando: {primeiros}.")
    if sobras:
        partes.append(f"{len(sobras)} tarefa{'s' if len(sobras) > 1 else ''} não coube{'ram' if len(sobras) > 1 else ''} hoje.")
    return " ".join(partes)


def blocos_fixos(app, dia: date) -> list[Bloco]:
    fixos: list[Bloco] = []
    for ev in app.agenda.do_dia(dia):
        if not ev["dia_inteiro"]:
            fixos.append(Bloco(ev["inicio"], ev["fim"], ev["titulo"], "evento"))
    for l in app.lembretes.do_dia(datetime.combine(dia, datetime.min.time())):
        quando = datetime.fromisoformat(l["quando"])
        fixos.append(Bloco(quando, quando + timedelta(minutes=15), l["texto"], "lembrete"))
    return fixos


def plano_da_semana(app, hoje: date) -> tuple[str, list[dict]]:
    """Tarefas com prazo e compromissos de cada dia dos próximos 7 dias."""
    dias = []
    pendentes = app.tarefas.pendentes()
    inicio = datetime.combine(hoje, datetime.min.time())
    eventos = app.agenda.eventos(inicio, inicio + timedelta(days=7))
    nomes = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    for i in range(7):
        dia = hoje + timedelta(days=i)
        tarefas_dia = [t["titulo"] for t in pendentes if t["prazo"] == dia.isoformat()]
        eventos_dia = [e["titulo"] for e in eventos if e["inicio"].date() == dia]
        dias.append({"dia": "hoje" if i == 0 else nomes[dia.weekday()], "data": dia.strftime("%d/%m"),
                     "tarefas": tarefas_dia, "eventos": eventos_dia})
    atrasadas = [t["titulo"] for t in pendentes if t["atrasada"]]
    carregados = [d for d in dias if d["tarefas"] or d["eventos"]]
    partes = []
    if atrasadas:
        partes.append(f"Atrasadas: {', '.join(atrasadas[:3])}.")
    for d in carregados[:4]:
        itens = d["eventos"] + d["tarefas"]
        partes.append(f"{d['dia'].capitalize()}: {', '.join(itens[:3])}.")
    sem_prazo = [t for t in pendentes if not t["prazo"]]
    if sem_prazo:
        partes.append(f"E {len(sem_prazo)} tarefa{'s' if len(sem_prazo) > 1 else ''} sem prazo.")
    return (" ".join(partes) or "Semana tranquila: nada com prazo e nenhum compromisso."), dias


def revisao_do_dia(app, hoje: date) -> str:
    """O que foi feito hoje e o que passa para amanhã (as de hoje não concluídas ganham prazo amanhã)."""
    feitas = app.tarefas.feitas_em(hoje)
    pendentes_hoje = [t for t in app.tarefas.pendentes() if t["prazo"] and date.fromisoformat(t["prazo"]) <= hoje]
    amanha = hoje + timedelta(days=1)
    for t in pendentes_hoje:
        app.tarefas.atualizar(t["id"], prazo=amanha)
    partes = []
    if feitas:
        partes.append(f"Hoje você concluiu {len(feitas)}: {', '.join(t['titulo'] for t in feitas[:4])}.")
    else:
        partes.append("Hoje nenhuma tarefa foi marcada como feita.")
    if pendentes_hoje:
        partes.append(f"Passei para amanhã: {', '.join(t['titulo'] for t in pendentes_hoje[:4])}.")
    eventos_amanha = app.agenda.do_dia(amanha)
    if eventos_amanha:
        partes.append("Amanhã tem " + "; ".join(app.agenda.descrever(e) for e in eventos_amanha[:3]) + ".")
    return " ".join(partes)
