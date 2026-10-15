"""Memória (SQLite + FTS5), aprendizado, verificação das ações, níveis de resposta e cérebro de reserva."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace as NS

import pytest

from sexta.aprendizado import e_correcao
from sexta.cerebro import nivel
from sexta.cerebro.agente import Agente
from sexta.cerebro.claude import ClienteClaude
from sexta.cerebro.ferramentas import CONFIRMAR, ROSTO, Contexto, Registro
from sexta.cerebro.memoria import Memoria
from sexta.cerebro.ollama import ErroOllama
from sexta.cerebro.reserva import CerebroComReserva
from tests.test_claude import SdkFalso, mensagem


@pytest.fixture
def memoria(tmp_path):
    m = Memoria(tmp_path / "memoria.db")
    yield m
    m.fechar()


# ---------------------------------------------------------------- memória
def test_aprender_buscar_e_reforcar(memoria):
    memoria.aprender("fato", "O time dele é o Cruzeiro")
    memoria.aprender("licao", "Quando ele pedir música para focar, tocar lo-fi no Spotify", etiquetas=["tocar_youtube"])
    memoria.aprender("conhecimento", "O Notion passa a área de transferência do renderizador ao processo principal por IPC",
                     etiquetas=["notion", "electron"], origem="engenharia_reversa")
    achados = memoria.buscar("toca uma música pra eu focar")
    assert achados and achados[0]["tipo"] == "licao"
    assert memoria.buscar("como o notion copia texto?")[0]["etiquetas"] == ["electron", "notion"]
    # aprender de novo não duplica: reforça
    id1 = memoria.aprender("fato", "o time dele é o cruzeiro.")
    assert len(memoria.listar()) == 1 and id1 == memoria.itens("fato")[0]["id"]
    assert memoria.buscar("", 5) == [] and memoria.buscar("de o a", 5) == []


def test_contexto_relevante_vai_na_mensagem_e_foto_fica_estavel(memoria):
    memoria.aprender("fato", "Ele trabalha como desenvolvedor Python", origem="usuario")
    memoria.renovar_foto()
    sistema = memoria.para_prompt()
    memoria.lembrar("A namorada dele se chama Ana")
    assert memoria.para_prompt() == sistema  # o prompt de sistema (cache) não muda a cada fato
    contexto = memoria.contexto_para("que horas são?")
    assert "Ana" in contexto and "desenvolvedor" not in contexto  # fatos novos vão em todo pedido
    memoria.aprender("licao", "Quando ele falar 'meu editor', abrir o VS Code")
    assert "(lição) Quando ele falar 'meu editor'" in memoria.contexto_para("abre meu editor")
    assert memoria.esquecer("namorada") == ["A namorada dele se chama Ana"]


def test_migra_memoria_antiga(tmp_path):
    antigo = tmp_path / "memoria.json"
    antigo.write_text(json.dumps({"fatos": [{"texto": "Gosta de café", "criado": 1}]}), encoding="utf-8")
    m = Memoria(tmp_path / "memoria.db", legado=antigo)
    assert m.listar() == ["Gosta de café"] and "café" in m.para_prompt()
    m.fechar()
    m = Memoria(tmp_path / "memoria.db", legado=antigo)  # uma vez só
    assert m.listar() == ["Gosta de café"]
    m.fechar()


def test_episodios_e_consolidacao(memoria):
    memoria.registrar_episodio("abre o spotify", caminho="atalho", ferramentas=[{"ferramenta": "abrir", "ok": True,
                                                                                 "resumo": "Abrindo Spotify."}])
    ep = memoria.registrar_episodio("abre meu editor", ferramentas=[{"ferramenta": "abrir", "ok": False,
                                                                    "resumo": "Não encontrei"}])
    assert memoria.ultimo_episodio()["ok"] is False
    memoria.marcar_episodio(ep, False, "usuário corrigiu")
    pedidos = []

    def completar(sistema, texto):
        pedidos.append(texto)
        return 'Aqui: {"fatos": ["Ele usa o VS Code"], "licoes": ["Quando ele disser meu editor, abrir o VS Code"]}'

    novos = memoria.consolidar(completar)
    assert novos == {"fato": 1, "licao": 1}
    assert "DEU ERRADO: usuário corrigiu" in pedidos[0]
    assert "Ele usa o VS Code" in memoria.para_prompt()  # a consolidação renova a foto
    assert memoria.consolidar(completar) == {"fato": 0, "licao": 0}  # sem episódios novos, nada a pedir
    assert len(pedidos) == 1
    e = memoria.estatisticas()
    assert e["episodios"] == 2 and e["acertos"] == 1 and e["consolidado_em"]


def test_consolidacao_esquece_o_que_nao_e_usado(memoria):
    memoria.aprender("licao", "Quando chover, avisar", origem="consolidacao", confianca=0.3)
    memoria.lembrar("Gosta de café")
    memoria._con.execute("UPDATE itens SET usado=0")
    memoria.consolidar(None, desde=time.time())
    assert memoria.listar("licao") == [] and memoria.listar() == ["Gosta de café"]


# ---------------------------------------------------------------- níveis de resposta
@pytest.mark.parametrize("texto,esperado", [
    ("abre o spotify", nivel.SIMPLES),
    ("quanto é 15% de 80?", nivel.SIMPLES),
    ("Sexta-Feira, me explica como funciona o protocolo TLS", nivel.COMPLEXO),
    ("analisa esse contrato e me diz os riscos", nivel.COMPLEXO),
    ("corrige o texto que eu copiei", nivel.COMPLEXO),
    ("tem um bug no meu código de login", nivel.COMPLEXO),
    ("toca uma música", nivel.SIMPLES),
])
def test_classificar(texto, esperado):
    assert nivel.classificar(texto) == esperado


def test_complexo_pensa_e_reconhece_na_hora(app):
    sdk = SdkFalso([(["Ok."], mensagem([NS(type="text", text="Ok.")])) for _ in range(2)])
    app.prefs.atualizar({"atalhos_rapidos": False})
    agente = Agente(app, ClienteClaude("claude-opus-5-5", cliente=sdk))
    agente.modelo_rapido = "claude-haiku-5-5"
    reconhecidos = []
    app.fala.reconhecer = lambda: reconhecidos.append(1)
    agente.processar("quanto é 2 mais 2", canal="voz")
    assert "thinking" not in sdk.pedidos[0] and sdk.pedidos[0]["model"] == "claude-haiku-5-5" and not reconhecidos
    agente.processar("me explica por que o céu é azul", canal="voz")
    assert sdk.pedidos[1]["thinking"] == {"type": "adaptive"} and sdk.pedidos[1]["model"] == "claude-opus-5-5"
    assert sdk.pedidos[1]["output_config"] == {"effort": "medium"} and reconhecidos == [1]


def test_memoria_relevante_e_episodio_no_pedido(app):
    sdk = SdkFalso([(["Cruzeiro, claro."], mensagem([NS(type="text", text="Cruzeiro, claro.")]))])
    app.prefs.atualizar({"atalhos_rapidos": False})
    app.agente = Agente(app, ClienteClaude("claude-opus-5-5", cliente=sdk))
    app.memoria.aprender("fato", "O time dele é o Cruzeiro")
    app.agente.processar("qual é o meu time?", canal="texto", falar=False)
    ultima = sdk.pedidos[0]["messages"][-1]["content"]
    assert "<memoria_relevante>" in ultima and "Cruzeiro" in ultima
    ep = app.memoria.ultimo_episodio()
    assert ep["pedido"] == "qual é o meu time?" and ep["caminho"] == "ia" and ep["ok"]


# ---------------------------------------------------------------- aprendizado
@pytest.mark.parametrize("texto", ["não era isso", "Sexta-Feira, você errou", "tá errado", "não abriu",
                                   "não, eu pedi o outro", "isso não funcionou"])
def test_correcoes(texto):
    assert e_correcao(texto)


@pytest.mark.parametrize("texto", ["não", "abre o spotify", "era uma vez", "não esquece de me lembrar"])
def test_nao_correcoes(texto):
    assert not e_correcao(texto)


def test_correcao_vira_licao(app, monkeypatch):
    app.memoria.registrar_episodio("abre meu editor", ferramentas=[{"ferramenta": "abrir", "ok": True, "resumo": "Abrindo Bloco de Notas."}],
                                   resposta="Abrindo Bloco de Notas.")
    monkeypatch.setattr(app.agente, "completar", lambda s, t, rapido=True: "Quando ele disser 'meu editor', abrir o VS Code.")
    threads = []
    monkeypatch.setattr("sexta.aprendizado.threading.Thread",
                        lambda target, **k: NS(start=lambda: threads.append(target)))
    app.aprendizado.corrigir("não era isso, é o VS Code")
    threads[0]()
    assert app.memoria.ultimo_episodio()["ok"] is False
    assert app.memoria.listar("licao") == ["Quando ele disser 'meu editor', abrir o VS Code"]


def test_regra_do_usuario(app):
    r = app.agente.processar("Sexta-Feira, aprende que quando eu falar modo cinema é para apagar as luzes", canal="texto",
                             falar=False)
    assert r["caminho"] == "aprendizado"
    assert app.memoria.listar("licao") == ["Quando eu falar modo cinema é para apagar as luzes"]


def test_atalhos_de_aprendizado(app):
    app.memoria.aprender("licao", "Quando ele pedir café, lembrar do açúcar")
    r = app.agente.processar("o que você aprendeu hoje?", canal="texto", falar=False)
    assert r["caminho"] == "atalho" and "Lições: Quando ele pedir café" in r["texto"]
    r = app.agente.processar("deu certo?", canal="texto", falar=False)
    assert r["caminho"] == "atalho"
    r = app.agente.processar("o que você sabe sobre mim?", canal="texto", falar=False)
    assert "lições" in r["texto"] and app.hologramas.aberto("memoria")


# ---------------------------------------------------------------- verificação e autonomia
def _registro_com(acao, verificar=None, nivel=1):
    registro = Registro()

    @registro.ferramenta("acao", "teste", nivel=nivel, verificar=verificar)
    def _acao(ctx):
        return acao()
    return registro


def test_verificacao_em_segundo_plano(app, monkeypatch):
    threads = []
    monkeypatch.setattr("sexta.aprendizado.threading.Thread",
                        lambda target, **k: NS(start=lambda: threads.append(target)))
    app.registro.obter("ajustar_volume").verificar = lambda a, r: (lambda: (False, "O volume ficou em 10%, não em 40%."))
    monkeypatch.setattr("sexta.habilidades.windows.definir_volume", lambda v: v)
    r = app.agente.processar("volume 40", canal="voz")
    assert r["texto"] == "Volume em 40%."
    assert len(threads) == 1
    threads[0]()
    assert app.memoria.ultimo_episodio()["ok"] is False
    assert app.fala.falas[-1] == "O volume ficou em 10%, não em 40%."
    assert app.atividades.listar(1)[0]["situacao"] == "nao_confirmada"


def test_autonomia_total_dispensa_confirmar_mas_nao_rosto():
    feitos = []
    registro = _registro_com(lambda: feitos.append(1) or "ok", nivel=CONFIRMAR)
    ctx = Contexto(app=None)
    assert registro.executar("acao", {}, ctx).get("pendente")
    registro.autonomia = lambda: "total"
    assert registro.executar("acao", {}, ctx)["ok"] and feitos == [1]
    registro = _registro_com(lambda: "ok", nivel=ROSTO)
    registro.autonomia = lambda: "total"
    assert registro.executar("acao", {}, ctx).get("pendente")


def test_terminal_na_autonomia_total(app):
    nivel_terminal = app.registro.obter("terminal").nivel_para
    assert nivel_terminal({"comando": "pip list"}) == ROSTO
    app.prefs.atualizar({"autonomia": "total"})
    assert nivel_terminal({"comando": "pip list"}) == CONFIRMAR
    assert nivel_terminal({"comando": "del /s /q C:\\pasta"}) == ROSTO
    assert nivel_terminal({"comando": "Remove-Item x -Recurse"}) == ROSTO


# ---------------------------------------------------------------- cérebro livre e reserva
def test_cerebro_livre_manda_so_o_basico():
    sdk = SdkFalso([(["Oi."], mensagem([NS(type="text", text="Oi.")]))])
    livre = ClienteClaude("auto", cliente=sdk, url="http://localhost:3001", nome="FreeLLMAPI")
    list(livre.conversar([{"role": "system", "content": "s"}, {"role": "user", "content": "oi"}], pensar=True))
    pedido = sdk.pedidos[0]
    assert pedido["model"] == "auto"
    assert not {"output_config", "thinking", "cache_control", "fallbacks", "betas"} & set(pedido)


class _Quebrado:
    modelo = "claude-opus-5-5"

    def conversar(self, *a, **k):
        raise ErroOllama("Limite de uso da API do Claude atingido.")
        yield  # noqa

    def completar(self, *a, **k):
        raise ErroOllama("sem crédito")


def test_reserva_assume_quando_o_principal_falha():
    sdk = SdkFalso([(["Oi."], mensagem([NS(type="text", text="Oi.")])) for _ in range(2)])
    reserva = ClienteClaude("auto", cliente=sdk, url="http://localhost:3001", nome="FreeLLMAPI")
    cerebro = CerebroComReserva(_Quebrado(), reserva, "rapido")
    eventos = list(cerebro.conversar([{"role": "user", "content": "oi"}], modelo="claude-haiku-5-5"))
    assert [e["texto"] for e in eventos if e["tipo"] == "texto"] == ["Oi."]
    assert sdk.pedidos[0]["model"] == "rapido" and cerebro.usando_reserva
    assert cerebro.completar("s", "t").startswith("Vejo")  # já no reserva, sem tentar o principal
    assert cerebro.modelo == "claude-opus-5-5"


# ---------------------------------------------------------------- notícias de TI e IA
def test_noticias_de_ti_e_ia_do_dia(app, monkeypatch):
    from datetime import datetime, timedelta, timezone

    agora = datetime.now(timezone.utc)
    feeds = {
        "ia": [{"titulo": "Novo modelo aberto supera rivais", "link": "a", "fonte": "The Decoder", "publicado": agora},
               {"titulo": "Notícia velha de IA", "link": "b", "fonte": "X", "publicado": agora - timedelta(days=3)}],
        "tecnologia": [{"titulo": "Windows ganha atualização", "link": "c", "fonte": "Tecnoblog", "publicado": agora}],
    }
    monkeypatch.setattr(app.jornal, "coletar", lambda categoria: feeds.get(categoria, []))
    monkeypatch.setattr(app.jornal, "buscar_tema", lambda tema: [])
    r = app.agente.processar("notícias de TI e IA de hoje", canal="texto", falar=False)
    assert r["caminho"] == "atalho"
    assert r["texto"] == "Em IA: Novo modelo aberto supera rivais. Em TI: Windows ganha atualização."
    jornal = next(h for h in app.hologramas.lista() if h["tipo"] == "jornal")
    assert jornal["dados"]["aba"] == "ia"
    assert app.agente.processar("o que saiu de inteligência artificial hoje", canal="texto", falar=False)["caminho"] == "atalho"
    assert "ia" in app.jornal.fontes
def test_holograma_memoria(app):
    app.memoria.lembrar("Gosta de café")
    r = app.registro.executar("holograma", {"acao": "mostrar", "tipo": "memoria"}, app.contexto("texto"))
    assert r["ok"], r
    h = next(h for h in app.hologramas.lista() if h["tipo"] == "memoria")
    assert h["dados"]["fatos"][0]["texto"] == "Gosta de café"
