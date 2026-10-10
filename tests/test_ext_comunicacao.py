"""Comunicação: personalidade ajustável, modo tradutor por voz e tradução da tela e do texto copiado."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from sexta.cerebro import personalidade
from sexta.cerebro.agente import Agente
from sexta.cerebro.ollama import ErroOllama
from sexta.extensoes import comunicacao
from sexta.util.texto import normalizar
from sexta.voz import assistente_voz as modulo_voz
from sexta.voz import fala as modulo_fala
from sexta.voz.audio import tom
from sexta.voz.transcricao import DICA_PADRAO, Transcritor

from test_agente import OllamaFalso, cliente
from test_voz import DetectorFalso, MicrofoneFalso, ReprodutorFalso, bloco

SILENCIO = np.zeros(16000, dtype=np.float32)
AVA = "en-US-AvaMultilingualNeural"


def sem_ia(app):
    """Agente com um Ollama que falha se for chamado: prova que o pedido não passou pela IA."""
    app.agente = Agente(app, cliente(OllamaFalso([])))
    return app.agente


def registrar_execucoes(app, monkeypatch) -> list[tuple[str, dict]]:
    chamadas: list[tuple[str, dict]] = []
    monkeypatch.setattr(app.registro, "executar",
                        lambda nome, args, ctx, **_: chamadas.append((nome, args)) or {"ok": True, "resumo": "ok"})
    return chamadas


def esperar(condicao, segundos: float = 4.0) -> bool:
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.01)
    return condicao()


# ---------------------------------------------------------------- personalidade

def test_declaracoes_da_extensao(app):
    from sexta import config
    from sexta.habilidades import hologramas, rotinas

    assert app.prefs.get("personalidade") == "amigavel" and "personalidade" in config.PREFERENCIAS_EDITAVEIS
    assert "traducao" in hologramas.TIPOS and "traducao" in hologramas.UNICOS
    assert {"personalidade", "tradutor"} <= set(rotinas.ACOES_SEGURAS)
    assert {"personalidade", "traducao"} <= set(app.registro.nomes())


def test_instalar_nao_liga_nada(app):
    antes = threading.active_count()
    comunicacao.instalar(app)
    assert threading.active_count() == antes and app.tradutor.alvo is None


def test_personalidade_padrao_mantem_o_tom_de_sempre(app):
    sistema = app.agente._sistema(app.contexto())
    assert "confiante, eficiente, leal" in sistema and "humor leve e seco" in sistema
    assert 'Trate o usuário por "chefe"' in sistema


def test_prompt_so_muda_quando_a_personalidade_muda(app):
    sistema = lambda: app.agente._sistema(app.contexto())  # noqa: E731
    amigavel = sistema()
    assert sistema() == amigavel  # idêntico entre pedidos: o cache do prompt continua valendo
    app.prefs.atualizar({"personalidade": "formal"})
    formal = sistema()
    assert formal != amigavel and sistema() == formal
    assert 'Trate o usuário por "senhor"' in formal and "sem gírias, piadas nem ironia" in formal
    app.prefs.atualizar({"tratamento": "senhora"})
    assert 'Trate o usuário por "senhora"' in sistema()
    app.prefs.atualizar({"personalidade": "sarcastica", "tratamento": "chefe"})
    sarcastica = sistema()
    assert "sarcástica" in sarcastica and "ditos de forma direta e séria" in sarcastica
    assert 'Trate o usuário por "chefe"' in sarcastica
    app.prefs.atualizar({"personalidade": "inventada"})  # valor estranho vindo do HUD: volta ao padrão
    assert sistema() == amigavel


def test_prompt_igual_em_pedidos_seguidos_com_a_mesma_personalidade(app):
    import httpx

    from test_agente import ndjson

    resposta = lambda: httpx.Response(200, content=ndjson({"message": {"content": "Certo."}, "done": True}))  # noqa: E731
    falso = OllamaFalso([resposta() for _ in range(3)])
    app.prefs.atualizar({"atalhos_rapidos": False, "personalidade": "formal"})
    app.agente = Agente(app, cliente(falso))
    app.agente.processar("oi", canal="voz")
    app.agente.processar("tudo bem?", canal="voz")
    app.prefs.atualizar({"personalidade": "sarcastica"})
    app.agente.processar("e agora?", canal="voz")
    primeiro, segundo, terceiro = (r["messages"][0]["content"] for r in falso.requisicoes)
    assert primeiro == segundo and terceiro != segundo


@pytest.mark.parametrize("estilo,esperadas", [
    ("amigavel", {"Às ordens, chefe."}),
    ("formal", {"Sempre às ordens, senhor."}),
    ("sarcastica", {"Às ordens, chefe. Anotei mais um elogio.", "Disponha, chefe. Eu sei, eu sei: sou ótima."}),
])
def test_obrigado_conforme_a_personalidade(app, estilo, esperadas):
    app.prefs.atualizar({"personalidade": estilo})
    resposta = sem_ia(app).processar("obrigado")
    assert resposta["caminho"] == "atalho" and resposta["texto"] in esperadas


def test_cancelamento_continua_claro_em_toda_personalidade(app, monkeypatch):
    fechados = []
    monkeypatch.setattr(app.apps, "fechar", lambda nome: (fechados.append(nome), (True, "ok"))[1])
    agente = sem_ia(app)
    for estilo in personalidade.PERSONALIDADES:
        app.prefs.atualizar({"personalidade": estilo})
        agente.processar("fecha o discord")
        texto = agente.processar("não")["texto"]
        assert "cancelado" in texto.lower(), texto
    assert agente.processar("fecha o discord") and fechados == []
    app.prefs.atualizar({"personalidade": "formal"})
    assert agente.processar("não")["texto"] == "Perfeitamente, senhor. Cancelado."


def test_pois_nao_conforme_a_personalidade(app):
    assert personalidade.resposta(app.prefs, "chamada") == "Pois não?"
    app.prefs.atualizar({"personalidade": "formal", "tratamento": "doutor"})
    assert personalidade.resposta(app.prefs, "chamada") == "Pois não, doutor?"


@pytest.mark.parametrize("frase,estilo", [
    ("modo formal", "formal"),
    ("Modo amigável", "amigavel"),
    ("modo sarcástico", "sarcastica"),
    ("Sexta-Feira, ativa o modo formal, por favor", "formal"),
    ("fica mais formal", "formal"),
    ("pode ser sarcástica", "sarcastica"),
    ("seja mais amigável", "amigavel"),
    ("muda a sua personalidade para sarcástica", "sarcastica"),
])
def test_mudar_personalidade_por_voz(app, frase, estilo):
    app.prefs.atualizar({"personalidade": "formal" if estilo != "formal" else "amigavel"})
    eventos = []
    app.barramento.ouvir(lambda e: e["tipo"] == "preferencias" and eventos.append(e["preferencias"]))
    resposta = sem_ia(app).processar(frase)
    assert resposta["caminho"] == "atalho"
    assert app.prefs.get("personalidade") == estilo
    assert resposta["texto"] == personalidade.resposta(app.prefs, "ativada")
    assert eventos[-1]["personalidade"] == estilo  # o HUD (Ajustes) atualiza na hora


def test_qual_e_a_personalidade(app):
    agente = sem_ia(app)
    assert agente.processar("qual é a sua personalidade?")["texto"].startswith("Estou no modo amigável")
    app.prefs.atualizar({"personalidade": "sarcastica"})
    assert agente.processar("qual sua personalidade")["texto"].startswith("Modo sarcástico")
    assert agente.processar("modo sarcástico")["texto"].startswith("Modo sarcástico")  # já estava: só informa


def test_protocolo_ou_layout_com_o_mesmo_nome_tem_preferencia(app, monkeypatch):
    app.rotinas.criar("formal", [{"acao": "falar", "valor": "Terno e gravata."}])
    monkeypatch.setattr(app.layouts, "obter", lambda nome: ("sarcastico", []) if "sarcastico" in normalizar(nome) else None)
    chamadas = registrar_execucoes(app, monkeypatch)
    agente = sem_ia(app)
    agente.processar("modo formal")
    agente.processar("modo sarcástico")
    assert chamadas[0] == ("rotina", {"acao": "executar", "nome": "formal"})
    assert chamadas[1][0] == "janelas" and chamadas[1][1]["acao"] == "aplicar_layout"
    assert app.prefs.get("personalidade") == "amigavel"


# ---------------------------------------------------------------- atalhos sem colisão com o núcleo

FRASES_DO_NUCLEO = [
    "abre o spotify", "fecha o chrome", "toca legião urbana", "modo jogo", "modo foco", "modo trabalho", "modo escuro",
    "ativa o modo escuro", "modo economia", "volume 30", "analisa a tela", "o que é isso?", "planeja meu dia",
    "abre o jornal", "obrigado", "cancela", "para", "pausa", "que horas são", "fecha o tradutor", "abre o tradutor",
    "traduz e cola o que eu copiei", "traduz isso pra mim", "como se diz obrigado em japonês", "lê a tela",
    "sai do foco", "pomodoro de 25 minutos", "modo fantasma", "fica quieta", "seja breve",
]
ATALHOS_DO_NUCLEO = [
    ("abre o youtube", "abrir", {"alvo": "youtube"}),
    ("fecha o chrome", "fechar_programa", {"nome": "chrome"}),
    ("toca legião urbana", "tocar_youtube", {"busca": "legiao urbana"}),
    ("modo jogo", "rotina", {"acao": "executar", "nome": "modo jogo"}),
    ("volume 30", "ajustar_volume", {"acao": "definir", "valor": 30}),
    ("analisa a tela", "ver", {"fonte": "tela"}),
    ("o que é isso?", "ver", {"fonte": "camera"}),
    ("planeja meu dia", "planejar", {"acao": "dia"}),
    ("abre o jornal", "jornal", {"acao": "mostrar"}),
    ("ativa o modo escuro", "configuracao", {"item": "modo_escuro", "valor": "ligar"}),
]


def test_frases_do_nucleo_nao_sao_capturadas(app):
    def rodar(*_a, **_k):
        raise AssertionError("a extensão capturou uma frase do núcleo")

    capturadas = [f for f in FRASES_DO_NUCLEO if comunicacao.atalho(normalizar(f), app.contexto(), rodar, f) is not None]
    assert capturadas == []


def test_nucleo_continua_com_os_mesmos_atalhos(app, monkeypatch):
    chamadas = registrar_execucoes(app, monkeypatch)
    agente = sem_ia(app)
    for frase, ferramenta, args in ATALHOS_DO_NUCLEO:
        chamadas.clear()
        assert agente.processar(frase)["caminho"] == "atalho", frase
        nome, argumentos = chamadas[0]
        assert nome == ferramenta and args.items() <= argumentos.items(), (frase, nome, argumentos)


# ---------------------------------------------------------------- atalhos de tradução

ATALHOS_DE_TRADUCAO = [
    ("modo tradutor para inglês", {"acao": "ao_vivo", "idioma": "ingles"}),
    ("Sexta-Feira, ativa o modo tradutor em espanhol", {"acao": "ao_vivo", "idioma": "espanhol"}),
    ("traduz para espanhol o que eu falar", {"acao": "ao_vivo", "idioma": "espanhol"}),
    ("traduz tudo que eu disser para o francês", {"acao": "ao_vivo", "idioma": "frances"}),
    ("tradução ao vivo inglês", {"acao": "ao_vivo", "idioma": "ingles"}),
    ("liga o tradutor em japonês", {"acao": "ao_vivo", "idioma": "japones"}),
    ("modo tradutor", {"acao": "ao_vivo"}),
    ("para de traduzir", {"acao": "parar"}),
    ("sair do tradutor", {"acao": "parar"}),
    ("desliga o modo tradutor", {"acao": "parar"}),
    ("traduz a tela", {"acao": "tela"}),
    ("traduz o que está na tela para português", {"acao": "tela", "idioma": "portugues"}),
    ("traduz essa página", {"acao": "tela"}),
    ("traduz essa página para o inglês", {"acao": "tela", "idioma": "ingles"}),
    ("traduz o que eu copiei para inglês", {"acao": "copiado", "idioma": "ingles"}),
    ("traduz o texto copiado", {"acao": "copiado"}),
]


def test_atalhos_de_traducao(app, monkeypatch):
    chamadas = registrar_execucoes(app, monkeypatch)
    agente = sem_ia(app)
    for frase, args in ATALHOS_DE_TRADUCAO:
        chamadas.clear()
        assert agente.processar(frase)["caminho"] == "atalho", frase
        assert chamadas == [("traducao", args)], frase


def test_idioma_desconhecido_fica_com_a_ia(app):
    nunca = lambda *_a, **_k: pytest.fail("não devia virar atalho")  # noqa: E731
    assert comunicacao.atalho("modo tradutor para klingon", app.contexto(), nunca, None) is None
    assert comunicacao.atalho("traduz a tela para elfico", app.contexto(), nunca, None) is None


@pytest.mark.parametrize("nome,codigo", [("inglês", "en"), ("o Inglês", "en"), ("castelhano", "es"), ("mandarim", "zh"),
                                         ("ja", "ja"), ("klingon", None), ("", None)])
def test_idioma_por_nome(nome, codigo):
    idioma = comunicacao.idioma_por_nome(nome)
    assert (idioma.codigo if idioma else None) == codigo


# ---------------------------------------------------------------- modo tradutor

@pytest.fixture
def conversa(app, monkeypatch):
    """Modo tradutor com microfone, Whisper e cérebro simulados."""
    app.voz.mic_ok = True
    ouvidos: list[tuple[str, str]] = []  # o que o "Whisper" devolve, em ordem: (texto, idioma)
    monkeypatch.setattr(app.transcritor, "transcrever_idioma",
                        lambda audio, idioma=None, candidatos=(), dica="": ouvidos.pop(0))
    traducoes = {"Bom dia, tudo bem?": '"Good morning, how are you?"', "I'm fine, thanks.": "Estou bem, obrigado.",
                 "Chega.": "Enough.", "Onde fica a estação?": "¿Dónde está la estación?"}
    pedidos: list[tuple[str, str]] = []

    def completar(sistema, texto, rapido=True):
        pedidos.append((sistema, texto))
        return traducoes[texto]

    monkeypatch.setattr(app.agente, "completar", completar)
    return SimpleNamespace(ouvidos=ouvidos, pedidos=pedidos)


def ligar(app, idioma: str = "inglês") -> dict:
    return app.registro.executar("traducao", {"acao": "ao_vivo", "idioma": idioma}, app.contexto())


def test_conversa_nos_dois_sentidos(app, conversa):
    resposta = ligar(app)
    assert resposta["ok"] and "português e inglês" in resposta["resumo"]
    ouvir = app.voz._escuta_continua
    assert ouvir is not None
    conversa.ouvidos += [("Bom dia, tudo bem?", "pt"), ("I'm fine, thanks.", "en")]
    ouvir(SILENCIO)
    ouvir(SILENCIO)

    assert app.fala.falas == ["Good morning, how are you?", "Estou bem, obrigado."]
    assert app.fala.vozes == [AVA, None]  # voz nativa no inglês; a dela no português
    ida, volta = (sistema for sistema, _ in conversa.pedidos)
    assert "do português do Brasil para o inglês" in ida and "SOMENTE com a tradução" in ida
    assert "do inglês para o português do Brasil" in volta
    holograma = app.hologramas.lista()[-1]
    assert holograma["tipo"] == "traducao" and holograma["dados"]["ativo"]
    linhas = holograma["dados"]["linhas"]
    assert [(l["de"], l["para"], l["traducao"]) for l in linhas] == [
        ("pt", "en", "Good morning, how are you?"), ("en", "pt", "Estou bem, obrigado.")]  # a mais nova embaixo


@pytest.mark.parametrize("fala", ["Sexta-Feira, para de traduzir.", "Sair do tradutor", "Sexta-feira, chega."])
def test_sair_do_tradutor_por_voz(app, conversa, fala):
    ligar(app)
    ouvir = app.voz._escuta_continua
    conversa.ouvidos.append((fala, "pt"))
    ouvir(SILENCIO)
    assert app.tradutor.alvo is None and app.voz._escuta_continua is None
    assert app.fala.falas[-1] == "Modo tradutor desligado."
    assert conversa.pedidos == []  # o pedido de parar não foi traduzido
    assert app.hologramas.lista()[-1]["dados"]["ativo"] is False


def test_sem_o_nome_uma_palavra_solta_e_traduzida(app, conversa):
    ligar(app)
    conversa.ouvidos.append(("Chega.", "pt"))
    app.voz._escuta_continua(SILENCIO)
    assert app.tradutor.alvo is not None and app.fala.falas[-1] == "Enough."


def test_trocar_de_idioma_sem_sair(app, conversa):
    ligar(app)
    conversa.ouvidos += [("Sexta-Feira, modo tradutor para espanhol", "pt"), ("Onde fica a estação?", "pt")]
    app.voz._escuta_continua(SILENCIO)
    assert app.fala.falas[-1] == "Agora traduzo entre português e espanhol."
    app.voz._escuta_continua(SILENCIO)
    assert app.fala.falas[-1] == "¿Dónde está la estación?" and app.fala.vozes[-1] == "es-ES-ElviraNeural"


def test_esc_no_hud_desliga(app, conversa):
    ligar(app, "espanhol")
    avisos = []
    app.barramento.ouvir(lambda e: e["tipo"] == "aviso" and avisos.append(e["texto"]))
    parar = {"tipo": "traducao.parar"}
    assert asyncio.run(comunicacao.mensagem_ws(app, None, None, parar, None))
    assert app.tradutor.alvo is None and app.voz._escuta_continua is None
    assert asyncio.run(comunicacao.mensagem_ws(app, None, None, parar, None))  # Esc de novo: nada a avisar
    assert avisos == ["Modo tradutor desligado."]
    assert not asyncio.run(comunicacao.mensagem_ws(app, None, None, {"tipo": "outro"}, None))


def test_tradutor_precisa_do_microfone_e_de_outro_idioma(app):
    resposta = ligar(app)
    assert not resposta["ok"] and "microfone" in resposta["resumo"] and app.voz._escuta_continua is None
    app.voz.mic_ok = True
    resposta = ligar(app, "português")
    assert not resposta["ok"] and "já falo português" in resposta["resumo"]
    resposta = ligar(app, "klingon")
    assert not resposta["ok"] and "inglês, espanhol" in resposta["resumo"]
    assert app.tradutor.alvo is None


def test_sem_idioma_usa_o_ultimo(app, conversa):
    ligar(app, "francês")
    app.registro.executar("traducao", {"acao": "parar"}, app.contexto())
    app.registro.executar("traducao", {"acao": "ao_vivo"}, app.contexto())
    assert app.tradutor.alvo.codigo == "fr"


def test_falha_na_traducao_avisa(app, conversa, monkeypatch):
    def falhar(sistema, texto, rapido=True):
        raise ErroOllama("Ollama fora do ar")

    monkeypatch.setattr(app.agente, "completar", falhar)
    avisos = []
    app.barramento.ouvir(lambda e: e["tipo"] == "aviso" and avisos.append(e["texto"]))
    ligar(app)
    conversa.ouvidos.append(("Bom dia, tudo bem?", "pt"))
    app.voz._escuta_continua(SILENCIO)
    assert app.fala.falas[-1] == "Não consegui traduzir essa. Pode repetir?"
    assert avisos == ["Não consegui traduzir: Ollama fora do ar"]


def test_desligado_enquanto_traduzia_nao_fala(app, conversa, monkeypatch):
    ligar(app)
    ouvir = app.voz._escuta_continua

    def completar_e_desligar(sistema, texto, rapido=True):
        app.tradutor.desligar()  # Esc no meio da tradução
        return "Good morning."

    monkeypatch.setattr(app.agente, "completar", completar_e_desligar)
    conversa.ouvidos.append(("Bom dia, tudo bem?", "pt"))
    ouvir(SILENCIO)
    assert "Good morning." not in app.fala.falas


def test_encerrar_desliga_o_tradutor(app, conversa):
    ligar(app)
    comunicacao.encerrar(app)
    assert app.tradutor.alvo is None and app.voz._escuta_continua is None


# ---------------------------------------------------------------- laço de voz

def iniciar_voz(app, monkeypatch, roteiro):
    voz = modulo_voz.AssistenteVoz(app)
    voz.mic = MicrofoneFalso(roteiro)
    monkeypatch.setattr(modulo_voz, "criar_detector", lambda cfg: DetectorFalso())
    return voz


def test_escuta_continua_dispensa_a_palavra_de_ativacao(app, monkeypatch):
    voz = iniciar_voz(app, monkeypatch, [bloco(0)] * 5 + [bloco(3000)] * 20 + [bloco(0)] * 60)
    pedidos = []
    monkeypatch.setattr(app.agente, "processar", lambda *a, **k: pedidos.append(a))
    ouvidos = []
    voz.escutar_continuamente(ouvidos.append)
    voz.iniciar()
    try:
        assert esperar(lambda: ouvidos)
    finally:
        voz.escutar_continuamente(None)
        voz.parar()
    assert ouvidos[0].dtype == np.float32 and float(np.abs(ouvidos[0]).max()) > 0.05
    assert pedidos == []  # nada foi tratado como comando


def test_escuta_continua_nao_grava_a_propria_voz(app, monkeypatch):
    falando = threading.Event()
    falando.set()
    monkeypatch.setattr(app.fala, "falando_ou_na_fila", falando.is_set)
    voz = iniciar_voz(app, monkeypatch, [bloco(3000)] * 20 + [bloco(0)] * 20)  # o eco da tradução que ela fala
    ouvidos = []
    voz.escutar_continuamente(ouvidos.append)
    voz.iniciar()
    try:
        time.sleep(0.4)
        assert ouvidos == []
        falando.clear()
        for b in [bloco(0)] * 10 + [bloco(3000)] * 20 + [bloco(0)] * 60:  # agora sim, alguém fala
            voz.mic.fila.put(b)
        assert esperar(lambda: ouvidos)
    finally:
        voz.escutar_continuamente(None)
        voz.parar()
    assert len(ouvidos) == 1


def test_pedido_que_liga_o_tradutor_encerra_o_atendimento(app, monkeypatch):
    # "Sexta-Feira, modo tradutor para inglês" e, logo depois, a primeira frase a traduzir
    roteiro = [bloco(9000)] * 3 + [bloco(3000)] * 20 + [bloco(0)] * 40 + [bloco(3000)] * 20 + [bloco(0)] * 60
    voz = iniciar_voz(app, monkeypatch, roteiro)
    monkeypatch.setattr(app.transcritor, "transcrever", lambda audio: "Sexta-feira, modo tradutor para inglês")
    ouvidos, pedidos = [], []

    def processar(texto, canal="voz", **_k):
        pedidos.append(texto)
        voz.escutar_continuamente(ouvidos.append)

    monkeypatch.setattr(app.agente, "processar", processar)
    app.prefs.atualizar({"modo_continuacao": True})
    voz.iniciar()
    try:
        assert esperar(lambda: ouvidos)
    finally:
        voz.escutar_continuamente(None)
        voz.parar()
    assert pedidos == ["modo tradutor para inglês"]  # a frase seguinte foi para o tradutor, não virou pedido


# ---------------------------------------------------------------- transcrição com idioma

class ModeloWhisperFalso:
    def __init__(self, deteccao: list[tuple[str, float]]):
        self.deteccao = deteccao
        self.chamadas: list[tuple[str | None, str | None]] = []

    def transcribe(self, audio, language=None, initial_prompt=None, **_opcoes):
        self.chamadas.append((language, initial_prompt))
        idioma = language or self.deteccao[0][0]
        info = SimpleNamespace(language=idioma, all_language_probs=None if language else self.deteccao)
        segmento = SimpleNamespace(text=f" fala em {idioma} ", no_speech_prob=0.01, avg_logprob=-0.2)
        return iter([segmento]), info


def transcritor(deteccao) -> Transcritor:
    t = Transcritor()
    t._modelo = ModeloWhisperFalso(deteccao)
    return t


def test_deteccao_de_idioma_limitada_aos_candidatos():
    t = transcritor([("es", 0.5), ("pt", 0.4), ("en", 0.1)])  # português confundido com espanhol
    assert t.transcrever_idioma(SILENCIO, candidatos=("pt", "en")) == ("fala em pt", "pt")
    assert t._modelo.chamadas == [(None, None), ("pt", None)]


def test_deteccao_dentro_dos_candidatos_decodifica_uma_vez():
    t = transcritor([("en", 0.9), ("pt", 0.1)])
    assert t.transcrever_idioma(SILENCIO, candidatos=("pt", "en")) == ("fala em en", "en")
    assert t._modelo.chamadas == [(None, None)]


def test_comandos_continuam_em_portugues_com_a_dica():
    t = transcritor([("en", 0.9)])
    assert t.transcrever(SILENCIO) == "fala em pt"
    assert t._modelo.chamadas == [("pt", DICA_PADRAO)]
    assert t.transcrever_idioma(np.zeros(1000, dtype=np.float32)) == ("", "")  # curto demais


# ---------------------------------------------------------------- voz por frase

def test_voz_por_frase_tem_cache_proprio_e_mantem_o_efeito(app, monkeypatch):
    fala = modulo_fala.Fala(app)
    try:
        pedidos = []

        async def edge(texto, voz, velocidade, tom_voz):
            pedidos.append((voz, velocidade, tom_voz))
            return b"mp3"

        monkeypatch.setattr(fala, "_edge_bytes", edge)
        monkeypatch.setattr(modulo_fala, "decodificar", lambda dados: (np.zeros(8, dtype=np.float32), 24000))
        monkeypatch.setattr(modulo_fala.efeitos, "traje", lambda audio, taxa: audio + 1)
        app.prefs.atualizar({"voz": "sexta", "voz_efeito": True})
        fala._sintetizar("Hello.", AVA)
        fala._sintetizar("Hello.")
        audio, _taxa = fala._sintetizar("Hello.", AVA)  # do cache
        assert pedidos == [(AVA, "+0%", "+0Hz"), ("pt-BR-ThalitaMultilingualNeural", "+4%", "-3Hz")]
        assert audio[0] == 1.0  # o efeito do traje vale também para a voz do tradutor

        sintetizados = []
        monkeypatch.setattr(fala, "_sintetizar",
                            lambda texto, voz=None: sintetizados.append((texto, voz)) or (tom([(440, 0.05)]), 24000))
        fala.reprodutor = ReprodutorFalso()
        fala.falar("Good morning.", voz=AVA)
        fala.falar("Bom dia.")
        assert fala.aguardar(5)
        assert sintetizados == [("Good morning.", AVA), ("Bom dia.", None)]
    finally:
        fala.encerrar()


def test_voz_do_windows_por_idioma(app):
    fala = modulo_fala.Fala(app)
    try:
        vozes = [SimpleNamespace(id=r"HKEY\Tokens\TTS_MS_EN-US_ZIRA_11.0", name="Microsoft Zira Desktop - English (United States)"),
                 SimpleNamespace(id=r"HKEY\Tokens\TTS_MS_PT-BR_MARIA_11.0", name="Microsoft Maria Desktop - Portuguese(Brazil)")]
        fala._pyttsx3 = SimpleNamespace(getProperty=lambda nome: vozes)
        assert fala._voz_windows("en") == vozes[0].id
        assert fala._voz_windows("pt") == vozes[1].id
        assert fala._voz_windows("ja") is None
    finally:
        fala.encerrar()


# ---------------------------------------------------------------- tela e texto copiado

@pytest.fixture
def tela(app, monkeypatch):
    from PIL import Image

    monkeypatch.setattr("sexta.habilidades.visao.capturar_tela", lambda: Image.new("RGB", (64, 32)))
    agente = sem_ia(app)
    pedidos: list[str] = []
    resposta = {"texto": "ORIGINAL:\nWelcome back\nYour order has shipped\nTRADUÇÃO:\nBem-vindo de volta\nSeu pedido foi enviado"}

    def visao(pergunta, imagens, sistema="", modelo=None):
        assert imagens and isinstance(imagens[0], str)
        pedidos.append(sistema)
        return resposta["texto"]

    monkeypatch.setattr(agente.ollama, "visao", visao)
    return SimpleNamespace(agente=agente, pedidos=pedidos, resposta=resposta)


def test_traduz_a_tela_para_portugues(app, tela):
    resposta = tela.agente.processar("traduz a tela")
    assert resposta["caminho"] == "atalho"
    assert resposta["texto"] == "Traduzi a tela. Começa assim: Bem-vindo de volta. Seu pedido foi enviado."
    assert "para o português do Brasil" in tela.pedidos[0] and "TRADUÇÃO:" in tela.pedidos[0]
    holograma = app.hologramas.lista()[-1]
    assert holograma["titulo"] == "Tela traduzida" and holograma["dados"]["modo"] == "tela"
    linha = holograma["dados"]["linhas"][0]
    assert linha["original"] == "Welcome back\nYour order has shipped" and linha["traducao"].startswith("Bem-vindo")


def test_traduz_a_pagina_para_outro_idioma(app, tela):
    tela.resposta["texto"] = "Bienvenido"  # o modelo ignorou o formato: tudo vira tradução
    resposta = tela.agente.processar("traduz essa página para o espanhol")
    assert resposta["texto"] == "Traduzi a tela para o espanhol. Está no holograma."
    assert "para o espanhol" in tela.pedidos[0]
    assert app.hologramas.lista()[-1]["dados"]["linhas"][0] | {"id": 0} == {
        "id": 0, "de": "", "para": "es", "original": "", "traducao": "Bienvenido"}


def test_tela_indisponivel(app, tela, monkeypatch):
    def falhar():
        raise OSError("sem monitor")

    monkeypatch.setattr("sexta.habilidades.visao.capturar_tela", falhar)
    assert tela.agente.processar("traduz a tela")["texto"] == "Não consegui capturar a tela: sem monitor"


@pytest.fixture
def copiado(app, monkeypatch):
    area = {"texto": "Bom dia, equipe. A reunião foi adiada."}
    monkeypatch.setattr("sexta.habilidades.area_transferencia.ler", lambda: area["texto"])
    monkeypatch.setattr("sexta.habilidades.area_transferencia.escrever", lambda texto: area.update(texto=texto))
    agente = sem_ia(app)
    pedidos: list[tuple[str, str, bool]] = []

    def completar(sistema, texto, rapido=True):
        pedidos.append((sistema, texto, rapido))
        return "Good morning, team. The meeting was postponed."

    monkeypatch.setattr(agente, "completar", completar)
    return SimpleNamespace(agente=agente, area=area, pedidos=pedidos)


def test_traduz_o_que_eu_copiei(app, copiado):
    resposta = copiado.agente.processar("traduz o que eu copiei para inglês")
    assert resposta["caminho"] == "atalho" and resposta["texto"] == "Traduzi para o inglês e copiei. É só colar."
    assert copiado.area["texto"] == "Good morning, team. The meeting was postponed."
    sistema, texto, rapido = copiado.pedidos[0]
    assert "para o inglês" in sistema and texto == "Bom dia, equipe. A reunião foi adiada." and rapido is False
    dados = app.hologramas.lista()[-1]["dados"]
    assert dados["modo"] == "copiado" and dados["linhas"][0]["original"].startswith("Bom dia")


def test_copiado_sem_idioma_escolhe_sozinho(app, copiado):
    assert copiado.agente.processar("traduz o texto copiado")["texto"] == "Traduzi e copiei. É só colar."
    assert comunicacao.DESTINO_AUTOMATICO in copiado.pedidos[0][0]


def test_area_de_transferencia_vazia(app, copiado):
    copiado.area["texto"] = "  "
    assert "vazia" in copiado.agente.processar("traduz o que eu copiei")["texto"]
    assert copiado.pedidos == []


# ---------------------------------------------------------------- protocolos, diagnóstico e holograma

def test_protocolo_com_personalidade_e_tradutor(app):
    app.voz.mic_ok = True
    app.rotinas.criar("reuniao internacional", [{"acao": "personalidade", "valor": "formal"},
                                                {"acao": "tradutor", "valor": "inglês"}])
    app.rotinas._executar(app.rotinas.obter("reuniao internacional"), app.contexto())
    assert app.prefs.get("personalidade") == "formal" and app.tradutor.alvo.codigo == "en"
    assert app.fala.falas[-1].startswith("Modo tradutor ligado: português e inglês.")
    app.rotinas.criar("fim da reuniao", [{"acao": "tradutor", "valor": "desligar"}])
    app.rotinas._executar(app.rotinas.obter("fim da reuniao"), app.contexto())
    assert app.tradutor.alvo is None and app.fala.falas[-1] == "Modo tradutor desligado."


def test_diagnostico_e_dados_do_holograma(app):
    assert comunicacao.diagnostico(app)[0]["ok"]
    app.cfg.voz_motor = "windows"
    assert not comunicacao.diagnostico(app)[0]["ok"]
    assert comunicacao.dados_holograma(app, "traducao")["linhas"] == []
    assert comunicacao.dados_holograma(app, "clima") is None
