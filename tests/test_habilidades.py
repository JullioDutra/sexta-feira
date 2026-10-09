"""Clima, notícias, lembretes, rotinas e ferramentas (sem rede: respostas simuladas)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import httpx

from sexta.habilidades.clima import ServicoClima
from sexta.habilidades.lembretes import proxima_ocorrencia
from sexta.habilidades.noticias import interpretar_rss

GEO = {"results": [
    {"name": "Uberaba", "latitude": -19.75, "longitude": -47.93, "country_code": "BR", "country": "Brasil",
     "admin1": "Minas Gerais", "timezone": "America/Sao_Paulo", "population": 340000},
    {"name": "Uberaba", "latitude": -10.0, "longitude": -50.0, "country_code": "BR", "country": "Brasil",
     "admin1": "Goiás", "population": 100},
]}
PREVISAO = {
    "current": {"temperature_2m": 27.4, "apparent_temperature": 30.6, "relative_humidity_2m": 40, "is_day": 1,
                "weather_code": 1, "wind_speed_10m": 9.2},
    "hourly": {"time": [f"2026-10-09T{h:02d}:00" for h in range(14, 24)] + [f"2026-10-10T{h:02d}:00" for h in range(0, 14)],
               "temperature_2m": [27] * 24, "precipitation_probability": [10] * 24, "weather_code": [1] * 24, "is_day": [1] * 24},
    "daily": {"time": [f"2026-10-{d:02d}" for d in range(9, 16)], "weather_code": [1, 63, 3, 0, 0, 2, 95],
              "temperature_2m_max": [31.2, 25, 26, 28, 29, 30, 27], "temperature_2m_min": [18.4, 17, 16, 17, 18, 19, 19],
              "precipitation_probability_max": [10, 80, 30, 0, 0, 20, 70],
              "sunrise": ["2026-10-09T05:52"] * 7, "sunset": ["2026-10-09T18:21"] * 7, "uv_index_max": [9.1] * 7},
}


def servico_clima() -> ServicoClima:
    def responder(request: httpx.Request) -> httpx.Response:
        if "geocoding" in request.url.host:
            return httpx.Response(200, json=GEO)
        return httpx.Response(200, json=PREVISAO)

    return ServicoClima(httpx.Client(transport=httpx.MockTransport(responder)))


def test_clima_resumo():
    clima = servico_clima()
    local = clima.localizar("Uberaba, MG")
    assert local["rotulo"] == "Uberaba - MG"
    dados = clima.obter(local)
    assert dados["atual"]["temp"] == 27 and dados["dias"][1]["dia"] == "amanhã"
    resumo = ServicoClima.resumo(dados, 2)
    assert resumo.startswith("Agora em Uberaba faz 27 graus, com predominantemente limpo.")
    assert "sensação térmica é de 31" in resumo
    assert "Amanhã: chuva moderada, de 17 a 25 graus, chuva 80%." in resumo


def test_ferramenta_clima_salva_cidade_e_abre_holograma(app):
    app.clima = servico_clima()
    resultado = app.registro.executar("obter_clima", {"cidade": "Uberaba MG", "salvar_como_padrao": True}, app.contexto())
    assert resultado["ok"] and app.prefs.get("cidade_rotulo") == "Uberaba - MG"
    assert [h["tipo"] for h in app.hologramas.lista()] == ["clima"]
    sem_cidade = app.registro.executar("obter_clima", {}, app.contexto())
    assert sem_cidade["ok"] and len(sem_cidade["previsao"]) == 7


RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>Banco Central mantém juros - g1</title><link>https://news.google.com/a</link>
<pubDate>Fri, 09 Oct 2026 15:00:00 GMT</pubDate><source url="https://g1.globo.com">g1</source></item>
<item><title>Nova IA brasileira é lançada - Folha</title><link>https://news.google.com/b</link>
<pubDate>Fri, 09 Oct 2026 12:00:00 GMT</pubDate><source url="https://folha.uol.com.br">Folha</source></item>
</channel></rss>"""


def test_rss():
    itens = interpretar_rss(RSS)
    assert itens[0]["titulo"] == "Banco Central mantém juros" and itens[0]["fonte"] == "g1"
    assert itens[1]["titulo"] == "Nova IA brasileira é lançada"


def test_lembrete_dispara_e_repete(app):
    agora = datetime.now()
    lembrete = app.lembretes.criar("tomar água", agora - timedelta(seconds=5), "nao", False)
    diario = app.lembretes.criar("remédio", agora - timedelta(seconds=5), "diario", False)
    app.lembretes.iniciar()
    for _ in range(40):
        if len(app.fala.falas) >= 2:
            break
        time.sleep(0.1)
    app.lembretes.parar()
    assert any("tomar água" in f for f in app.fala.falas)
    ativos = {l["id"]: l for l in app.lembretes.listar()}
    assert lembrete["id"] not in ativos  # não repete: some
    assert datetime.fromisoformat(ativos[diario["id"]]["quando"]) > agora  # repete: vai para amanhã


def test_proxima_ocorrencia_dias_uteis():
    sexta = datetime(2026, 10, 9, 7, 0)
    assert proxima_ocorrencia(sexta, "dias_uteis", sexta) == datetime(2026, 10, 12, 7, 0)
    assert proxima_ocorrencia(sexta, "semanal", sexta) == datetime(2026, 10, 16, 7, 0)


