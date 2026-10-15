"""Extensão maos_livres: escuta pelo celular, comandos remotos e anúncios (sem áudio real nem Windows)."""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sexta.extensoes import maos_livres as ml

BASE = "http://127.0.0.1:8765"
WS = {"host": "127.0.0.1:8765", "origin": BASE}


class DetectorFalso:
    """Dispara quando recebe um bloco "marcado" (primeira amostra = 7777)."""

    def __init__(self) -> None:
        self.reinicios = 0

    def processar(self, bloco: bytes) -> bool:
        return np.frombuffer(bloco[:2], dtype=np.int16)[0] == 7777

    def reiniciar(self) -> None:
        self.reinicios += 1


def bloco(tipo: str) -> bytes:
    if tipo == "nome":
        a = np.zeros(ml.AMOSTRAS_BLOCO, np.int16)
        a[0] = 7777
    elif tipo == "fala":
        t = np.arange(ml.AMOSTRAS_BLOCO) / ml.TAXA
        a = (np.sin(2 * np.pi * 300 * t) * 8000).astype(np.int16)
    else:
        a = (np.random.default_rng(1).normal(0, 30, ml.AMOSTRAS_BLOCO)).astype(np.int16)
    return a.tobytes()


class Registrado:
    def __init__(self, id_=99, tipo="celular") -> None:
        self.id, self.tipo, self.nome = id_, tipo, "Pixel"


class Cliente:
    tipo, id, nome = "celular", "cel1", "Pixel"


def esperar(condicao, limite=5.0):
    fim = time.time() + limite
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def eventos(app):
    lista: list[dict] = []
    app.barramento.ouvir(lista.append)
    return lista


@pytest.fixture
def sessao(app, eventos):
    app.maos_livres.criar_detector = DetectorFalso
    reg = Registrado()
    ok, motivo = app.maos_livres.ligar(reg, Cliente())
    assert ok, motivo
    s = app.maos_livres.sessao(reg.id)
    s.limite = ml.LimiteTaxa(10**9, 10**6)  # o teste manda mais rápido que o tempo real
    yield s
    app.maos_livres.desligar(reg.id)


def falar(s: ml.SessaoCelular, *partes: tuple[str, int]) -> None:
    for tipo, n in partes:
        for _ in range(n):
            assert s.receber(bloco(tipo))


def tipos(eventos):
    return [e["tipo"] for e in eventos]


# ---------------------------------------------------------------- limites
def test_limite_de_taxa():
    lim = ml.LimiteTaxa(bytes_por_s=4000, quadros_por_s=2)
    assert lim.permitir(1000, agora=0.0) and lim.permitir(1000, agora=0.0)
    assert not lim.permitir(1000, agora=0.0)  # acabaram os quadros
    assert lim.permitir(1000, agora=1.0)
    assert not ml.LimiteTaxa().permitir(10**6)


def test_quadro_invalido_e_cliente_sem_sessao(app, sessao):
    assert not sessao.receber(b"\x00" * (ml.MAX_QUADRO + 2))
    assert not sessao.receber(b"\x00\x01\x02")  # tamanho ímpar
    assert not ml.receber_audio(app, Registrado(5), b"\x00" * 100)  # mãos livres desligado
    assert not ml.receber_audio(app, Registrado(99, "pc"), b"\x00" * 100)  # PC não manda áudio


# ---------------------------------------------------------------- linha de escuta
def test_pedido_completo_responde_so_para_o_celular(app, sessao, eventos, monkeypatch):
    ouvidos = []
    monkeypatch.setattr(app.transcritor, "transcrever", lambda audio, dica="": ouvidos.append(audio.size) or "Sexta-Feira, que horas são?")
    falar(sessao, ("ruido", 20), ("nome", 1), ("fala", 30), ("ruido", 40))
    assert esperar(lambda: "maos_livres.resposta" in tipos(eventos))
    resposta = next(e for e in eventos if e["tipo"] == "maos_livres.resposta")
    assert resposta["texto"].startswith("São ")
    assert resposta["transcricao"] == "que horas são?"
    assert resposta["audio"].startswith("/api/maos_livres/audio/")
    assert "maos_livres.ativado" in tipos(eventos)
    estados = [e["estado"] for e in eventos if e["tipo"] == "maos_livres.estado"]
    assert "gravando" in estados and "pensando" in estados and "falando" in estados
    assert ouvidos and ouvidos[0] > ml.AMOSTRAS_BLOCO * 30  # com a pré-rolagem
    conversa = [e for e in eventos if e["tipo"] == "conversa"]
    assert conversa and conversa[0]["canal"] == "celular"


