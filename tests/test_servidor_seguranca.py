"""Servidor: tokens, Host, pareamento do celular, WebSocket e PIN."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sexta.seguranca import Acesso, ErroAcesso
from sexta.servidor import HostsPermitidos, criar_api

BASE = "http://127.0.0.1:8765"
WS = {"host": "127.0.0.1:8765", "origin": BASE}  # o TestClient usa "testserver" no WebSocket


@pytest.fixture
def cliente(app):
    api = HostsPermitidos(criar_api(app), ["meu-pc.tail1234.ts.net"])
    with TestClient(api, base_url=BASE) as c:
        yield c


def cab(app) -> dict:
    return {"Authorization": f"Bearer {app.acesso.token_pc}"}


def test_saude_sem_token(cliente):
    assert cliente.get("/api/saude").json()["ok"] is True


def test_exige_token(cliente, app):
    assert cliente.get("/api/estado").status_code == 401
    assert cliente.get("/api/estado", headers={"Authorization": "Bearer errado"}).status_code == 401
    r = cliente.get("/api/estado", headers=cab(app))
    assert r.status_code == 200 and r.json()["cliente"]["tipo"] == "pc"


def test_host_estranho_bloqueado(app):
    api = HostsPermitidos(criar_api(app), [])
    with TestClient(api, base_url="http://site-malicioso.com") as c:
        assert c.get("/api/saude").status_code == 400
    assert HostsPermitidos(lambda *a: None, []).host_ok("meu-pc.tail1234.ts.net")
    assert HostsPermitidos(lambda *a: None, []).host_ok("localhost:8765")
    assert not HostsPermitidos(lambda *a: None, []).host_ok("evil.com")
    assert HostsPermitidos(lambda *a: None, ["casa.exemplo"]).host_ok("casa.exemplo:8766")


def test_pareamento_do_celular(cliente, app):
    inicio = cliente.post("/api/pareamento", headers=cab(app)).json()
    assert len(inicio["codigo"]) == 6
    errado = cliente.post("/api/pareamento/concluir", json={"codigo": "000000" if inicio["codigo"] != "000000" else "111111"})
    assert errado.status_code == 403
    certo = cliente.post("/api/pareamento/concluir", json={"codigo": inicio["codigo"], "nome": "Galaxy"})
    assert certo.status_code == 200
    token = certo.json()["token"]
    celular = {"Authorization": f"Bearer {token}"}
    estado = cliente.get("/api/estado", headers=celular).json()
    assert estado["cliente"] == {"tipo": "celular", "nome": "Galaxy"}
    # celular não acessa ações exclusivas do PC
    assert cliente.post("/api/pareamento", headers=celular).status_code == 403
    assert cliente.patch("/api/preferencias", headers=celular, json={"nome": "x"}).status_code == 403
    # o código não pode ser reutilizado
    assert cliente.post("/api/pareamento/concluir", json={"codigo": inicio["codigo"]}).status_code == 403
    # revogar
    disp = cliente.get("/api/dispositivos", headers=cab(app)).json()
    cliente.delete(f"/api/dispositivos/{disp[0]['id']}", headers=cab(app))
    assert cliente.get("/api/estado", headers=celular).status_code == 401


def test_websocket_recebe_eventos(cliente, app):
    with pytest.raises(Exception):
        with cliente.websocket_connect("/ws?token=errado", headers=dict(WS)) as ws:
            ws.receive_json()
    with cliente.websocket_connect(f"/ws?token={app.acesso.token_pc}", headers=dict(WS)) as ws:
        ola = ws.receive_json()
        assert ola["tipo"] == "ola" and ola["cliente"]["tipo"] == "pc"
        r = cliente.post("/api/hologramas", headers=cab(app), json={"tipo": "relogio"})
        assert r.status_code == 200
        evento = ws.receive_json()
        while evento["tipo"] != "holograma.abrir":
            evento = ws.receive_json()
        assert evento["holograma"]["tipo"] == "relogio"
        ws.send_json({"tipo": "ping", "t": 123})
        while (evento := ws.receive_json())["tipo"] != "pong":
            pass
        assert evento["t"] == 123


def test_websocket_rejeita_outra_origem(cliente, app):
    with pytest.raises(Exception):
        with cliente.websocket_connect(f"/ws?token={app.acesso.token_pc}",
                                       headers={"host": "127.0.0.1:8765", "origin": "http://evil.com"}) as ws:
            ws.receive_json()


def test_conversa_bloqueada_e_pin(cliente, app, monkeypatch):
    monkeypatch.setattr(app.rosto, "cadastrado", lambda: True)
    app.sessao.bloquear("teste")
    r = cliente.post("/api/conversa", headers=cab(app), json={"texto": "oi"})
    assert r.status_code == 423
    assert cliente.post("/api/pin", headers=cab(app), json={"pin": "12a"}).status_code == 400
    assert cliente.post("/api/pin", headers=cab(app), json={"pin": "4321"}).json()["pin"] is True
    assert cliente.post("/api/desbloquear", headers=cab(app), json={"metodo": "pin", "pin": "0000"}).status_code == 403
    r = cliente.post("/api/desbloquear", headers=cab(app), json={"metodo": "pin", "pin": "4321"})
    assert r.status_code == 200 and r.json()["bloqueada"] is False
    # trocar o PIN exige o atual
    assert cliente.post("/api/pin", headers=cab(app), json={"pin": "1111"}).status_code == 403


def test_preferencias_e_cidade_invalida(cliente, app, monkeypatch):
    from sexta.habilidades.clima import ErroClima

    def falhar(_):
        raise ErroClima("Não encontrei a cidade Xyzzy.")

    monkeypatch.setattr(app.clima, "localizar", falhar)
    r = cliente.patch("/api/preferencias", headers=cab(app), json={"nome": "Júlio", "cidade_lat": 1})
    assert r.json()["nome"] == "Júlio" and r.json()["cidade_lat"] is None  # chaves internas não são editáveis
    r = cliente.patch("/api/preferencias", headers=cab(app), json={"cidade": "Xyzzy"})
    assert r.status_code == 400 and "Xyzzy" in r.json()["erro"]


def test_prints_sem_path_traversal(cliente, app):
    assert cliente.get("/api/prints/..%2F..%2Facesso.json", headers=cab(app)).status_code in (400, 404)
    assert cliente.get("/api/prints/segredo.txt", headers=cab(app)).status_code == 400


def test_hud_sem_build(cliente, app):
    r = cliente.get("/")
    assert r.status_code == 200


def test_pin_limita_tentativas(tmp_path):
    acesso = Acesso(tmp_path / "acesso.json")
    acesso.definir_pin("2468")
    for _ in range(5):
        assert acesso.verificar_pin("0000") is False
    with pytest.raises(ErroAcesso):
        acesso.verificar_pin("2468")


def test_tokens_persistem_e_dispositivos_tem_hash(tmp_path):
    a = Acesso(tmp_path / "acesso.json")
    codigo = a.iniciar_pareamento()["codigo"]
    token, _ = a.concluir_pareamento(codigo, "Pixel")
    conteudo = (tmp_path / "acesso.json").read_text()
    assert token not in conteudo  # só o hash fica salvo
    b = Acesso(tmp_path / "acesso.json")
    assert b.token_pc == a.token_pc and b.autenticar(token).nome == "Pixel"


def test_preferencias_de_planejamento_validadas(cliente, app):
    assert cliente.patch("/api/preferencias", json={"expediente_inicio": "9h"}, headers=cab(app)).status_code == 400
    assert cliente.patch("/api/preferencias", json={"almoco": "meio-dia"}, headers=cab(app)).status_code == 400
    r = cliente.patch("/api/preferencias", json={"expediente_inicio": "08:30", "almoco": ""}, headers=cab(app))
    assert r.status_code == 200 and r.json()["expediente_inicio"] == "08:30"


def test_quadro_de_tarefas_pela_api(cliente, app):
    r = cliente.post("/api/tarefas", json={"texto": "revisar o relatório até amanhã, urgente"}, headers=cab(app))
    assert r.status_code == 200 and r.json()["titulo"] == "Revisar o relatório" and r.json()["prioridade"] == "alta"
    id_ = r.json()["id"]
    assert cliente.patch(f"/api/tarefas/{id_}", json={"status": "fazendo"}, headers=cab(app)).json()["status"] == "fazendo"
    assert cliente.patch(f"/api/tarefas/{id_}", json={"status": "voando"}, headers=cab(app)).status_code == 400
    assert [t["id"] for t in cliente.get("/api/tarefas", headers=cab(app)).json()["colunas"]["fazendo"]] == [id_]
    assert cliente.delete(f"/api/tarefas/{id_}", headers=cab(app)).json()["ok"]
