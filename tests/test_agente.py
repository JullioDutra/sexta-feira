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


def test_ferramenta_direta_dispensa_segunda_rodada(app):
    """Ações cujo resultado já é a resposta (memória, volume, abrir...) não voltam ao modelo."""
    falso = OllamaFalso([
        httpx.Response(200, content=ndjson(
            {"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "memoria", "arguments": {"acao": "lembrar", "fato": "O time dele é o Cruzeiro"}}}]},
             "done": False},
            {"message": {"role": "assistant", "content": ""}, "done": True})),
    ])
    app.prefs.atualizar({"atalhos_rapidos": False})
    app.agente = Agente(app, cliente(falso))
    resposta = app.agente.processar("lembra que meu time é o Cruzeiro", canal="voz")

    assert resposta["texto"] == "Anotado."
    assert len(falso.requisicoes) == 1
    assert app.memoria.listar() == ["O time dele é o Cruzeiro"]
    assert app.fala.tudo() == "Anotado."
    assert falso.requisicoes[0]["think"] is False and falso.requisicoes[0]["tools"]
    assert [m["role"] for m in app.agente.historico] == ["user", "assistant"]


def test_ferramenta_de_dados_volta_ao_modelo(app):
    """Se a ferramenta falha (ou traz dados para interpretar), o modelo redige a resposta."""
    falso = OllamaFalso([
        httpx.Response(200, content=ndjson(
            {"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "obter_clima", "arguments": {}}}]}, "done": False},
            {"message": {"role": "assistant", "content": ""}, "done": True})),
        httpx.Response(200, content=ndjson(
            {"message": {"role": "assistant", "content": "Ainda não sei sua cidade, chefe. "}, "done": False},
            {"message": {"role": "assistant", "content": "Onde você mora?"}, "done": False},
            {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"})),
    ])
    app.prefs.atualizar({"atalhos_rapidos": False})
    app.agente = Agente(app, cliente(falso))
    resposta = app.agente.processar("como está o tempo?", canal="voz")

    assert resposta["texto"] == "Ainda não sei sua cidade, chefe. Onde você mora?"
    segunda = falso.requisicoes[1]["messages"]
    assert segunda[-1]["role"] == "tool" and segunda[-1]["tool_name"] == "obter_clima"
    assert json.loads(segunda[-1]["content"])["ok"] is False
    assert app.fala.tudo() == "Ainda não sei sua cidade, chefe. Onde você mora?"


def test_prompt_de_sistema_estavel_para_cache(app):
    """A hora vai na mensagem do usuário; o prompt de sistema não muda entre pedidos (cache do Ollama)."""
    resposta_simples = lambda: httpx.Response(200, content=ndjson({"message": {"content": "Oi."}, "done": True}))
    falso = OllamaFalso([resposta_simples(), resposta_simples()])
    app.prefs.atualizar({"atalhos_rapidos": False})
    app.agente = Agente(app, cliente(falso))
    app.agente.processar("oi", canal="voz")
    app.agente.processar("tudo bem?", canal="voz")
    sistema1, sistema2 = (r["messages"][0]["content"] for r in falso.requisicoes)
    assert sistema1 == sistema2
    ultima = falso.requisicoes[1]["messages"][-1]["content"]
    assert ultima.endswith("tudo bem?") and "canal: voz" in ultima
    # o histórico guarda o texto puro (sem o cabeçalho de hora)
    assert falso.requisicoes[1]["messages"][1] == {"role": "user", "content": "oi"}
    assert falso.requisicoes[0]["options"]["num_predict"] == app.cfg.ollama_max_tokens_voz


def test_dois_cerebros(app):
    app.cfg.ollama_modelo_rapido = "qwen3.5:4b"
    falso = OllamaFalso([httpx.Response(200, content=ndjson({"message": {"content": "Ok."}, "done": True}))
                         for _ in range(2)])
    app.prefs.atualizar({"atalhos_rapidos": False})
    app.agente = Agente(app, cliente(falso))
    app.agente.processar("liga a luz do quarto", canal="texto", falar=False)
    app.agente.processar("planeja meu dia considerando as reuniões e a academia", canal="texto", falar=False)
    assert falso.requisicoes[0]["model"] == "qwen3.5:4b"
    assert falso.requisicoes[1]["model"] == "qwen3.5:9b"


def test_area_transferencia_vai_junto(app, monkeypatch):
    monkeypatch.setattr("sexta.habilidades.area_transferencia.ler", lambda: "Texto copiado sobre o projeto.")
    falso = OllamaFalso([httpx.Response(200, content=ndjson({"message": {"content": "Resumo."}, "done": True}))])
    app.prefs.atualizar({"atalhos_rapidos": False})
    app.agente = Agente(app, cliente(falso))
    app.agente.processar("resume o que eu copiei", canal="texto", falar=False)
    ultima = falso.requisicoes[0]["messages"][-1]["content"]
    assert "<area_de_transferencia>\nTexto copiado sobre o projeto.\n</area_de_transferencia>" in ultima


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
