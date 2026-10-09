"""Fase 3: central de notícias (sem rede: feeds simulados)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from sexta.habilidades.jornal import Jornal, agrupar, extrair_texto, interpretar_feed

AGORA = datetime.now(timezone.utc)


def rss(itens: list[tuple[str, str]], fonte: str = "") -> bytes:
    corpo = "".join(
        f"<item><title>{t}</title><link>{l}</link><description>&lt;p&gt;Resumo de {t}&lt;/p&gt;</description>"
        f"<pubDate>{format_datetime(AGORA - timedelta(hours=1))}</pubDate>"
        + (f"<source url='x'>{fonte}</source>" if fonte else "") + "</item>" for t, l in itens)
    return f"<?xml version='1.0'?><rss><channel>{corpo}</channel></rss>".encode()


ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Nvidia anuncia a RTX 6090 com 48 GB de memoria</title><link rel="alternate" href="https://verge/rtx"/>
<published>2026-10-09T10:00:00Z</published><summary>Placa nova.</summary></entry></feed>"""


def test_rss_e_atom():
    itens = interpretar_feed(rss([("Inflação desacelera em setembro - Folha", "https://a")], "Folha"), "")
    assert itens[0]["titulo"] == "Inflação desacelera em setembro" and itens[0]["fonte"] == "Folha"
    assert itens[0]["resumo"] == "Resumo de Inflação desacelera em setembro - Folha"
    atom = interpretar_feed(ATOM, "The Verge")
    assert atom[0]["link"] == "https://verge/rtx" and atom[0]["publicado"].year == 2026


def test_agrupar_junta_a_mesma_noticia():
    base = {"publicado": AGORA, "resumo": ""}
    itens = [
        {**base, "titulo": "Nvidia anuncia RTX 6090 com 48 GB de memória", "fonte": "Tecnoblog", "link": "1"},
        {**base, "titulo": "RTX 6090: Nvidia anuncia placa com 48 GB", "fonte": "Canaltech", "link": "2"},
        {**base, "titulo": "Governo anuncia novo programa de habitação", "fonte": "g1", "link": "3"},
    ]
    grupos = agrupar(itens)
    assert len(grupos) == 2
    assert grupos[0]["fontes"] == ["Tecnoblog", "Canaltech"]  # 2 fontes: mais relevante


def test_extrair_texto():
    pagina = "<html><nav><p>Menu menu menu menu menu menu menu menu menu menu menu menu</p></nav>" \
             "<article><p>" + "Primeiro parágrafo da matéria com bastante conteúdo útil. " * 2 + "</p>" \
             "<p>curto</p><script>var x = '<p>não</p>'</script></article></html>"
    assert extrair_texto(pagina).startswith("Primeiro parágrafo") and "Menu" not in extrair_texto(pagina)


