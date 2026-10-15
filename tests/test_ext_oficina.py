"""Oficina 3D e visualizador de música: busca do modelo, rota com código opaco, comandos, atalhos e espectro."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sexta.cerebro.ferramentas import Contexto
from sexta.extensoes import oficina as mod
from sexta.habilidades.arquivos import Arquivo
from sexta.util.texto import normalizar


class ArquivosFalsos:
    def __init__(self, caminhos: list[Path]) -> None:
        self.caminhos = caminhos
        self.consultas: list[tuple[str, str | None]] = []

    def buscar(self, consulta, tipo=None, limite=5):
        self.consultas.append((consulta, tipo))
        termos = consulta.split()
        achados = [p for p in self.caminhos if all(t in normalizar(p.stem) for t in termos)
                   and (tipo != "modelo 3d" or p.suffix.lower() in mod.FORMATOS)]
        return [Arquivo(str(p), normalizar(p.stem), p.suffix.lower(), 0.0, p.stat().st_size) for p in achados][:limite]


@pytest.fixture
def modelos(tmp_path):
    pasta = tmp_path / "Modelos"
    pasta.mkdir()
    stl = pasta / "Capacete Mark 3.stl"
    stl.write_bytes(b"solid capacete\nendsolid\n")
    glb = pasta / "capacete.glb"
    glb.write_bytes(b"glTF" + b"\0" * 16)
    gltf = pasta / "turbina.gltf"
    gltf.write_text('{"asset": {"version": "2.0"}, "buffers": [{"uri": "turbina.bin"}]}', encoding="utf-8")
    (pasta / "turbina.bin").write_bytes(b"\1\2\3")
    (tmp_path / "segredo.bin").write_bytes(b"secreto")
    return pasta


@pytest.fixture
def oficina(app, modelos):
    app.arquivos = ArquivosFalsos(sorted(modelos.iterdir()))
    return app.oficina


def ctx(app):
    return app.contexto("texto")


def executar(app, nome, args):
    return app.registro.executar(nome, args, ctx(app))


def test_extensao_declarada(app):
    from sexta import eventos
    from sexta.habilidades import hologramas, rotinas

    assert {"oficina", "visualizador"} <= set(hologramas.TIPOS)
    assert "musica.espectro" in eventos.TIPOS_ALTA_FREQUENCIA
    assert "visualizador" in rotinas.ACOES_EXTRAS and "visualizador" in rotinas.ACOES_SEGURAS
    assert {"oficina", "visualizador"} <= set(app.registro.nomes()) if hasattr(app.registro, "nomes") else True


def test_limpar_consulta():
    assert mod.limpar_consulta("o modelo 3d do capacete") == ("capacete", "")
    assert mod.limpar_consulta("capacete.glb") == ("capacete", "glb")
    assert mod.limpar_consulta("stl") == ("stl", "")


def test_abrir_modelo_publica_holograma(app, oficina):
    r = executar(app, "oficina", {"acao": "abrir", "modelo": "modelo do capacete"})
    assert r["ok"] and "na oficina" in r["resumo"]
    holo = next(h for h in app.hologramas.lista() if h["tipo"] == "oficina")
    dados = holo["dados"]
    assert dados["formato"] in ("stl", "glb") and dados["url"] == f"/api/oficina/arquivo/{dados['id']}"
    assert "/" not in dados["id"] and "Modelos" not in dados["url"]
    assert app.arquivos.consultas[-1] == ("capacete", "modelo 3d")


def test_abrir_prefere_extensao_pedida(app, oficina):
    r = executar(app, "oficina", {"acao": "abrir", "modelo": "capacete.glb"})
    assert r["ok"] and oficina.atual["nome"] == "capacete.glb" and oficina.atual["formato"] == "glb"


def test_abrir_por_caminho_e_erros(app, oficina, modelos, tmp_path):
    r = executar(app, "oficina", {"acao": "abrir", "modelo": str(modelos / "turbina.gltf")})
    assert r["ok"] and oficina.atual["formato"] == "gltf"
    r = executar(app, "oficina", {"acao": "abrir", "modelo": str(tmp_path / "segredo.bin")})
    assert not r["ok"] and "não é um modelo 3D" in r["resumo"]
    r = executar(app, "oficina", {"acao": "abrir", "modelo": "foguete"})
    assert not r["ok"] and "Não encontrei" in r["resumo"]


def test_limite_de_tamanho(app, oficina, modelos, monkeypatch):
    monkeypatch.setattr(mod, "MAX_BYTES", 10)
    r = executar(app, "oficina", {"acao": "abrir", "modelo": str(modelos / "Capacete Mark 3.stl")})
    assert not r["ok"] and "limite" in r["resumo"]


def test_comandos_e_uma_peca(app, oficina):
    eventos = []
    app.barramento.ouvir(lambda e: eventos.append(e))
    assert executar(app, "oficina", {"acao": "explodir"})["resumo"] == mod.SEM_OFICINA
    executar(app, "oficina", {"acao": "abrir", "modelo": "turbina"})
    r = executar(app, "oficina", {"acao": "explodir"})
    assert r["ok"] and r["resumo"] == "Explodindo as peças.", r
    comando = [e for e in eventos if e["tipo"] == "oficina.comando"][-1]
    assert comando["acao"] == "explodir" and comando["id"] == oficina.atual["id"]
    oficina.pecas[oficina.atual["id"]] = 1
    assert executar(app, "oficina", {"acao": "explodir"})["resumo"] == mod.UMA_PECA
    assert executar(app, "oficina", {"acao": "girar"})["resumo"] == "Girando o modelo."
    assert executar(app, "oficina", {"acao": "fechar"})["resumo"] == "Oficina fechada."
    assert not app.hologramas.aberto("oficina")


def test_codigos_limitados(app, oficina, modelos, monkeypatch):
    monkeypatch.setattr(mod, "MAX_CODIGOS", 2)
    a = oficina.liberar(modelos / "a.stl")
    assert oficina.liberar(modelos / "a.stl") == a
    oficina.liberar(modelos / "b.stl")
    oficina.liberar(modelos / "c.stl")
    assert oficina.caminho(a) is None


# ---------------------------------------------------------------- atalhos

@pytest.mark.parametrize(("frase", "esperado"), [
    ("abre o modelo do capacete na oficina", ("capacete", True)),
    ("abre o capacete stl", ("capacete stl", True)),
    ("mostra o modelo 3d da turbina", ("turbina", True)),
    ("abre a oficina", ("", True)),
    ("abre o modelo do contrato", ("contrato", False)),
    ("abre o spotify", None),
    ("mostra o clima", None),
])
def test_interpretar_abrir(frase, esperado):
    assert mod.interpretar_abrir(normalizar(frase)) == esperado


def plano(app, frase):
    from sexta.cerebro import atalhos

    return atalhos.tentar(frase, ctx(app))


def test_atalhos_oficina(app, oficina):
    assert plano(app, "Sexta-Feira, abre o capacete.stl") == "Abrindo Capacete Mark 3.stl na oficina."
    assert plano(app, "explode as peças") == "Explodindo as peças."
    assert plano(app, "junta as peças") == "Juntando as peças."
    assert plano(app, "para de girar") == "Rotação parada."
    assert plano(app, "gira o modelo") == "Girando o modelo."
    assert plano(app, "fecha a oficina") == "Oficina fechada."
    # "modelo" que não é 3D fica para os outros comandos
    assert mod.atalho(normalizar("abre o modelo do contrato"), ctx(app), lambda *a, **k: None, None) is None
    assert plano(app, "abre o modelo do capacete") == "Abrindo Capacete Mark 3.stl na oficina."


def test_atalhos_visualizador(app):
    assert plano(app, "liga o visualizador") .startswith("Visualizador")
    assert app.hologramas.aberto("visualizador")
    assert plano(app, "desliga o visualizador de música") == "Visualizador desligado."
    assert not app.hologramas.aberto("visualizador")
    # as frases do protocolo festa não são capturadas pelos atalhos da oficina
    for frase in ("modo festa", "protocolo festa", "bora festa"):
        assert mod.atalho(normalizar(frase), ctx(app), lambda *a, **k: "x", None) is None


def test_acao_de_protocolo(app):
    from sexta.habilidades import rotinas

    rotinas.ACOES_EXTRAS["visualizador"](app, "ligar", ctx(app), {})
    assert app.hologramas.aberto("visualizador")
    rotinas.ACOES_EXTRAS["visualizador"](app, "desligar", ctx(app), {})
    assert not app.hologramas.aberto("visualizador")
    rotinas.ACOES_EXTRAS["visualizador"](app, True, ctx(app), {})
    assert app.hologramas.aberto("visualizador")


# ---------------------------------------------------------------- rotas

@pytest.fixture
def api(app):
    from sexta.servidor import criar_api

    with TestClient(criar_api(app), base_url="http://127.0.0.1:8765") as c:
        c.headers["Authorization"] = f"Bearer {app.acesso.token_pc}"
        yield c


def test_rota_arquivo(app, oficina, api, modelos):
    executar(app, "oficina", {"acao": "abrir", "modelo": str(modelos / "Capacete Mark 3.stl")})
    url = oficina.atual["url"]
    assert api.get(url, headers={"Authorization": ""}).status_code == 401
    r = api.get(url)
    assert r.status_code == 200 and r.content.startswith(b"solid") and r.headers["content-type"] == "model/stl"
    assert api.get("/api/oficina/arquivo/naoexiste").status_code == 404
    assert api.get("/api/oficina/arquivo/..%2F..%2Fsegredo.bin").status_code == 404


def test_rota_recursos_gltf(app, oficina, api, modelos):
    executar(app, "oficina", {"acao": "abrir", "modelo": "turbina"})
    url = oficina.atual["url"]
    assert api.get(f"{url}/turbina.bin").content == b"\1\2\3"
    assert api.get(f"{url}/../segredo.bin").status_code == 404
    assert api.get(f"{url}/..%2Fsegredo.bin").status_code == 404
    assert oficina.recurso(oficina.atual["id"], "../segredo.bin") is None
    assert oficina.recurso(oficina.atual["id"], "turbina.gltf") is None  # só buffers e imagens


def test_rota_pecas(app, oficina, api):
    executar(app, "oficina", {"acao": "abrir", "modelo": "turbina"})
    codigo = oficina.atual["id"]
    assert api.post("/api/oficina/pecas", json={"id": codigo, "pecas": 1}).json() == {"ok": True}
    assert oficina.pecas[codigo] == 1
    assert api.post("/api/oficina/pecas", json={"id": "x", "pecas": 1}).status_code == 404
    assert api.post("/api/oficina/pecas", json={"id": codigo, "pecas": "muitas"}).status_code == 400


# ---------------------------------------------------------------- espectro

def seno(freq: float, n: int, amp: float = 0.5, taxa: int = 44100, inicio: int = 0) -> np.ndarray:
    t = (np.arange(n) + inicio) / taxa
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_analisador_bandas():
    a = mod.Analisador()
    assert len(a.limites) == 32 and all(ini < fim for ini, fim in a.limites)
    assert all(a.limites[i][1] <= a.limites[i + 1][0] for i in range(31))
    for i in range(20):
        r = a.processar(np.stack([seno(60, 1764, inicio=i * 1764)] * 2, axis=1))
    assert len(r["bandas"]) == 32 and all(0 <= v <= 1 for v in r["bandas"])
    assert r["grave"] > 0.3 and r["nivel"] > 0.3
    assert int(np.argmax(r["bandas"])) < 6
    b = mod.Analisador()
    for i in range(20):
        r = b.processar(seno(5000, 1764, inicio=i * 1764))
    assert int(np.argmax(r["bandas"])) > 20 and r["grave"] < 0.3


def test_analisador_silencio_e_decaimento():
    a = mod.Analisador()
    for i in range(10):
        a.processar(seno(440, 1764, inicio=i * 1764))
    alto = max(a.processar(seno(440, 1764))["bandas"])
    for _ in range(40):
        r = a.processar(np.zeros(1764, dtype=np.float32))
    assert max(r["bandas"]) < alto * 0.05 and r["nivel"] < 0.05


# ---------------------------------------------------------------- captura

def test_captura_indisponivel_avisa_uma_vez(app, monkeypatch):
    eventos = []
    app.barramento.ouvir(lambda e: eventos.append(e))
    monkeypatch.setattr(mod.windows, "WINDOWS", False)
    vis = app.visualizador
    assert "Windows" in vis.motivo_indisponivel()
    app.hologramas.mostrar("visualizador")
    holo = next(h for h in app.hologramas.lista() if h["tipo"] == "visualizador")
    assert "Windows" in holo["dados"]["motivo"]
    vis.iniciar()
    try:
        prazo = time.time() + 3
        while time.time() < prazo and not any(e["tipo"] == "musica.estado" for e in eventos):
            time.sleep(0.05)
        estados = [e for e in eventos if e["tipo"] == "musica.estado"]
        assert len(estados) == 1 and not estados[0]["ativo"] and "Windows" in estados[0]["motivo"]
    finally:
        vis.encerrar()


def test_captura_com_soundcard_falso(app, monkeypatch):
    import sys
    import types

    blocos = {"n": 0, "fechado": False}

    class Gravador:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            blocos["fechado"] = True

        def record(self, numframes):
            blocos["n"] += 1
            time.sleep(0.005)
            return np.stack([seno(100, numframes, inicio=blocos["n"] * numframes)] * 2, axis=1)

    class Microfone:
        def recorder(self, samplerate, blocksize):
            assert samplerate == 44100 and blocksize == 1764
            return Gravador()

    falso = types.ModuleType("soundcard")
    falso.default_speaker = lambda: types.SimpleNamespace(name="Alto-falantes")
    falso.get_microphone = lambda id, include_loopback: Microfone() if include_loopback and id == "Alto-falantes" else None
    monkeypatch.setitem(sys.modules, "soundcard", falso)
    monkeypatch.setattr(mod.windows, "WINDOWS", True)
    monkeypatch.setattr(mod, "_iniciar_com", lambda: False)
    espectros = []
    app.barramento.ouvir(lambda e: e["tipo"] == "musica.estado" and espectros.append(e))
    original = app.barramento.publicar

    def publicar(tipo, para=None, **dados):
        if tipo == "musica.espectro":
            espectros.append({"tipo": tipo, **dados})
        return original(tipo, para, **dados)

    monkeypatch.setattr(app.barramento, "publicar", publicar)
    vis = app.visualizador
    vis.iniciar()
    try:
        assert not any(e["tipo"] == "musica.espectro" for e in espectros)  # fechado: não capta
        app.hologramas.mostrar("visualizador")
        prazo = time.time() + 5
        while time.time() < prazo and sum(e["tipo"] == "musica.espectro" for e in espectros) < 5:
            time.sleep(0.05)
        quadros = [e for e in espectros if e["tipo"] == "musica.espectro"]
        assert len(quadros) >= 5 and len(quadros[-1]["bandas"]) == 32 and vis.ativo
        app.hologramas.fechar(tipo="visualizador")
        prazo = time.time() + 3
        while time.time() < prazo and not blocos["fechado"]:
            time.sleep(0.05)
        assert blocos["fechado"] and not vis.ativo
    finally:
        vis.encerrar()


def test_diagnostico(app, monkeypatch):
    monkeypatch.setattr(mod.windows, "WINDOWS", False)
    item = mod.diagnostico(app)[0]
    assert item["nome"] == "Visualizador de música" and item["ok"]
