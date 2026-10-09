"""Fase 2: protocolos com gatilhos, condições, criação por voz com aprovação e sensores."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sexta.habilidades.gatilhos import Vigia
from sexta.habilidades.rotinas import app_combina, montar


def test_formato_antigo_e_novo(app):
    r = montar("x", {"frases": ["oi"], "horario": "07:30", "dias": ["seg"], "passos": [{"falar": "a"}]},
               da_ia=False, permitidas=["falar"])
    assert r.frases == ["oi"] and r.horario == "07:30" and r.dias == [0]
    r = montar("y", {"gatilhos": [{"app_aberto": "Valorant"}], "condicoes": [{"entre": "18:00-23:59"},
               {"em_reuniao": False}, {"dias": "fim de semana"}], "passos": [{"fechar": "Chrome"}]},
               da_ia=True, permitidas=["fechar"])
    assert r.gatilhos == [{"tipo": "app_aberto", "valor": "Valorant"}]
    assert r.condicoes == [{"tipo": "entre", "valor": "18:00-23:59"}, {"tipo": "em_reuniao", "valor": False},
                           {"tipo": "dias", "valor": [5, 6]}]


def test_app_combina():
    assert app_combina("Valorant", "VALORANT-Win64-Shipping.exe")
    assert app_combina("VS Code", "Code.exe")
    assert app_combina("chrome", "chrome.exe")
    assert not app_combina("Valorant", "chrome.exe")


def test_criar_por_voz_pede_aprovacao_e_dispara(app, monkeypatch):
    fechados, planos = [], []
    monkeypatch.setattr(app.apps, "fechar", lambda nome: (fechados.append(nome), (True, "ok"))[1])
    monkeypatch.setattr("sexta.habilidades.configuracoes.definir_plano", lambda v: planos.append(v) or v)
    args = {"nome": "modo valorant", "gatilhos": [{"tipo": "app_aberto", "valor": "Valorant"}],
            "passos": [{"acao": "fechar", "valor": "Chrome"}, {"acao": "plano_energia", "valor": "desempenho maximo"}]}
    r = app.registro.executar("criar_protocolo", args, app.contexto())
    assert r["pendente"] and "quando abrir Valorant" in r["resumo"]
    assert app.rotinas.obter("modo valorant") is None  # ainda não salvou
    assert any(h["tipo"] == "protocolo" for h in app.hologramas.lista())

    r = app.registro.confirmar(app.contexto())
    assert r["ok"] and app.rotinas.obter("modo valorant") is not None
    assert not any(h["tipo"] == "protocolo" for h in app.hologramas.lista())

    disparados = app.rotinas.disparar("app_aberto", app="VALORANT-Win64-Shipping.exe")
    assert disparados == ["modo valorant"]
    import time
    for _ in range(50):
        if fechados and planos:
            break
        time.sleep(0.02)
    assert fechados == ["Chrome"] and planos == ["desempenho maximo"]  # sem pedir confirmação de novo
    assert app.rotinas.disparar("app_aberto", app="VALORANT.exe") == []  # intervalo mínimo


def test_condicao_bloqueia(app, monkeypatch):
    app.rotinas.criar("noite", [{"acao": "falar", "valor": "oi"}], gatilhos=[{"tipo": "desbloquear"}],
                      condicoes=[{"tipo": "entre", "valor": "22:00-06:00"}])
    r = app.rotinas.obter("noite")
    assert app.rotinas.condicoes_ok(r, datetime(2026, 10, 9, 23, 30))[0]
    assert app.rotinas.condicoes_ok(r, datetime(2026, 10, 9, 5, 0))[0]
    assert not app.rotinas.condicoes_ok(r, datetime(2026, 10, 9, 12, 0))[0]


def test_desativar_e_editor(app):
    app.rotinas.salvar_do_editor({"nome": "pendrive", "gatilhos": [{"tipo": "pendrive", "valor": ""}],
                                  "acoes": [{"tipo": "notificar", "valor": "Pendrive {rotulo} conectado"}]})
    assert app.rotinas.sensores_necessarios() == {"pendrive": [""]}
    app.rotinas.definir_ativo("pendrive", False)
    assert not app.rotinas.obter("pendrive").ativo and app.rotinas.sensores_necessarios() == {}
    app.rotinas.salvar_do_editor({"nome": "pendrive 2", "ativo": True, "gatilhos": [{"tipo": "pendrive"}],
                                  "acoes": [{"tipo": "falar", "valor": "oi"}]}, nome_antigo="pendrive")
    assert app.rotinas.obter("pendrive 2") and not any(r.nome == "pendrive" for r in app.rotinas.listar())


def test_arquivo_novo_espera_download_terminar(app, tmp_path, monkeypatch):
    pasta = tmp_path / "entrada"
    pasta.mkdir()
    app.rotinas.criar("pdfs", [{"acao": "notificar", "valor": "{nome_arquivo}"}],
                      gatilhos=[{"tipo": "arquivo_novo", "valor": str(pasta)}])
    disparos = []
    monkeypatch.setattr(app.rotinas, "executar", lambda r, ctx, v=None: disparos.append(v))
    vigia = Vigia(app)
    vigia._ver_pastas([pasta])
    (pasta / "nota.pdf").write_text("abc")
    vigia._ver_pastas([pasta])
    assert disparos == []  # ainda pode estar baixando
    vigia._ver_pastas([pasta])
    assert disparos and Path(disparos[0]["arquivo"]).name == "nota.pdf"


def test_notificar_publica_para_o_celular(app):
    eventos = []
    app.barramento.ouvir(lambda e: eventos.append(e))
    from sexta.habilidades.notificacoes import notificar

    notificar(app, "Chegou o boleto")
    assert any(e["tipo"] == "notificacao" and e["texto"] == "Chegou o boleto" for e in eventos)


def test_editor_recusa_bloco_vazio(app):
    import pytest

    with pytest.raises(ValueError, match="Notificar no celular"):
        app.rotinas.salvar_do_editor({"nome": "x", "gatilhos": [{"tipo": "desbloquear", "valor": True}],
                                      "acoes": [{"tipo": "notificar", "valor": ""}]})
    with pytest.raises(ValueError, match="Quando abrir o app"):
        app.rotinas.salvar_do_editor({"nome": "x", "gatilhos": [{"tipo": "app_aberto", "valor": ""}],
                                      "acoes": [{"tipo": "minimizar_tudo", "valor": True}]})
    salvo = app.rotinas.salvar_do_editor({"nome": "x", "gatilhos": [{"tipo": "pendrive", "valor": ""}],
                                          "acoes": [{"tipo": "minimizar_tudo", "valor": True}]})
    assert salvo.passos == [{"minimizar_tudo": True}]