def test_ferramenta_criar_lembrete(app):
    r = app.registro.executar("criar_lembrete", {"texto": "ligar para o João", "quando": "daqui a 20 minutos"}, app.contexto())
    assert r["ok"] and r["resumo"] == "Lembrete criado para daqui a 20 minutos."
    r = app.registro.executar("criar_lembrete", {"texto": "x", "quando": "num dia qualquer"}, app.contexto())
    assert not r["ok"]
    r = app.registro.executar("gerenciar_lembretes", {"acao": "cancelar", "alvo": "joão"}, app.contexto())
    assert r["ok"] and app.lembretes.listar() == []


def test_rotinas_do_yaml(app):
    nomes = {r.nome for r in app.rotinas.listar()}
    assert {"modo trabalho", "modo jogo", "bom dia", "boa noite", "modo foco"} <= nomes
    assert app.rotinas.encontrar_por_frase("hora de trabalhar").nome == "modo trabalho"
    assert app.rotinas.encontrar_por_frase("ativa modo jogo").nome == "modo jogo"
    assert app.rotinas.obter("jogo").nome == "modo jogo"


def test_rotina_criada_pela_ia_nao_executa_comandos(app):
    nova = app.rotinas.criar("modo estudo", [{"acao": "abrir", "valor": "Notion"},
                                             {"acao": "executar", "valor": "del C:\\tudo"},
                                             {"acao": "volume", "valor": "25"}], horario="20:00", dias=["seg", "qua"])
    assert [next(iter(p)) for p in nova.passos] == ["abrir", "volume"]
    assert nova.criada_pela_ia and nova.dias == [0, 2]
    assert app.rotinas.apagar("modo estudo")
    assert not app.rotinas.apagar("modo jogo")  # rotinas do arquivo do usuário não são apagadas pela IA


def test_horario_sem_aspas_no_yaml(app, tmp_path):
    (tmp_path / "config" / "rotinas.yaml").write_text(
        "rotinas:\n  cedo:\n    horario: 07:30\n    passos:\n      - falar: oi\n", encoding="utf-8")
    app.rotinas.recarregar()
    assert app.rotinas.obter("cedo").horario == "07:30"


def test_executar_rotina_em_sequencia(app, monkeypatch):
    abertos = []
    monkeypatch.setattr(app.apps, "abrir", lambda alvo: (abertos.append(alvo), (True, "ok"))[1])
    monkeypatch.setattr("sexta.habilidades.windows.definir_volume", lambda v: v)
    monkeypatch.setattr("sexta.habilidades.web.tocar_youtube", lambda b: (True, "ok"))
    rotina = app.rotinas.obter("modo trabalho")
    app.rotinas._executar(rotina, app.contexto())
    assert abertos == ["Visual Studio Code", "gmail"]
    assert app.fala.falas[0] == "Preparando seu ambiente de trabalho."


def test_apps_resolver(app):
    assert app.apps.resolver("youtube").valor == "https://www.youtube.com"
    assert app.apps.resolver("github.com").tipo == "url"
    assert app.apps.resolver("a pasta downloads").tipo == "pasta"
    assert app.apps.resolver("calculadora").valor == "calc"
    assert app.apps.resolver("meu site").valor == "https://exemplo.com"
    assert app.apps.resolver("programa que não existe") is None


def test_hologramas_unicos_e_texto(app):
    eventos = []
    app.barramento.ouvir(lambda e: eventos.append(e["tipo"]))
    app.registro.executar("holograma", {"acao": "mostrar", "tipo": "sistema"}, app.contexto())
    app.registro.executar("holograma", {"acao": "mostrar", "tipo": "sistema"}, app.contexto())
    app.registro.executar("holograma", {"acao": "mostrar", "tipo": "texto", "titulo": "Compras", "conteudo": "pão"}, app.contexto())
    tipos = [h["tipo"] for h in app.hologramas.lista()]
    assert tipos == ["sistema", "texto"]
    assert eventos.count("holograma.abrir") == 2 and eventos.count("holograma.atualizar") == 1
    app.registro.executar("holograma", {"acao": "fechar_todos"}, app.contexto())
    assert app.hologramas.lista() == []


def test_desligar_exige_confirmacao(app):
    r = app.registro.executar("computador", {"acao": "desligar"}, app.contexto())
    assert not r["ok"] and "confirma" in r["resumo"]


def test_memoria(app):
    app.registro.executar("memoria", {"acao": "lembrar", "fato": "Gosta de café sem açúcar"}, app.contexto())
    assert "café" in app.agente._sistema(app.contexto())
    r = app.registro.executar("memoria", {"acao": "esquecer", "fato": "café"}, app.contexto())
    assert r["ok"] and app.memoria.listar() == []


def test_parametros_convertidos(app, monkeypatch):
    pedidos = []

    def buscar(assunto, categoria, quantidade):
        pedidos.append((assunto, categoria, quantidade))
        return [{"titulo": "Manchete", "fonte": "g1", "link": "", "quando": "agora"}]

    monkeypatch.setattr(app.noticias, "buscar", buscar)
    # "três" não vira número: o parâmetro é descartado e vale o padrão (5)
    r = app.registro.executar("obter_noticias", {"quantidade": "três", "categoria": "Tecnologia"}, app.contexto())
    assert r["ok"] and pedidos == [(None, "tecnologia", 8)]
    r = app.registro.executar("obter_noticias", {"quantidade": "2", "categoria": "categoria inventada"}, app.contexto())
    assert pedidos[-1] == (None, None, 8) and len(r["manchetes"]) == 1
