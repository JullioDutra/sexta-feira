"""Cérebro Claude com um cliente simulado (sem rede): streaming, ferramentas, cache e reenvio."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

from sexta.cerebro.agente import Agente
from sexta.cerebro.claude import ClienteClaude


class StreamFalso:
    def __init__(self, textos, final):
        self.textos, self.final = textos, final

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        for t in self.textos:
            yield NS(type="text", text=t)

    def get_final_message(self):
        return self.final


def mensagem(blocos, stop="end_turn"):
    uso = NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=4000, cache_creation_input_tokens=0)
    return NS(content=blocos, stop_reason=stop, usage=uso, model="claude-opus-5-5")


class SdkFalso:
    def __init__(self, rodadas):
        self.rodadas = list(rodadas)
        self.pedidos = []
        self.beta = NS(messages=NS(stream=self._stream, create=self._create))
        self.messages = NS(create=self._create)

    def _stream(self, **params):
        self.pedidos.append(params)
        textos, final = self.rodadas.pop(0)
        return StreamFalso(textos, final)

    def _create(self, **params):
        self.pedidos.append(params)
        return mensagem([NS(type="text", text="Vejo um erro de sintaxe na linha 3.")])


def test_claude_ferramenta_direta_e_cache(app, monkeypatch):
    monkeypatch.setattr("sexta.habilidades.windows.definir_volume", lambda v: v)
    uso = NS(type="tool_use", id="toolu_1", name="ajustar_volume", input={"acao": "definir", "valor": 25})
    sdk = SdkFalso([([], mensagem([NS(type="thinking", thinking=""), uso], stop="tool_use"))])
    app.prefs.atualizar({"atalhos_rapidos": False})
    app.agente = Agente(app, ClienteClaude("claude-opus-5-5", cliente=sdk))
    r = app.agente.processar("deixa o som baixinho, uns 25", canal="voz")
    assert r["texto"] == "Volume em 25%." and len(sdk.pedidos) == 1
    pedido = sdk.pedidos[0]
    assert pedido["system"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert pedido["output_config"] == {"effort": "low"}
    assert pedido["fallbacks"] == "default" and pedido["betas"] == ["server-side-fallback-2026-07-01"]
    assert all(t["eager_input_streaming"] for t in pedido["tools"])
    assert all(m["role"] != "system" for m in pedido["messages"])


def test_claude_resultado_volta_com_id(app):
    uso = NS(type="tool_use", id="toolu_9", name="obter_clima", input={})
    sdk = SdkFalso([
        ([], mensagem([uso], stop="tool_use")),
        (["Qual é a sua cidade, ", "chefe?"], mensagem([NS(type="text", text="Qual é a sua cidade, chefe?")])),
    ])
    app.prefs.atualizar({"atalhos_rapidos": False})
    app.agente = Agente(app, ClienteClaude("claude-opus-5-5", cliente=sdk))
    r = app.agente.processar("vai chover hoje?", canal="texto", falar=False)
    assert r["texto"] == "Qual é a sua cidade, chefe?"
    segunda = sdk.pedidos[1]["messages"]
    assert segunda[-2] == {"role": "assistant", "content": [uso]}
    resultado = segunda[-1]["content"][0]
    assert resultado["tool_use_id"] == "toolu_9" and resultado["is_error"] is True
    assert json.loads(resultado["content"])["ok"] is False
    assert sdk.pedidos[1]["output_config"] == {"effort": "medium"}


def test_claude_dois_cerebros(app):
    app.cfg.claude_modelo_rapido = "claude-haiku-5-5"
    sdk = SdkFalso([(["Ok."], mensagem([NS(type="text", text="Ok.")])) for _ in range(2)])
    app.prefs.atualizar({"atalhos_rapidos": False})
    agente = Agente(app, ClienteClaude("claude-opus-5-5", cliente=sdk))
    agente.modelo_rapido = "claude-haiku-5-5"
    agente.processar("acende a luz", canal="texto", falar=False)
    agente.processar("me explica por que o céu é azul com detalhes", canal="texto", falar=False)
    assert sdk.pedidos[0]["model"] == "claude-haiku-5-5" and "fallbacks" not in sdk.pedidos[0]
    assert sdk.pedidos[1]["model"] == "claude-opus-5-5"


def test_claude_recusa_e_visao(app):
    sdk = SdkFalso([([], mensagem([], stop="refusal"))])
    app.prefs.atualizar({"atalhos_rapidos": False})
    app.agente = Agente(app, ClienteClaude("claude-opus-5-5", cliente=sdk))
    assert app.agente.processar("algo proibido", canal="texto", falar=False)["texto"] == "Não posso ajudar com isso."
    resposta = app.agente.ollama.visao("o que é isso?", ["AAAA"], "sistema")
    assert resposta.startswith("Vejo um erro")
    assert sdk.pedidos[-1]["messages"][0]["content"][0]["type"] == "image"


def test_historico_sobrevive_ao_reinicio(app):
    app.agente._registrar("meu nome é Jullio", "Prazer, Jullio.")
    novo = Agente(app, ClienteClaude("claude-opus-5-5", cliente=SdkFalso([])))
    assert novo.historico[-2:] == [{"role": "user", "content": "meu nome é Jullio"},
                                   {"role": "assistant", "content": "Prazer, Jullio."}]