def test_so_o_nome_pergunta_pois_nao_e_continua(app, sessao, eventos, monkeypatch):
    falas = iter(["Sexta-Feira", "que horas são"])
    monkeypatch.setattr(app.transcritor, "transcrever", lambda audio, dica="": next(falas))
    falar(sessao, ("ruido", 10), ("nome", 1), ("fala", 20), ("ruido", 40))
    assert esperar(lambda: any(e["tipo"] == "maos_livres.resposta" for e in eventos))
    primeira = next(e for e in eventos if e["tipo"] == "maos_livres.resposta")
    assert "?" in primeira["texto"]  # "Pois não?"
    sessao.definir_tocando(False)  # o celular terminou de tocar
    assert esperar(lambda: sessao.estado == "gravando")
    falar(sessao, ("fala", 20), ("ruido", 40))
    assert esperar(lambda: sum(e["tipo"] == "maos_livres.resposta" for e in eventos) >= 2)
    assert [e for e in eventos if e["tipo"] == "maos_livres.resposta"][1]["texto"].startswith("São ")


def test_bloqueada_exige_pin(app, sessao, eventos, monkeypatch):
    monkeypatch.setattr(app.transcritor, "transcrever", lambda audio, dica="": "que horas são")
    monkeypatch.setattr(app.acesso, "tem_pin", lambda: True)
    monkeypatch.setattr(app.rosto, "cadastrado", lambda: True)
    app.sessao.bloquear("teste")
    assert app.sessao.bloqueada
    processados = []
    monkeypatch.setattr(app.agente, "processar", lambda *a, **k: processados.append(a))
    falar(sessao, ("nome", 1), ("fala", 20), ("ruido", 40))
    assert esperar(lambda: "maos_livres.resposta" in tipos(eventos))
    resposta = next(e for e in eventos if e["tipo"] == "maos_livres.resposta")
    assert "PIN" in resposta["texto"] and not processados


def test_nome_durante_a_resposta_interrompe(app, sessao, eventos, monkeypatch):
    monkeypatch.setattr(app.transcritor, "transcrever", lambda audio, dica="": "que horas são")
    sessao.definir_tocando(True)
    sessao._tocando_desde -= 5  # já passou a carência
    falar(sessao, ("nome", 1), ("fala", 20), ("ruido", 40))
    assert esperar(lambda: "maos_livres.parar_audio" in tipos(eventos))
    assert esperar(lambda: "maos_livres.resposta" in tipos(eventos))


def test_sem_detector_explica(app):
    app.maos_livres.criar_detector = lambda: None
    ok, motivo = app.maos_livres.ligar(Registrado(7), Cliente())
    assert not ok and "ATIVACAO_MOTOR" in motivo

    def quebra():
        raise ImportError("No module named vosk")
    app.maos_livres.criar_detector = quebra
    ok, motivo = app.maos_livres.ligar(Registrado(8), Cliente())
    assert not ok and "vosk" in motivo


# ---------------------------------------------------------------- WebSocket
@pytest.fixture
def servidor(app):
    from sexta.servidor import HostsPermitidos, criar_api

    api = HostsPermitidos(criar_api(app), [])
    with TestClient(api, base_url=BASE) as c:
        yield c


def token_celular(cliente, app) -> str:
    cab = {"Authorization": f"Bearer {app.acesso.token_pc}"}
    codigo = cliente.post("/api/pareamento", headers=cab).json()["codigo"]
    return cliente.post("/api/pareamento/concluir", json={"codigo": codigo, "nome": "Pixel"}).json()["token"]


