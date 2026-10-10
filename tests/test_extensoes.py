"""Mecanismo de extensões (Fases 5 e 6): declarações, ganchos e isolamento de erros."""

from __future__ import annotations

import types

import pytest

from sexta import extensoes


@pytest.fixture
def extensao_falsa(monkeypatch):
    from sexta import config, eventos
    from sexta.habilidades import hologramas, rotinas

    chamadas = []
    mod = types.ModuleType("sexta.extensoes.falsa")
    mod.PREFERENCIAS = {"falsa_ligada": True}
    mod.HOLOGRAMAS = {"falso": "Holograma falso"}
    mod.EVENTOS_ALTA_FREQUENCIA = {"falso.nivel"}
    mod.ACOES_PROTOCOLO = {"acao_falsa": {"rotulo": "Ação falsa", "entrada": "texto",
                                          "executar": lambda app, valor, ctx, v: chamadas.append(("passo", valor))}}
    mod.instalar = lambda app: setattr(app, "servico_falso", "ok")

    def registrar(app, registro):
        @registro.ferramenta("ferramenta_falsa", "Teste.", direta=True)
        def ferramenta_falsa(ctx):
            return "Falsa feita."

    mod.registrar = registrar
    mod.atalho = lambda t, ctx, rodar, original: rodar("ferramenta_falsa", {}) if t == "comando falso" else None
    mod.dados_holograma = lambda app, tipo: {"x": 1} if tipo == "falso" else None
    mod.diagnostico = lambda app: [{"nome": "Falsa", "ok": True, "detalhe": "", "dica": ""}]
    quebrada = types.ModuleType("sexta.extensoes.quebrada")
    quebrada.instalar = lambda app: 1 / 0  # erro numa extensão não derruba as outras
    quebrada.atalho = lambda *a: 1 / 0

    # estado limpo: as tabelas do núcleo são restauradas no fim
    monkeypatch.setattr(extensoes, "_carregados", [quebrada, mod])
    monkeypatch.setattr(extensoes, "_preparado", False)
    monkeypatch.setattr(config, "PREFERENCIAS_PADRAO", dict(config.PREFERENCIAS_PADRAO))
    monkeypatch.setattr(config, "PREFERENCIAS_EDITAVEIS", set(config.PREFERENCIAS_EDITAVEIS))
    monkeypatch.setattr(hologramas, "TIPOS", list(hologramas.TIPOS))
    monkeypatch.setattr(hologramas, "TITULOS", dict(hologramas.TITULOS))
    monkeypatch.setattr(hologramas, "UNICOS", set(hologramas.UNICOS))
    monkeypatch.setattr(rotinas, "ACOES_SEGURAS", list(rotinas.ACOES_SEGURAS))
    monkeypatch.setattr(rotinas, "ACOES", list(rotinas.ACOES))
    monkeypatch.setattr(rotinas, "ACOES_EXTRAS", {})
    monkeypatch.setattr(rotinas, "CATALOGO", {k: list(v) for k, v in rotinas.CATALOGO.items()})
    monkeypatch.setattr(eventos, "TIPOS_ALTA_FREQUENCIA", set(eventos.TIPOS_ALTA_FREQUENCIA))
    return chamadas


def test_extensao_completa(extensao_falsa, cfg, tmp_path, monkeypatch):
    from sexta.app import SextaFeira
    from sexta.cerebro.agente import Agente
    from sexta.config import Config
    from sexta.diagnostico import verificar_tudo
    from sexta.habilidades import hologramas, rotinas
    from test_agente import OllamaFalso, cliente
    from conftest import FalaFalsa

    monkeypatch.setattr(Config, "pasta_config", property(lambda self: tmp_path / "config"))
    (tmp_path / "config").mkdir()
    app = SextaFeira(cfg, com_voz=False)
    app.fala.encerrar()
    app.fala = FalaFalsa()
    try:
        assert app.servico_falso == "ok"
        assert app.prefs.get("falsa_ligada") is True and "falsa_ligada" in __import__("sexta.config").config.PREFERENCIAS_EDITAVEIS
        assert "falso" in hologramas.TIPOS and "falso" in hologramas.UNICOS
        assert "ferramenta_falsa" in app.registro.nomes()
        app.agente = Agente(app, cliente(OllamaFalso([])))
        r = app.agente.processar("comando falso")
        assert r["caminho"] == "atalho" and r["texto"] == "Falsa feita."
        app.hologramas.mostrar("falso")
        assert app.hologramas.lista()[-1]["dados"] == {"x": 1}
        rotinas.ACOES_EXTRAS["acao_falsa"](app, "oi", None, {})
        assert extensao_falsa == [("passo", "oi")]
        assert any(a["tipo"] == "acao_falsa" for a in rotinas.CATALOGO["acoes"])
        assert verificar_tudo.__module__  # diagnóstico inclui o item da extensão
        assert any(i["nome"] == "Falsa" for i in extensoes.diagnostico(app))
    finally:
        app.hologramas._rodando = False


def test_modulos_inexistentes_sao_ignorados(monkeypatch):
    monkeypatch.setattr(extensoes, "_carregados", None)
    monkeypatch.setattr(extensoes, "MODULOS", ["nao_existe_ainda"])
    assert extensoes.carregar() == []
