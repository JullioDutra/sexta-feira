"""O agente conversa com um Ollama falso (respostas NDJSON em streaming) e executa ferramentas."""

from __future__ import annotations

import json

import httpx

from sexta.cerebro.agente import Agente, FiltroTags
from sexta.cerebro.ollama import ClienteOllama


def ndjson(*objetos) -> bytes:
    return ("\n".join(json.dumps(o) for o in objetos) + "\n").encode()


class OllamaFalso:
    """Responde em sequência; guarda as requisições recebidas."""

    def __init__(self, respostas: list[httpx.Response]):
        self.respostas = list(respostas)
        self.requisicoes: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:9b"}]})
        self.requisicoes.append(json.loads(request.content))
        return self.respostas.pop(0)


def cliente(falso: OllamaFalso) -> ClienteOllama:
    return ClienteOllama("http://ollama.teste", "qwen3.5:9b", transporte=httpx.MockTransport(falso))


def test_ferramenta_e_resposta_final(app):
    falso = OllamaFalso([
        httpx.Response(200, content=ndjson(
            {"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "memoria", "arguments": {"acao": "lembrar", "fato": "O time dele é o Cruzeiro"}}}]},
             "done": False},
            {"message": {"role": "assistant", "content": ""}, "done": True})),
        httpx.Response(200, content=ndjson(
            {"message": {"role": "assistant", "content": "Anotado, chefe. "}, "done": False},
            {"message": {"role": "assistant", "content": "Vou lembrar que você torce pro Cruzeiro."}, "done": False},
            {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"})),
    ])
    app.prefs.atualizar({"atalhos_rapidos": False})
    app.agente = Agente(app, cliente(falso))
    resposta = app.agente.processar("lembra que meu time é o Cruzeiro", canal="voz")

    assert resposta["texto"] == "Anotado, chefe. Vou lembrar que você torce pro Cruzeiro."
    assert app.memoria.listar() == ["O time dele é o Cruzeiro"]
    # a segunda chamada leva o resultado da ferramenta
    segunda = falso.requisicoes[1]["messages"]
    assert segunda[-1]["role"] == "tool" and segunda[-1]["tool_name"] == "memoria"
    assert json.loads(segunda[-1]["content"])["ok"] is True
    assert falso.requisicoes[0]["think"] is False and falso.requisicoes[0]["tools"]
    # a voz recebeu frases completas
    assert app.fala.tudo() == "Anotado, chefe. Vou lembrar que você torce pro Cruzeiro."
    # o histórico guarda só pergunta e resposta
    assert [m["role"] for m in app.agente.historico] == ["user", "assistant"]


def test_modelo_sem_think_tenta_de_novo(app):
    falso = OllamaFalso([
        httpx.Response(400, json={"error": '"llama3.1" does not support thinking'}),
        httpx.Response(200, content=ndjson({"message": {"content": "Oi! Tudo certo por aqui."}, "done": True})),
    ])
    app.prefs.atualizar({"atalhos_rapidos": False})
    app.agente = Agente(app, cliente(falso))
    resposta = app.agente.processar("oi", canal="texto", falar=False)
    assert resposta["texto"] == "Oi! Tudo certo por aqui."
    assert "think" not in falso.requisicoes[1]
    assert app.fala.falas == []


def test_ollama_fora_do_ar(app):
    def recusar(request):
        raise httpx.ConnectError("recusado", request=request)

    app.prefs.atualizar({"atalhos_rapidos": False})
    app.agente = Agente(app, ClienteOllama("http://ollama.teste", "x", transporte=httpx.MockTransport(recusar)))
    resposta = app.agente.processar("qual a capital da França?")
    assert "Ollama" in resposta["texto"]
    assert app.estado.atual == "inativa"


def test_atalho_rapido_nao_chama_ia(app, monkeypatch):
    chamadas = []
    monkeypatch.setattr("sexta.habilidades.windows.definir_volume", lambda v: chamadas.append(v) or v)
    app.agente = Agente(app, cliente(OllamaFalso([])))
    resposta = app.agente.processar("volume 40")
    assert chamadas == [40]
    assert resposta["texto"] == "Volume em 40%."
    assert app.fala.falas == ["Volume em 40%."]


def test_atalho_rotina(app, monkeypatch):
    executadas = []
    monkeypatch.setattr(app.rotinas, "executar", lambda rotina, ctx: executadas.append(rotina.nome))
    app.agente = Agente(app, cliente(OllamaFalso([])))
    app.agente.processar("modo jogo")
    assert executadas == ["modo jogo"]


def test_filtro_tags_remove_pensamento_e_captura_ferramenta():
    filtro = FiltroTags()
    pedacos = ["<thi", "nk>hmm, vou ", "ver</think>Claro! ", "<tool_call>{\"name\": \"abrir\", ",
               "\"arguments\": {\"alvo\": \"Spotify\"}}</tool_call>", " Abrindo."]
    visivel = "".join(filtro.alimentar(p) for p in pedacos) + filtro.finalizar()
    assert visivel == "Claro!  Abrindo."
    assert filtro.chamadas() == [{"nome": "abrir", "argumentos": {"alvo": "Spotify"}}]


def test_esquemas_das_ferramentas_sao_validos(app):
    esquemas = app.registro.esquemas()
    nomes = {e["function"]["name"] for e in esquemas}
    assert {"obter_clima", "obter_noticias", "abrir", "criar_lembrete", "rotina", "holograma"} <= nomes
    for e in esquemas:
        parametros = e["function"]["parameters"]
        assert parametros["type"] == "object"
        for nome, p in parametros["properties"].items():
            assert "_obrigatorio" not in p, nome
        json.dumps(e)  # serializável