def test_websocket_aceita_audio_do_celular(servidor, app, monkeypatch):
    app.maos_livres.criar_detector = DetectorFalso
    recebidos = []
    original = ml.GerenteMaosLivres.receber_audio
    monkeypatch.setattr(ml.GerenteMaosLivres, "receber_audio",
                        lambda self, reg, dados: recebidos.append(len(dados)) or original(self, reg, dados))
    token = token_celular(servidor, app)
    with servidor.websocket_connect(f"/ws?token={token}", headers=dict(WS)) as ws:
        assert ws.receive_json()["tipo"] == "ola"
        ws.send_bytes(b"\x00" * 3200)  # desligado: ignorado
        ws.send_json({"tipo": "maos_livres", "ligar": True})
        while (e := ws.receive_json())["tipo"] != "maos_livres.estado":
            pass
        assert e["ligado"] and e["estado"] == "ouvindo"
        ws.send_bytes(b"\x00" * 3200)
        ws.send_json({"tipo": "ping", "t": 1})  # JSON continua funcionando
        while (e := ws.receive_json())["tipo"] != "pong":
            pass
        assert len(app.maos_livres.sessoes) == 1
        sessao = next(iter(app.maos_livres.sessoes.values()))
        assert esperar(lambda: sessao.fila.qsize() >= 1 or sessao._sobra)
        ws.send_json({"tipo": "maos_livres.tocando", "tocando": True})
        assert esperar(lambda: sessao.tocando)
    assert esperar(lambda: not app.maos_livres.sessoes)  # desconectou: limpou
    assert recebidos == [3200, 3200]


def test_websocket_pc_nao_manda_audio(servidor, app, monkeypatch):
    chamados = []
    monkeypatch.setattr(ml, "receber_audio", lambda *a: chamados.append(a))
    with servidor.websocket_connect(f"/ws?token={app.acesso.token_pc}", headers=dict(WS)) as ws:
        ws.receive_json()
        ws.send_bytes(b"\x00" * 100)
        ws.send_json({"tipo": "maos_livres", "ligar": True})  # PC: ignorado
        ws.send_json({"tipo": "ping", "t": 2})
        while (e := ws.receive_json())["tipo"] != "pong":
            pass
    assert not chamados and not app.maos_livres.sessoes


def test_rota_de_audio_autenticada(servidor, app):
    url = app.maos_livres.gerar_audio("Oi")
    assert servidor.get(url).status_code == 401
    r = servidor.get(url, headers={"Authorization": f"Bearer {app.acesso.token_pc}"})
    assert r.status_code == 200 and r.content == b"ID3falso"


# ---------------------------------------------------------------- comandos remotos
def test_print_pelo_celular(app, monkeypatch, tmp_path):
    from sexta.habilidades import windows

    def print_falso(pasta):
        pasta.mkdir(parents=True, exist_ok=True)
        arquivo = pasta / "print_2026-10-15_10-00-00.png"
        arquivo.write_bytes(b"png")
        return arquivo
    monkeypatch.setattr(windows, "print_da_tela", print_falso)
    for frase in ("tira um print do PC e me manda", "manda um print da tela", "Sexta-Feira, me manda um print"):
        r = app.agente.processar(frase, canal="celular", falar=False)
        assert r["texto"] == "Pronto, aqui está o print da tela do PC.", frase
        assert ml.imagem_da_resposta(app, r)["url"].startswith("/api/prints/print_")
    r = app.agente.processar("tira um print do pc e me manda", canal="voz", falar=False)
    assert "Print salvo" in r["texto"]


