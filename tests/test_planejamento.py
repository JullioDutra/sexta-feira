"""Fase 4: tarefas, planejamento do dia, revisão, plano da semana, modo foco e agenda iCal."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import httpx
import pytest

from sexta.habilidades.agenda import Agenda
from sexta.habilidades.planejador import Bloco, planejar_dia
from sexta.habilidades.tarefas import interpretar_prazo, interpretar_tarefa

SEXTA = date(2026, 10, 9)


def test_interpretar_prazo():
    assert interpretar_prazo("até sexta", SEXTA) == date(2026, 10, 16)
    assert interpretar_prazo("amanhã", SEXTA) == date(2026, 10, 10)
    assert interpretar_prazo("fim do mês", SEXTA) == date(2026, 10, 31)
    assert interpretar_prazo("semana que vem", SEXTA) == date(2026, 10, 12)
    assert interpretar_prazo("dia 20", SEXTA) == date(2026, 10, 20)


def test_interpretar_tarefa():
    c = interpretar_tarefa("terminar o sistema do campeonato até sexta, urgente, leva 3 horas", SEXTA)
    assert c == {"titulo": "terminar o sistema do campeonato", "prazo": date(2026, 10, 16), "prioridade": "alta",
                 "estimativa": 180}
    assert interpretar_tarefa("tenho que pagar o boleto da Câmara amanhã", SEXTA)["titulo"] == "pagar o boleto da Câmara"


def test_criar_por_voz_sem_ia_e_concluir(app):
    from sexta.cerebro.agente import Agente
    from test_agente import OllamaFalso, cliente

    app.agente = Agente(app, cliente(OllamaFalso([])))
    r = app.agente.processar("Sexta-Feira, anota: terminar o sistema do campeonato até sexta")
    assert r["caminho"] == "atalho" and r["texto"].startswith("Anotado: Terminar o sistema do campeonato para ")
    tarefa = app.tarefas.pendentes()[0]
    assert tarefa["prazo"] == interpretar_prazo("sexta").isoformat()
    r = app.agente.processar("terminei o sistema do campeonato")
    assert r["texto"].startswith("Feito: Terminar o sistema do campeonato") and app.tarefas.pendentes() == []


def test_quadro_e_mover(app):
    t = app.tarefas.criar("Revisar PR", prioridade="alta")
    app.registro.executar("tarefas", {"acao": "mover", "alvo": "revisar", "status": "fazendo"}, app.contexto())
    quadro = app.tarefas.quadro()
    assert [x["id"] for x in quadro["colunas"]["fazendo"]] == [t["id"]]
    r = app.registro.executar("tarefas", {"acao": "apagar", "alvo": "revisar"}, app.contexto())
    assert r["pendente"]  # apagar pede confirmação


def _tarefa(id_, titulo, minutos, prioridade="media", prazo=None):
    return {"id": id_, "titulo": titulo, "estimativa": minutos, "prioridade": prioridade, "status": "a_fazer",
            "prazo": prazo, "atrasada": False, "prazo_texto": ""}


def test_planejar_dia_encaixa_entre_compromissos():
    agora = datetime(2026, 10, 9, 8, 30)
    reuniao = Bloco(datetime(2026, 10, 9, 10, 0), datetime(2026, 10, 9, 11, 0), "Daily", "evento")
    tarefas = [_tarefa(1, "Relatório", 150, "alta"), _tarefa(2, "E-mails", 30, "baixa"), _tarefa(3, "Deploy", 60, "media", "2026-10-09")]
    blocos, sobras = planejar_dia(agora, tarefas, [reuniao], "09:00", "18:00", "12:00-13:00")
    resumo = [(b.inicio.strftime("%H:%M"), b.fim.strftime("%H:%M"), b.titulo) for b in blocos]
    assert resumo[0] == ("09:00", "10:00", "Deploy")  # prazo hoje vem primeiro
    assert ("10:00", "11:00", "Daily") in resumo and ("12:00", "13:00", "Almoço") in resumo
    assert ("11:00", "12:00", "Relatório (parte)") in resumo
    assert not any(b.inicio < reuniao.fim and b.fim > reuniao.inicio and b.tipo == "tarefa" for b in blocos)
    assert sobras == []
    # pausa depois de 90 min seguidos de trabalho
    blocos, _ = planejar_dia(datetime(2026, 10, 9, 13, 0), [_tarefa(1, "Longa", 240)], [], "13:00", "18:00", None)
    assert [b.tipo for b in blocos][:3] == ["tarefa", "pausa", "tarefa"]


def test_revisao_passa_pendencias_para_amanha(app):
    hoje = date.today()
    feita = app.tarefas.criar("Feita hoje", prazo=hoje)
    app.tarefas.atualizar(feita["id"], status="feito")
    app.tarefas.criar("Ficou para trás", prazo=hoje)
    r = app.registro.executar("planejar", {"acao": "revisao_dia"}, app.contexto())
    assert "concluiu 1: Feita hoje" in r["resumo"] and "Passei para amanhã: Ficou para trás" in r["resumo"]
    assert app.tarefas.pendentes()[0]["prazo"] == (hoje + timedelta(days=1)).isoformat()


def test_foco_pausa_encerra_e_segura_avisos(app, monkeypatch):
    chamadas = []
    monkeypatch.setattr(app.registro, "executar", lambda n, a, ctx, **_: chamadas.append((n, a)) or {"ok": True, "resumo": ""})
    monkeypatch.setattr(app.apps, "conhece_processo", lambda nome: nome == "Discord")
    e = app.foco.iniciar(minutos=25)
    try:
        assert e["fase"] == "foco" and app.foco.ativo()
        assert ("configuracao", {"item": "nao_perturbe", "valor": "ligar"}) in chamadas
        assert ("fechar_programa", {"nome": "Discord"}) in chamadas
        segurado = []
        assert app.foco.segurar(lambda: segurado.append(1))
        assert app.foco.pausar() and app.foco.estado()["pausado"]
        assert app.foco.retomar()
    finally:
        app.foco.encerrar()
    assert segurado == [1] and not app.foco.ativo()
    assert ("configuracao", {"item": "nao_perturbe", "valor": "desligar"}) in chamadas


def test_foco_troca_de_fase(app, monkeypatch):
    monkeypatch.setattr(app.registro, "executar", lambda *a, **k: {"ok": True, "resumo": ""})
    app.foco.iniciar(minutos=1, pausa=1, ciclos=2)
    try:
        app.foco._proxima_fase()
        assert app.foco.estado()["fase"] == "pausa" and "Hora da pausa" in app.fala.tudo()
        app.foco._proxima_fase()
        assert app.foco.estado()["fase"] == "foco" and app.foco.estado()["ciclo"] == 2
        app.foco._proxima_fase()
        assert app.foco.estado() is None and "Foco concluído" in app.fala.tudo()
    finally:
        app.foco.encerrar(silencioso=True)


ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:daily@x
DTSTART:{d}T100000
DTEND:{d}T103000
RRULE:FREQ=DAILY;COUNT=5
SUMMARY:Daily do time
END:VEVENT
BEGIN:VEVENT
UID:feriado@x
DTSTART;VALUE=DATE:{d}
SUMMARY:Aniversário da Ana
END:VEVENT
END:VCALENDAR
"""


