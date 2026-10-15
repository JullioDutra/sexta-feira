"""Tarefas aprendidas: ensinar, gravar, repetir, executar com agente, aprender com o agente e agendar."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS


def _adiado(monkeypatch) -> list:
    """Threads da extensão ficam guardadas para rodar depois que o pedido atual terminar."""
    pendentes = []

    class ThreadDepois:
        def __init__(self, target, args=(), **_k):
            self.target, self.args = target, args

        def start(self):
            pendentes.append(lambda: self.target(*self.args))

    monkeypatch.setattr("sexta.extensoes.tarefas_aprendidas.threading.Thread", ThreadDepois)
    return pendentes


def _sincrono(monkeypatch):
    """Threads da extensão rodam na hora (testes determinísticos)."""
    class ThreadNaHora:
        def __init__(self, target, args=(), **_k):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr("sexta.extensoes.tarefas_aprendidas.threading.Thread", ThreadNaHora)


def test_ensinar_e_executar_com_agente(app, monkeypatch):
    roteiro = {"nome": "relatório semanal", "frases": ["faz o relatório"], "objetivo": "relatório salvo em Documentos",
               "passos": ["abre o Excel", "salva o relatório"], "agente": "automacao", "conferir": "arquivo existe"}
    monkeypatch.setattr(app.agente, "completar", lambda s, t, rapido=True: json.dumps(roteiro))
    r = app.agente.processar("aprende a tarefa relatório semanal: abre o excel, preenche e salva em documentos",
                             canal="texto", falar=False)
    assert r["caminho"] == "atalho" and "Aprendi a tarefa relatório semanal, em 2 passos" in r["texto"]
    tarefa = app.tarefas_aprendidas.encontrar("relatório semanal")
    assert tarefa["origem"] == "ensinada" and tarefa["agente"] == "automacao"
    assert "explicacao" in tarefa and "preenche" in tarefa["explicacao"]

    iniciados = []

    def iniciar(tipo, objetivo, origem):
        iniciados.append((tipo, objetivo, origem))
        return NS(id="a9", tipo=NS(rotulo="Automação", nome="automacao"))
    monkeypatch.setattr(app.agentes, "iniciar", iniciar)
    r = app.agente.processar("faz o relatório", canal="voz")  # frase da própria tarefa
    assert "agente automação está fazendo a tarefa relatório semanal" in r["texto"]
    tipo, objetivo, _ = iniciados[0]
    assert tipo == "automacao" and "1. abre o Excel" in objetivo and "Como conferir no fim: arquivo existe" in objetivo
    assert "já está em andamento" in app.tarefas_aprendidas.executar("relatório semanal")

    # fim do agente: conta a execução e libera
    _sincrono(monkeypatch)
    monkeypatch.setattr(app.tarefas_aprendidas, "_roteiro_do_agente",
                        lambda agente: {"passos": ["abre o Excel", "usa o modelo", "salva"], "conferir": "ok"})
    agente = NS(id="a9", status="concluido", evidencia="", resumo="", objetivo=objetivo, passos=[],
                tipo=NS(nome="automacao"))
    app.tarefas_aprendidas.agente_terminou(agente)
    tarefa = app.tarefas_aprendidas.encontrar("relatório semanal")
    assert tarefa["execucoes"] == 1 and tarefa["sucessos"] == 1
    assert tarefa["passos"] == ["abre o Excel", "usa o modelo", "salva"]  # o roteiro melhorou
    assert any("Como fiz" in i["texto"] for i in app.memoria.itens("conhecimento"))


def test_gravar_e_repetir(app, monkeypatch):
    chamadas = []
    monkeypatch.setattr("sexta.habilidades.windows.definir_volume", lambda v: chamadas.append(v) or v)
    assert "Gravando a tarefa modo noite" in app.agente.processar("começa a gravar a tarefa modo noite", canal="texto",
                                                                  falar=False)["texto"]
    app.agente.processar("volume 20", canal="texto", falar=False)
    app.agente.processar("qual é a capital da frança", canal="texto", falar=False)  # não fez nada: não entra
    r = app.agente.processar("termina a gravação", canal="texto", falar=False)
    assert "Aprendi a tarefa modo noite, com 1 passo" in r["texto"]
    assert app.tarefas_aprendidas.encontrar("modo noite")["comandos"] == ["volume 20"]

    pendentes = _adiado(monkeypatch)
    chamadas.clear()
    r = app.agente.processar("faz a tarefa modo noite", canal="voz")
    assert r["texto"] == "Fazendo a tarefa modo noite."
    pendentes.pop()()
    tarefa = app.tarefas_aprendidas.encontrar("modo noite")
    assert chamadas == [20] and tarefa["sucessos"] == 1 and tarefa["ultima"]["ok"]
    assert "Tarefa modo noite concluída." in app.fala.falas


def test_repeticao_para_em_confirmacao(app, monkeypatch):
    pendentes = _adiado(monkeypatch)
    servico = app.tarefas_aprendidas
    servico._guardar({"nome": "fechar tudo", "origem": "gravada", "comandos": ["fecha o chrome"], "frases": []})
    monkeypatch.setattr(app.apps, "conhece_processo", lambda nome: True)
    servico.executar("fechar tudo", origem="voz")
    pendentes.pop()()
    tarefa = servico.encontrar("fechar tudo")
    assert tarefa["ultima"]["ok"] is False and "pediu confirmação" in tarefa["ultima"]["falha"]
    assert app.registro.pendente() is None  # repetir nunca deixa uma confirmação pendurada
    assert any("cuidado" in t for t in app.memoria.listar("licao"))


def test_gravacao_vazia_e_descartar(app):
    app.agente.processar("começa a gravar a tarefa nada", canal="texto", falar=False)
    assert "não salvei" in app.agente.processar("termina a gravação", canal="texto", falar=False)["texto"]
    app.agente.processar("começa a gravar a tarefa outra", canal="texto", falar=False)
    assert app.agente.processar("cancela a gravação", canal="texto", falar=False)["texto"] == "Gravação descartada."
    assert app.tarefas_aprendidas.tarefas == []


def test_salvar_ultimo_agente_e_agendar(app, monkeypatch):
    servico = app.tarefas_aprendidas
    assert "Nenhum agente" in servico.salvar_ultimo_agente("x")
    servico._ultimo_agente = NS(status="concluido", objetivo="pegar o preço do dólar", tipo=NS(nome="pesquisador"),
                                roteiro={"passos": ["pesquisa cotação do dólar", "lê o valor"], "conferir": ""})
    r = app.agente.processar("salva isso como tarefa cotação do dólar", canal="texto", falar=False)
    assert r["texto"].startswith("Salvei como a tarefa cotação do dólar")
    assert servico.encontrar("cotação do dólar")["agente"] == "pesquisador"
    r = app.agente.processar("faz a tarefa cotação do dólar toda segunda às 9h", canal="texto", falar=False)
    assert r["texto"] == "Combinado: faço a tarefa cotação do dólar seg às 09:00."
    rotina = app.rotinas.obter("tarefa cotação do dólar")
    assert rotina.passos == [{"tarefa": "cotação do dólar"}]
    assert "Esqueci" in app.agente.processar("esquece a tarefa cotação do dólar", canal="texto", falar=False)["texto"]


def test_persistencia_e_holograma(app, cfg):
    from sexta.extensoes.tarefas_aprendidas import TarefasAprendidas

    app.tarefas_aprendidas._guardar({"nome": "backup", "origem": "gravada", "comandos": ["abre o drive"], "frases": []})
    outro = TarefasAprendidas(app, cfg.dados / "tarefas_aprendidas.json")
    assert outro.encontrar("backup")["comandos"] == ["abre o drive"]
    r = app.agente.processar("quais tarefas você sabe fazer", canal="texto", falar=False)
    assert r["texto"] == "Sei fazer: backup." and app.hologramas.aberto("tarefas_aprendidas")