def test_o_que_esta_rodando(app, monkeypatch):
    from sexta.habilidades import janelas, processos

    monkeypatch.setattr(janelas, "listar", lambda: [janelas.Janela(1, "Projeto - Visual Studio Code", "code"),
                                                   janelas.Janela(2, "YouTube - Google Chrome", "chrome"),
                                                   janelas.Janela(3, "Outra aba", "chrome")])
    monkeypatch.setattr(processos, "top", lambda ordem="cpu", limite=6, amostra=0.6: [
        {"nome": "chrome", "cpu": 12.4, "ram_mb": 900}, {"nome": "code", "cpu": 3.0, "ram_mb": 500},
        {"nome": "ocioso", "cpu": 0.2, "ram_mb": 5}])
    r = app.agente.processar("o que está rodando aí", canal="celular", falar=False)
    assert "Abertos (2)" in r["texto"] and "chrome 12%" in r["texto"] and "ocioso" not in r["texto"]
    r = app.agente.processar("o que tá aberto no PC", canal="voz", falar=False)
    assert r["texto"].startswith("Abertos no PC: code e chrome.")


def test_o_que_esta_rodando_fora_do_windows(app, monkeypatch):
    from sexta.habilidades import processos

    monkeypatch.setattr(processos, "top", lambda *a, **k: [])
    assert ml.resumo_pc(app)["ok"] is False  # Linux: sem janelas e sem processos -> mensagem clara


def test_trava_o_pc_pelo_celular(app, monkeypatch):
    from sexta.habilidades import windows

    travados = []
    monkeypatch.setattr(windows, "bloquear_windows", lambda: travados.append(1))
    monkeypatch.setattr(app.rosto, "cadastrado", lambda: True)
    r = app.agente.processar("trava o PC aí", canal="celular", falar=False)
    assert travados and "PC bloqueado" in r["texto"] and app.sessao.bloqueada
    app.sessao.desbloquear("teste")
    r = app.agente.processar("bloqueia o computador", canal="celular", falar=False)
    assert len(travados) == 2 and r["texto"] == "Tela bloqueada."


def test_aprova_o_agente_pelo_celular(app):
    r = app.agente.processar("aprova o agente", canal="celular", falar=False)
    assert r["texto"] == "Nenhum agente está esperando aprovação."


# ---------------------------------------------------------------- anúncios
def test_anuncia_aprovacao_de_agente_e_alerta_de_seguranca(app, sessao, eventos):
    pendente = {"id": "a1", "numero": 2, "rotulo": "Navegador", "status": "aguardando",
                "pendente": {"ferramenta": "x", "descricao": "enviar o formulário", "nivel": 2}}
    app.barramento.publicar("agentes", agentes=[pendente], tipos=[])
    app.barramento.publicar("agentes", agentes=[pendente], tipos=[])  # repetido: anuncia uma vez só
    assert esperar(lambda: "maos_livres.anuncio" in tipos(eventos))
    anuncio = next(e for e in eventos if e["tipo"] == "maos_livres.anuncio")
    assert "aprova o agente 2" in anuncio["texto"] and anuncio["audio"]
    app.barramento.publicar("agentes", agentes=[{**pendente, "status": "concluido", "pendente": None}], tipos=[])
    assert esperar(lambda: any("terminou" in e.get("texto", "") for e in eventos if e["tipo"] == "maos_livres.anuncio"))
    app.barramento.publicar("aviso", nivel="erro", texto="Revisão semanal de segurança: 2 pontos importantes.")
    assert esperar(lambda: any(e["tipo"] == "maos_livres.alerta" for e in eventos))
    assert esperar(lambda: any("Alerta de segurança" in e.get("texto", "") for e in eventos if e["tipo"] == "maos_livres.anuncio"))
    time.sleep(0.2)
    assert sum("aprova o agente" in e.get("texto", "") for e in eventos if e["tipo"] == "maos_livres.anuncio") == 1


def test_sem_anuncios_quando_desligado(app, sessao, eventos):
    app.prefs.atualizar({"maos_livres_anuncios": False})
    app.maos_livres.anunciar("teste")
    assert "maos_livres.anuncio" not in tipos(eventos)


def test_desligar_limpa(app, sessao):
    assert threading.active_count() >= 1
    app.maos_livres.desligar(sessao.registrado.id)
    assert esperar(lambda: not sessao.thread.is_alive())
