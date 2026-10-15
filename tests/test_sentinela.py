"""Protocolo Sentinela, Casa Limpa e "Onde eu parei?": vigilância com câmera e rosto simulados, alertas,
fotos e rotas, limpeza de temporários, histórico de navegadores (SQLite falsos), sessões e atalhos.
Sem câmera, sem rede e sem Windows."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sexta.cerebro.ferramentas import CONFIRMAR, LIVRE, ROSTO
from sexta.extensoes import sentinela as mod


class MemoriaFalsa:
    def __init__(self) -> None:
        self.aprendido: list[tuple] = []

    def aprender(self, tipo, texto, etiquetas=(), origem=""):
        self.aprendido.append((tipo, texto, list(etiquetas), origem))


QUADRO = np.zeros((48, 64, 3), dtype=np.uint8)


def preparar(app, monkeypatch, roteiro: list[tuple[bool, bool]], cadastrado: bool = True):
    """Sentinela com câmera falsa: cada quadro devolve o próximo (tem_rosto, dono) do roteiro."""
    s: mod.Sentinela = app.sentinela
    fila = list(roteiro)
    monkeypatch.setattr(s, "_ler_quadros", lambda n: [QUADRO] * min(n, len(fila)))
    monkeypatch.setattr(s, "_avaliar", lambda q: fila.pop(0) if fila else (False, False))
    monkeypatch.setattr(s, "cadastrado", lambda: cadastrado)
    monkeypatch.setattr(mod.windows, "bloquear_windows", lambda: None)
    notificacoes: list[tuple] = []
    monkeypatch.setattr("sexta.habilidades.notificacoes.notificar",
                        lambda app_, texto, titulo="", prioridade="": notificacoes.append((texto, titulo)))
    app.memoria = MemoriaFalsa()
    s.pasta = app.cfg.dados / "sentinela"
    return s, notificacoes


def test_declaracoes_e_registro(app):
    from sexta.habilidades import hologramas, rotinas

    assert {"sentinela", "retomar"} <= set(hologramas.TIPOS)
    assert {"fechar_tudo", "limpar_temporarios"} <= set(rotinas.ACOES_EXTRAS)
    assert {"sentinela", "casa_limpa", "retomar"} <= set(app.registro.nomes())
    assert app.prefs.get("sentinela_auto") is False and app.prefs.get("sentinela_minutos") == 5
    ferramenta = app.registro.obter("sentinela")
    assert ferramenta.nivel_para({"acao": "desativar"}) == ROSTO and ferramenta.nivel_para({"acao": "ativar"}) == LIVRE
    assert app.registro.obter("casa_limpa").nivel == CONFIRMAR
    assert app.registro.obter("retomar").nivel_para({"acao": "reabrir"}) == CONFIRMAR


# ---------------------------------------------------------------- Sentinela

def test_armar_bloqueia_e_estranho_em_dois_quadros_vira_alerta_silencioso(app, monkeypatch):
    s, notificacoes = preparar(app, monkeypatch, [(True, False), (True, False), (True, False)])
    frase = s.armar()
    assert s.armado and frase.startswith("Protocolo Sentinela ativado")
    assert s.checar() == "intruso"
    fotos = s.fotos()
    assert len(fotos) == 1 and mod.nome_foto_valido(fotos[0]["nome"])
    assert (app.cfg.dados / "sentinela" / fotos[0]["nome"]).read_bytes()[:2] == b"\xff\xd8"  # JPEG
    texto, titulo = notificacoes[0]
    assert titulo == "Sentinela" and texto.startswith("Rosto desconhecido no PC às") and "salva no computador" in texto
    assert app.fala.falas == []  # nunca fala com um estranho na frente do PC
    assert any("Rosto desconhecido" in i["resumo"] and i["ferramenta"] == "sentinela" for i in app.atividades.listar())
    tipo, texto_memoria, etiquetas, origem = app.memoria.aprendido[-1]
    assert tipo == "conhecimento" and "sentinela" in etiquetas and origem == "sentinela" and ".jpg" not in texto_memoria
    historico = app.seguranca.historico()
    assert historico[0]["tipo"] == "sentinela" and historico[0]["risco"] == "alto"
    assert app.seguranca.resumo_historico()[0]["titulo"].startswith("Sentinela: rosto desconhecido")


def test_limite_de_um_alerta_a_cada_dois_minutos(app, monkeypatch):
    s, notificacoes = preparar(app, monkeypatch, [(True, False)] * 8)
    s.armar()
    assert s.checar() == "intruso"
    s.checar()
    assert len(notificacoes) == 1 and len(s.fotos()) == 1
    s._ultimo_alerta -= mod.ALERTA_INTERVALO_S + 1
    s.checar()
    assert len(notificacoes) == 2


def test_dono_reconhecido_desarma_e_cumprimenta(app, monkeypatch):
    s, notificacoes = preparar(app, monkeypatch, [(True, True), (True, True)])
    app.prefs.atualizar({"tratamento": "chefe"})
    s.armar()
    assert s.checar() == "dono"
    assert not s.armado and notificacoes == []
    assert app.fala.falas[-1].startswith("Bem-vindo de volta, chefe. Ninguém mexeu no PC.")


def test_um_quadro_parecido_nao_basta(app, monkeypatch):
    s, _ = preparar(app, monkeypatch, [(True, True), (False, False), (True, True), (False, False)])
    s.armar()
    s.checar()
    assert s.armado


def test_atividade_sem_o_dono_vira_alerta_e_com_o_dono_nao(app, monkeypatch):
    s, notificacoes = preparar(app, monkeypatch, [(False, False)] * 6)
    s.armar()
    assert s.checar(atividade=True) == "intruso"
    assert notificacoes[0][0].startswith("Alguém mexeu no PC")
    s2, notificacoes2 = preparar(app, monkeypatch, [(True, True), (False, False)] + [(False, False)] * 4)
    s2._ultimo_alerta = 0
    assert s2.checar(atividade=True) != "intruso"
    assert len(notificacoes2) == 0


def test_sem_cadastro_fotografa_quem_mexer(app, monkeypatch):
    s, notificacoes = preparar(app, monkeypatch, [(True, False)] * 6, cadastrado=False)
    assert "não está cadastrado" in s.armar()
    assert s.checar() == "rosto"  # sem cadastro, um rosto sozinho não é intruso (pode ser você)
    assert s.checar(atividade=True) == "intruso" and len(notificacoes) == 1


def test_atividade_so_conta_depois_da_carencia(app):
    s: mod.Sentinela = app.sentinela
    s.ocioso = lambda: 0.5
    s.armado, s.desde = True, time.time()
    assert not s._houve_atividade()
    s.desde -= mod.CARENCIA_S + 1
    assert s._houve_atividade()
    s.ocioso = lambda: None  # fora do Windows
    assert not s._houve_atividade()
    s.armado = False


def test_modo_automatico_arma_depois_de_duas_ausencias(app, monkeypatch):
    s, _ = preparar(app, monkeypatch, [(False, False)] * 4)
    s.ocioso = lambda: 6 * 60
    assert not s.ausente() and s.ausente()
    s.ocioso = lambda: 30
    assert not s.ausente() and s._ausente_seguidos == 0


def test_modo_automatico_descansa_a_camera_quando_ve_o_dono(app, monkeypatch):
    s, _ = preparar(app, monkeypatch, [(True, True)] * 4)
    s.ocioso = lambda: 10 * 60
    assert not s.ausente()
    monkeypatch.setattr(s, "_ler_quadros", lambda n: pytest.fail("não devia ligar a câmera"))
    assert not s.ausente()


def test_desativar_pede_rosto_e_status(app, monkeypatch):
    s, _ = preparar(app, monkeypatch, [])
    s.armar()
    ctx = app.contexto("texto")
    resultado = app.registro.executar("sentinela", {"acao": "desativar"}, ctx)
    assert resultado["pendente"] and s.armado
    resultado = app.registro.confirmar(ctx, app.verificar_para_acao)
    assert resultado["ok"] and not s.armado and resultado["resumo"].startswith("Protocolo Sentinela desativado")
    assert "desligado" in app.registro.executar("sentinela", {"acao": "status"}, ctx)["resumo"]


def test_nomes_de_foto(app):
    assert mod.nome_foto_valido("2026-10-15_14-32-05.jpg") and mod.nome_foto_valido("2026-10-15_14-32-05_1.jpg")
    for ruim in ("../sexta.db", "..\\x.jpg", "2026-10-15_14-32-05.png", "a.jpg", "", "2026-10-15_14-32-05.jpg/..",
                 "%2e%2e/2026-10-15_14-32-05.jpg"):
        assert not mod.nome_foto_valido(ruim)


@pytest.fixture
def api(app):
    from sexta.servidor import criar_api

    with TestClient(criar_api(app), base_url="http://127.0.0.1:8765") as c:
        c.headers["Authorization"] = f"Bearer {app.acesso.token_pc}"
        yield c


def test_rotas_das_fotos(app, api, monkeypatch):
    s, _ = preparar(app, monkeypatch, [(True, False)] * 2)
    s.armar()
    s.checar()
    nome = s.fotos()[0]["nome"]
    assert api.get("/api/sentinela/fotos", headers={"Authorization": ""}).status_code == 401
    assert api.get("/api/sentinela/fotos").json()["fotos"][0]["nome"] == nome
    foto = api.get(f"/api/sentinela/fotos/{nome}")
    assert foto.status_code == 200 and foto.headers["content-type"] == "image/jpeg"
    com_token = api.get(f"/api/sentinela/fotos/{nome}?token={app.acesso.token_pc}", headers={"Authorization": ""})
    assert com_token.status_code == 200
    (app.cfg.dados / "segredo.jpg").write_bytes(b"x")
    for ruim in ("..%2Fsegredo.jpg", "segredo.jpg", "..%5C..%5Csexta.db"):
        assert api.get(f"/api/sentinela/fotos/{ruim}").status_code == 404
    assert api.delete("/api/sentinela/fotos/nada.jpg").status_code == 404
    assert api.delete(f"/api/sentinela/fotos/{nome}").json()["fotos"] == []
    assert api.get("/api/sentinela/estado").json()["armado"] is True
    app.sessao.bloqueada = False
    assert "desativado" in api.post("/api/sentinela/desarmar").json()["texto"]


# ---------------------------------------------------------------- Casa Limpa

def _velho(caminho: Path, horas: float = 48) -> None:
    t = time.time() - horas * 3600
    os.utime(caminho, (t, t))


def test_limpar_temporarios(tmp_path):
    raiz = tmp_path / "AppData" / "Local" / "Temp"
    (raiz / "pasta_velha").mkdir(parents=True)
    velho = raiz / "velho.tmp"
    velho.write_bytes(b"x" * 2048)
    novo = raiz / "novo.tmp"
    novo.write_bytes(b"y" * 10)
    dentro = raiz / "pasta_velha" / "a.log"
    dentro.write_bytes(b"z" * 100)
    fora = tmp_path / "importante.txt"
    fora.write_text("não apague")
    _velho(velho)
    _velho(dentro)
    _velho(fora)
    if sys.platform != "win32":
        (raiz / "link").symlink_to(tmp_path)  # um link para fora: nunca seguir
    _velho(raiz / "pasta_velha")
    r = mod.limpar_temporarios(raiz)
    assert r["arquivos"] == 2 and r["bytes"] == 2148 and not r["recusado"]
    assert not velho.exists() and not dentro.exists() and novo.exists() and fora.exists()
    assert raiz.exists()


def test_limpar_temporarios_recusa_pastas_perigosas(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert mod.limpar_temporarios(tmp_path)["recusado"]
    assert mod.limpar_temporarios(Path("/"))["recusado"]
    assert mod.limpar_temporarios(tmp_path / "nao_existe")["recusado"]


def test_quem_pode_fechar():
    protegidos = {10}
    assert mod.pode_fechar("relatorio.docx - Word", "winword", 20, protegidos)
    assert not mod.pode_fechar("Sexta-Feira", "msedge", 20, protegidos)
    assert not mod.pode_fechar("Sexta-Feira — HUD", "chrome", 20, protegidos)
    assert not mod.pode_fechar("Pasta", "explorer", 20, protegidos)
    assert not mod.pode_fechar("x", "csrss", 20, protegidos)
    assert not mod.pode_fechar("Windows PowerShell", "windowsterminal", 10, protegidos)  # o terminal da Sexta-Feira


def test_frase_casa_limpa_e_bytes():
    assert mod.formatar_bytes(int(1.2 * 1024 ** 3)) == "1,2 GB" and mod.formatar_bytes(5 * 1024 ** 2) == "5 MB"
    frase = mod.frase_casa_limpa(7, 23, {"bytes": int(1.2 * 1024 ** 3)})
    assert frase == "Fechei 7 janelas, organizei 23 arquivos e liberei 1,2 GB de temporários."


def test_casa_limpa_pede_confirmacao_e_fora_do_windows_explica(app):
    ctx = app.contexto("voz")
    resultado = app.registro.executar("casa_limpa", {}, ctx)
    assert resultado["pendente"] and "organizar a pasta Downloads" in resultado["resumo"]
    resultado = app.registro.confirmar(ctx)
    assert not resultado["ok"] and "só funciona no Windows" in resultado["resumo"]


def test_casa_limpa_no_windows_simulado(app, monkeypatch):
    monkeypatch.setattr(mod.windows, "WINDOWS", True)
    monkeypatch.setattr(mod, "fechar_tudo", lambda: 3)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(mod, "limpar_temporarios", lambda: {"arquivos": 4, "bytes": 3 * 1024 ** 2})
    chamadas = []

    def executar(nome, args, ctx, **kw):
        chamadas.append((nome, args, ctx.confiavel))
        return {"ok": True, "resumo": "Organizei 12 arquivos: 8 em Imagens."}

    monkeypatch.setattr(app.registro, "executar", executar)
    r = mod.casa_limpa(app, app.contexto("voz"))
    assert r["resumo"] == "Fechei 3 janelas, organizei 12 arquivos e liberei 3 MB de temporários."
    assert chamadas == [("arquivos", {"acao": "organizar_downloads"}, True)]


# ---------------------------------------------------------------- Onde eu parei

def _chrome(caminho: Path, visitas: list[tuple[str, str, float]]) -> Path:
    db = sqlite3.connect(caminho)
    db.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, last_visit_time INTEGER)")
    db.executemany("INSERT INTO urls (url, title, last_visit_time) VALUES (?, ?, ?)",
                   [(u, t, int((q + mod.EPOCA_CHROME_S) * 1_000_000)) for u, t, q in visitas])
    db.commit()
    db.close()
    return caminho


def _firefox(caminho: Path, visitas: list[tuple[str, str, float]]) -> Path:
    db = sqlite3.connect(caminho)
    db.execute("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT, last_visit_date INTEGER)")
    db.executemany("INSERT INTO moz_places (url, title, last_visit_date) VALUES (?, ?, ?)",
                   [(u, t, int(q * 1_000_000)) for u, t, q in visitas])
    db.commit()
    db.close()
    return caminho


def test_abas_do_historico(tmp_path):
    agora = time.time()
    chrome = _chrome(tmp_path / "History", [
        ("https://github.com/eu/projeto-x", "projeto-x", agora - 60),
        ("https://github.com/eu/projeto-x#readme", "projeto-x", agora - 50),
        ("https://www.google.com/search?q=python", "python - Pesquisa", agora - 40),
        ("https://accounts.google.com/signin", "Login", agora - 30),
        ("http://127.0.0.1:8765/#t=abc", "Sexta-Feira", agora - 20),
        ("https://antigo.com/", "Antigo", agora - 5 * 3600),
    ])
    firefox = _firefox(tmp_path / "places.sqlite", [("https://docs.python.org/3/", "Python docs", agora - 10),
                                                    ("about:newtab", "", agora - 5)])
    abas = mod.abas_recentes(agora - 2 * 3600, [("chromium", chrome), ("firefox", firefox)])
    assert [a["url"] for a in abas] == ["https://docs.python.org/3/", "https://github.com/eu/projeto-x"]
    assert abas[1]["titulo"] == "projeto-x"


def test_no_maximo_oito_abas():
    visitas = [(f"https://site{i}.com/", f"Site {i}", 1000 + i) for i in range(20)]
    abas = mod.escolher_abas(visitas)
    assert len(abas) == 8 and abas[0]["url"] == "https://site19.com/"


SESSAO_A = {"apps": [{"exe": "code", "caminho": "C:/VS/Code.exe", "titulo": "main.py - projeto-x - Visual Studio Code",
                      "janelas": 1},
                     {"exe": "chrome", "caminho": "C:/Chrome/chrome.exe", "titulo": "GitHub", "janelas": 1}],
            "arquivos": [{"nome": "relatorio.docx", "caminho": "C:/D/relatorio.docx"}],
            "abas": [{"url": f"https://s{i}.com/", "titulo": str(i), "quando": 0} for i in range(5)]}


def test_resumo_falado():
    assert mod.resumo_sessao(SESSAO_A) == ("Você estava no VS Code em projeto-x, no Chrome com 5 abas e editando "
                                           "relatorio.docx. Quer que eu reabra?")
    assert mod.resumo_sessao({"apps": [], "arquivos": [], "abas": []}).startswith("Não anotei")


def test_sessoes_novas_depois_de_30_minutos_e_guarda_10(app):
    sessoes: mod.Sessoes = app.sessoes
    sessoes.coletar_apps = lambda: SESSAO_A["apps"]
    sessoes.coletar_arquivos = lambda desde: SESSAO_A["arquivos"]
    sessoes.coletar_abas = lambda desde: SESSAO_A["abas"]
    base = datetime(2026, 10, 15, 9, 0).timestamp()
    primeira = sessoes.instantaneo(base)
    assert sessoes.instantaneo(base + 20 * 60)["id"] == primeira["id"]
    segunda = sessoes.instantaneo(base + 20 * 60 + mod.NOVA_SESSAO_S)
    assert segunda["id"] != primeira["id"]
    # logo depois de voltar, "onde eu parei" mostra a sessão anterior
    assert sessoes.anterior(base + 20 * 60 + mod.NOVA_SESSAO_S + 60)["id"] == primeira["id"]
    assert sessoes.anterior(base + 20 * 60 + mod.NOVA_SESSAO_S + 25 * 60)["id"] == segunda["id"]
    for i in range(12):
        sessoes.instantaneo(base + (i + 2) * 2 * 3600)
    assert len(sessoes.listar()) == 10
    salvo = json.loads((app.cfg.dados / "sessoes.json").read_text(encoding="utf-8"))
    assert len(salvo) == 10 and salvo[-1]["apps"][0]["exe"] == "code"


def test_novo_dia_comeca_outra_sessao(app):
    sessoes: mod.Sessoes = app.sessoes
    sessoes.coletar_apps = lambda: SESSAO_A["apps"]
    sessoes.coletar_arquivos = sessoes.coletar_abas = lambda desde: []
    noite = datetime(2026, 10, 15, 23, 55).timestamp()
    a = sessoes.instantaneo(noite)
    b = sessoes.instantaneo(noite + 10 * 60)
    assert a["id"] != b["id"]


def test_passo_anota_ao_bloquear_e_a_cada_5_minutos(app):
    sessoes: mod.Sessoes = app.sessoes
    feitos = []
    sessoes.instantaneo = lambda agora=None: feitos.append(agora)
    sessoes.ocioso, sessoes.bloqueado = (lambda: 3.0), (lambda: False)
    sessoes.passo(1000.0)
    sessoes._ultimo_instantaneo = 1000.0
    sessoes.passo(1100.0)
    assert feitos == [1000.0]
    sessoes.bloqueado = lambda: True
    sessoes.passo(1150.0)
    sessoes.passo(1160.0)
    assert feitos == [1000.0, 1150.0]


def test_onde_eu_parei_mostra_e_sim_reabre(app, monkeypatch):
    sessoes: mod.Sessoes = app.sessoes
    sessoes.coletar_apps = lambda: SESSAO_A["apps"]
    sessoes.coletar_arquivos = lambda desde: SESSAO_A["arquivos"]
    sessoes.coletar_abas = lambda desde: SESSAO_A["abas"]
    sessao = sessoes.instantaneo(time.time() - 3 * 3600)
    reabertas = []
    monkeypatch.setattr(mod, "reabrir", lambda s, *a: reabertas.append(s["id"]) or
                        {"apps": 1, "arquivos": 1, "abas": 5, "ja_abertos": 1})
    ctx = app.contexto("voz")
    resultado = app.registro.executar("retomar", {"acao": "mostrar"}, ctx)
    assert resultado["resumo"].startswith("Você estava no VS Code") and app.hologramas.aberto("retomar")
    assert app.registro.pendente().nome == "retomar"
    resultado = app.registro.confirmar(ctx)
    assert resultado["resumo"] == "Reabri 1 programa, 1 arquivo e 5 páginas." and reabertas == [sessao["id"]]


def test_reabrir_api_usa_indices_da_sessao_salva(app, api, monkeypatch):
    sessoes: mod.Sessoes = app.sessoes
    sessoes.coletar_apps = lambda: SESSAO_A["apps"]
    sessoes.coletar_arquivos = lambda desde: SESSAO_A["arquivos"]
    sessoes.coletar_abas = lambda desde: SESSAO_A["abas"]
    sessao = sessoes.instantaneo(time.time() - 3 * 3600)
    chamadas = []
    monkeypatch.setattr(mod, "reabrir", lambda s, apps, arquivos, abas: chamadas.append((apps, arquivos, abas)) or
                        {"apps": 0, "arquivos": 0, "abas": 2, "ja_abertos": 0})
    r = api.post("/api/retomar/reabrir", json={"sessao": sessao["id"], "apps": [], "arquivos": ["C:/x.exe"],
                                               "abas": [0, 1, True]}).json()
    assert r["texto"] == "Reabri 2 páginas." and chamadas == [([], [], [0, 1])]
    assert api.post("/api/retomar/reabrir", json={"sessao": "nada"}).status_code == 404


def test_reabrir_fora_do_windows():
    with pytest.raises(mod.windows.NaoSuportado):
        mod.reabrir(SESSAO_A)


# ---------------------------------------------------------------- atalhos

@pytest.mark.parametrize("frase, ferramenta, args", [
    ("ativa o protocolo sentinela", "sentinela", {"acao": "ativar"}),
    ("Sexta-feira, protocolo sentinela", "sentinela", {"acao": "ativar"}),
    ("modo sentinela", "sentinela", {"acao": "ativar"}),
    ("desativa o sentinela", "sentinela", {"acao": "desativar"}),
    ("mostra as fotos do sentinela", "sentinela", {"acao": "mostrar"}),
    ("protocolo casa limpa", "casa_limpa", {}),
    ("casa limpa", "casa_limpa", {}),
    ("limpa a casa", "casa_limpa", {}),
    ("faz uma faxina no PC", "casa_limpa", {}),
    ("onde eu parei?", "retomar", {"acao": "mostrar"}),
    ("o que eu estava fazendo", "retomar", {"acao": "mostrar"}),
    ("retoma de onde eu parei", "retomar", {"acao": "mostrar"}),
])
def test_atalhos(app, frase, ferramenta, args):
    from sexta.util.texto import normalizar

    t = normalizar(frase.replace("Sexta-feira,", "")).strip()
    assert mod.atalho(t, app.contexto(), lambda n, a: (n, a), frase) == (ferramenta, args)


def test_frases_parecidas_nao_sao_capturadas(app):
    for frase in ("sentinela", "o que e um sentinela", "limpa a tela", "abre o spotify", "bloqueia o pc", "onde fica o banco"):
        assert mod.atalho(frase, app.contexto(), lambda n, a: (n, a), frase) is None


def test_diagnostico_e_holograma(app):
    itens = {i["nome"]: i for i in mod.diagnostico(app)}
    assert "Protocolo Sentinela" in itens and itens["Casa Limpa e Onde eu parei"]["detalhe"] == "só no Windows"
    assert mod.dados_holograma(app, "sentinela")["armado"] is False
    assert mod.dados_holograma(app, "retomar") == {"sessao": None}
