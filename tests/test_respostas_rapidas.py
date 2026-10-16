"""Conversa social sem IA, cadeia de cérebros reserva e mapeamento ATT&CK da análise estática."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from sexta.cerebro import agente, atalhos, personalidade
from sexta.cerebro.ollama import ErroOllama
from sexta.cerebro.reserva import CerebroComReserva
from sexta.extensoes.seguranca import padroes
from sexta.util.texto import normalizar
from sexta.voz.transcricao import _ECO_IDIOMA


def _social(fala: str) -> str | None:
    t = re.sub(r"^(sexta feira|sexta) ", "", normalizar(fala))  # como em atalhos.tentar
    return next((chave for padrao, chave in atalhos._SOCIAL if padrao.match(t)), None)


@pytest.mark.parametrize("fala, chave", [
    ("tudo bem?", "tudo_bem"), ("Tudo bem, Sexta-Feira?", "tudo_bem"), ("oi, tudo bem?", "tudo_bem"),
    ("como você está?", "tudo_bem"), ("tudo bom e você?", "tudo_bem"), ("beleza?", "tudo_bem"),
    ("bom dia", "saudacao"), ("Boa noite, Sexta!", "saudacao"), ("oi", "saudacao"),
    ("tá aí?", "presente"), ("você está me ouvindo?", "presente"),
    ("quem é você?", "quem_sou"), ("mandou bem", "elogio"), ("até amanhã", "tchau"),
])
def test_conversa_social_responde_sem_ia(fala, chave):
    assert _social(fala) == chave


@pytest.mark.parametrize("fala", [
    "tudo bem, abre o spotify", "como faço pra instalar python", "bom dia, planeja meu dia",
    "como está o tempo", "como vai o projeto do campeonato", "tudo bem se eu fechar o chrome?",
])
def test_pedidos_de_verdade_seguem_para_a_ia(fala):
    assert _social(fala) is None


def test_frases_prontas_cobrem_as_respostas_sociais():
    prefs = {"personalidade": "amigavel", "tratamento": "chefe"}
    prontas = set(personalidade.frases_prontas(prefs))
    for chave in personalidade.SOCIAIS:
        for hora in (8, 15, 21):
            assert personalidade.resposta(prefs, chave, hora=hora) in prontas


def test_eco_da_dica_do_whisper_e_removido():
    assert _ECO_IDIOMA.sub("", "em português do Brasil").strip() == ""
    assert _ECO_IDIOMA.sub("", "Em português do Brasil, abre o Spotify").strip() == "abre o Spotify"
    assert _ECO_IDIOMA.sub("", "abre o português").strip() == "abre o português"


def test_reservas_configuradas_em_cadeia(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = SimpleNamespace(cerebro_reserva="livre, ollama;claude,livre")
    assert agente.reservas_configuradas(cfg, "claude") == ["livre", "ollama"]
    assert agente.reservas_configuradas(cfg, "livre") == ["ollama"]


class _Cerebro:
    def __init__(self, nome: str, falha: bool) -> None:
        self.nome, self.falha, self.modelo, self.pedido = nome, falha, f"{nome}-principal", "?"

    def conversar(self, mensagens, ferramentas=None, cancelado=lambda: False, *, modelo=None, max_tokens=None,
                  pensar=False):
        self.pedido = modelo
        if self.falha:
            raise ErroOllama(f"{self.nome} fora do ar")
        yield {"tipo": "texto", "texto": self.nome}


def test_cadeia_cai_ate_o_ultimo_cerebro_que_responde():
    claude, livre, ollama = _Cerebro("claude", True), _Cerebro("livre", True), _Cerebro("ollama", False)
    cadeia = CerebroComReserva(claude, CerebroComReserva(livre, ollama, ""), "auto:fast")
    textos = [e["texto"] for e in cadeia.conversar([], modelo="claude-haiku")]
    assert textos == ["ollama"]
    # o modelo rápido de cada cérebro é traduzido para o do próximo
    assert (claude.pedido, livre.pedido, ollama.pedido) == ("claude-haiku", "auto:fast", None)


def test_achados_viram_tecnicas_attack_e_indicadores():
    motivos = [padroes.Motivo("persistencia", "inicia com o Windows", 2, tecnica="persistencia"),
               padroes.Motivo("powershell_base64", "esconde comando", 3, tecnica="ofuscacao"),
               padroes.Motivo("ofuscacao", "embaralhado", 2, tecnica="ofuscacao"),
               padroes.Motivo("assinado", "assinado", -3)]
    tecnicas = padroes.mapear_attack(motivos)
    ids = [t["id"] for t in tecnicas]
    assert "T1547.001" in ids and "T1059.001" in ids
    assert ids.count("T1027") == 1  # sem repetir; guarda os dois achados de origem
    assert next(t for t in tecnicas if t["id"] == "T1027")["achados"] == ["powershell_base64", "ofuscacao"]
    assert next(t for t in tecnicas if t["id"] == "T1547.001")["url"].endswith("/T1547/001/")
    iocs = padroes.indicadores({"sha256": "ab", "strings": {"urls": ["http://Mal.example:8080/x"], "ips": ["10.0.0.9"]}})
    assert iocs["dominios"] == ["mal.example"] and iocs["ips"] == ["10.0.0.9"]