def test_agenda_ical_e_aviso(app):
    hoje = date.today()
    corpo = ICS.format(d=hoje.strftime("%Y%m%d")).encode()
    agenda = Agenda(app, ["webcal://cal/secreto.ics"], http=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=corpo))))
    eventos = agenda.do_dia(hoje)
    assert [(e["titulo"], e["dia_inteiro"]) for e in eventos] == [("Aniversário da Ana", True), ("Daily do time", False)]
    amanha = agenda.do_dia(hoje + timedelta(days=1))
    assert [e["titulo"] for e in amanha] == ["Daily do time"]  # a repetição diária funciona
    agora = datetime.combine(hoje, datetime.min.time()).replace(hour=9, minute=52)
    avisados = agenda.verificar_avisos(agora)
    assert [e["titulo"] for e in avisados] == ["Daily do time"]
    assert "Daily do time começa em 8 minutos" in app.fala.tudo()
    assert agenda.verificar_avisos(agora) == []  # não repete


@pytest.mark.parametrize("frase,ferramenta,args", [
    ("planeja meu dia", "planejar", {"acao": "dia"}),
    ("faz a revisão do dia", "planejar", {"acao": "revisao_dia"}),
    ("planeja minha semana", "planejar", {"acao": "semana"}),
    ("plano da semana", "rotina", {"acao": "executar", "nome": "plano da semana"}),  # protocolo de mesmo nome
    ("quais são minhas tarefas", "tarefas", {"acao": "mostrar_quadro"}),
    ("pomodoro de 50 minutos", "foco", {"acao": "iniciar", "minutos": 50}),
    ("encerra o foco", "foco", {"acao": "encerrar"}),
])
def test_atalhos_planejamento(app, monkeypatch, frase, ferramenta, args):
    from sexta.cerebro.agente import Agente
    from test_agente import OllamaFalso, cliente

    chamadas = []
    monkeypatch.setattr(app.registro, "executar", lambda n, a, ctx, **_: chamadas.append((n, a)) or {"ok": True, "resumo": "ok"})
    app.agente = Agente(app, cliente(OllamaFalso([])))
    assert app.agente.processar(frase)["caminho"] == "atalho"
    assert chamadas[0] == (ferramenta, args)