@pytest.fixture
def jornal(app, tmp_path):
    respostas = {"tecnoblog": rss([("Nvidia anuncia RTX 6090 com 48 GB de memória", "https://tb/rtx")]),
                 "canaltech": rss([("RTX 6090: Nvidia anuncia placa com 48 GB", "https://ct/rtx")]),
                 "google": rss([("Câmara aprova reforma do setor elétrico - g1", "https://g1/x")], "g1")}

    def responder(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for chave, corpo in respostas.items():
            if chave in url:
                return httpx.Response(200, content=corpo)
        return httpx.Response(404)

    config = tmp_path / "noticias.yaml"
    config.write_text("fontes:\n  brasil:\n    - Google: google:brasil\n  tecnologia:\n"
                      "    - Tecnoblog: https://tecnoblog.net/feed/\n    - Canaltech: https://canaltech.com.br/rss/\n",
                      encoding="utf-8")
    j = Jornal(app, config, app.cfg.dados, http=httpx.Client(transport=httpx.MockTransport(responder)))
    app.jornal = j
    j._respostas = respostas
    return j


def test_abas_e_salvas(jornal):
    dados = jornal.dados_holograma()
    tec = dados["abas"]["tecnologia"]
    assert len(tec) == 1 and tec[0]["fontes"] == ["Tecnoblog", "Canaltech"]
    assert dados["abas"]["brasil"][0]["titulo"] == "Câmara aprova reforma do setor elétrico"
    item = jornal.por_id(tec[0]["id"])
    assert jornal.salvar(item) and not jornal.salvar(item)
    assert jornal.dados_holograma("salvas")["abas"]["salvas"][0]["titulo"].startswith("Nvidia")
    assert jornal.remover_salva(tec[0]["id"]) and jornal.salvas() == []


def test_tema_avisa_so_o_que_e_novo(jornal, app):
    jornal._respostas["google"] = rss([("Nvidia confirma RTX 60 para janeiro - Tecmundo", "https://tm/1")], "Tecmundo")
    assert jornal.adicionar_tema("RTX 60")
    assert jornal.verificar_temas() == []  # o que já tinha saído não gera alerta
    jornal._respostas["google"] = rss([("Nvidia confirma RTX 60 para janeiro - Tecmundo", "https://tm/1"),
                                       ("Preço da RTX 60 vaza em loja - Adrenaline", "https://ad/2")], "x")
    jornal._cache.clear()
    novidades = jornal.verificar_temas()
    assert [i["link"] for _, i in novidades] == ["https://ad/2"]
    eventos = []
    app.barramento.ouvir(lambda e: eventos.append(e))
    jornal._avisar(novidades)
    assert "saiu notícia sobre RTX 60" in app.fala.tudo()
    assert any(e["tipo"] == "notificacao" for e in eventos)


def test_briefing_sem_ia(app, jornal, monkeypatch):
    monkeypatch.setattr(app.agente, "completar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sem IA")))
    texto = app.briefing()
    assert "No Brasil: Câmara aprova reforma do setor elétrico" in texto
    assert "Em tecnologia: Nvidia anuncia RTX 6090" in texto
    assert any(h["tipo"] == "jornal" for h in app.hologramas.lista())


def test_briefing_com_ia_usa_o_roteiro(app, jornal, monkeypatch):
    pedidos = []
    monkeypatch.setattr(app.agente, "completar", lambda sistema, texto, **k: pedidos.append(texto) or "Bom dia, chefe. Roteiro.")
    assert app.briefing() == "Bom dia, chefe. Roteiro."
    assert "RTX 6090" in pedidos[0] and "230 palavras" in __import__("sexta.app", fromlist=["x"]).BRIEFING_SISTEMA


@pytest.mark.parametrize("frase,args", [
    ("abre o jornal", {"acao": "mostrar"}),
    ("me avisa quando sair notícia de RTX 60", {"acao": "adicionar_tema", "tema": "rtx 60"}),
    ("para de me avisar sobre rtx 60", {"acao": "remover_tema", "tema": "rtx 60"}),
    ("lê a segunda notícia de tecnologia", {"acao": "ler", "aba": "tecnologia", "numero": 2}),
    ("salva a primeira", {"acao": "salvar", "aba": "destaques", "numero": 1}),
])
def test_atalhos_jornal(app, monkeypatch, frase, args):
    from sexta.cerebro.agente import Agente
    from test_agente import OllamaFalso, cliente

    chamadas = []
    monkeypatch.setattr(app.registro, "executar", lambda n, a, ctx, **_: chamadas.append((n, a)) or {"ok": True, "resumo": "ok"})
    app.agente = Agente(app, cliente(OllamaFalso([])))
    assert app.agente.processar(frase)["caminho"] == "atalho"
    assert chamadas == [("jornal", args)]


def test_agendar_briefing_vira_protocolo(app, jornal):
    r = app.registro.executar("jornal", {"acao": "agendar_briefing", "horario": "7h30", "dias": ["uteis"]}, app.contexto())
    assert r["resumo"] == "Briefing agendado para as 07:30."
    protocolo = app.rotinas.obter("briefing matinal")
    assert protocolo.horario == "07:30" and protocolo.dias == [0, 1, 2, 3, 4]
    assert protocolo.passos == [{"briefing": "true"}]
