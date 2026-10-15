"""Cibersegurança: auditoria de site e de rede (defensiva), autorização, faixas privadas e aprendizado."""

from __future__ import annotations

import httpx
import pytest

from sexta.extensoes import ciberseguranca as cs


# ----------------------------------------------------------------- site (funções puras)
def test_avaliar_site_https_ruim():
    resposta = {"ok": True, "url_final": "https://site.com", "headers": {"Server": "nginx/1.18.0"},
                "set_cookie": ["sid=abc"]}
    tls = {"ok": True, "versao": "TLSv1", "dias_para_expirar": 3, "emissor": "X"}
    r = cs.avaliar_site("https://site.com", resposta, tls)
    titulos = {i["titulo"] for i in r["itens"]}
    assert "Protocolo TLS antigo (TLSv1)" in titulos
    assert "Certificado TLS perto de vencer" in titulos
    assert any("strict-transport-security" in t for t in titulos)
    assert "Servidor expõe a versão" in titulos
    assert "Cookies sem Secure/HttpOnly" in titulos
    assert r["risco"] in ("alto", "medio")


def test_avaliar_site_sem_https():
    r = cs.avaliar_site("http://x.com", {"ok": True, "url_final": "http://x.com", "headers": {}}, {"ok": False})
    assert r["itens"][0]["titulo"] == "Site sem HTTPS" and r["risco"] == "alto"


def test_avaliar_site_bom():
    headers = {k: "v" for k in cs.CABECALHOS}
    r = cs.avaliar_site("https://ok.com", {"ok": True, "url_final": "https://ok.com", "headers": headers, "set_cookie": []},
                        {"ok": True, "versao": "TLSv1.3", "dias_para_expirar": 200})
    assert r["risco"] == "baixo" and r["itens"] == []


def test_auditar_site_com_http_falso(app):
    def handler(request):
        return httpx.Response(200, headers={"strict-transport-security": "max-age=1", "server": "Apache"},
                              text="ok")
    cliente = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    app.ciberseguranca._http = cliente
    app.ciberseguranca._tls = lambda host, porta=443: ({"notAfter": "Jan 1 00:00:00 2099 GMT",
                                                        "issuer": [[("organizationName", "Let's Encrypt")]]}, "TLSv1.3", ("X",))
    r = app.ciberseguranca.auditar_site("meusite.com.br")
    assert r["tipo"] == "site" and r["tls"]["emissor"] == "Let's Encrypt"
    assert any("content-security-policy" in i["titulo"] for i in r["itens"])
    # virou conhecimento na memória
    assert any("Auditoria de site" in i["texto"] for i in app.memoria.itens("conhecimento"))


# ----------------------------------------------------------------- rede (só privada)
@pytest.mark.parametrize("ip,privado", [("192.168.0.5", True), ("10.1.2.3", True), ("172.16.0.1", True),
                                        ("8.8.8.8", False), ("1.1.1.1", False)])
def test_so_rede_privada(ip, privado):
    assert cs.e_privado(ip) is privado
    assert (cs.rede_do_ip(ip) is not None) is privado


def test_avaliar_host_servicos_inseguros():
    h = cs.avaliar_host("192.168.0.9", "nas", {23: "", 22: "SSH-2.0", 445: ""})
    titulos = {i["titulo"]: i["risco"] for i in h["itens"]}
    assert titulos["Telnet aberto em nas"] == "alto"
    assert titulos["SMB exposto em nas"] == "medio"
    assert {s["porta"] for s in h["servicos"]} == {22, 23, 445}


def test_auditar_rede_recusa_publica(app):
    r = app.ciberseguranca.auditar_rede("8.8.8.0/24")
    assert "privadas" in r["erro"]


def test_auditar_rede_varre_so_o_alvo(app, monkeypatch):
    abertas = {"192.168.0.1": {80: "", 443: ""}, "192.168.0.7": {23: ""}}
    monkeypatch.setattr(cs, "porta_aberta", lambda host, porta, timeout: abertas.get(host, {}).get(porta))
    monkeypatch.setattr(cs, "_nomes_arp", lambda: {"192.168.0.1": "aa:bb:cc:dd:ee:ff"})
    monkeypatch.setattr(cs, "_nome_reverso", lambda ip: "")
    app.prefs.atualizar({"ciber_rede_max_hosts": 16})
    r = app.ciberseguranca.auditar_rede("192.168.0.0/28")
    ips = {h["ip"] for h in r["aparelhos"]}
    assert ips == {"192.168.0.1", "192.168.0.7"}
    assert any(i["titulo"] == "Telnet aberto em 192.168.0.7" and i["risco"] == "alto" for i in r["itens"])


# ----------------------------------------------------------------- autorização
def test_site_pede_autorizacao_e_depois_roda(app, monkeypatch):
    chamadas = []
    monkeypatch.setattr(app.ciberseguranca, "auditar_site",
                        lambda alvo: chamadas.append(alvo) or {"tipo": "site", "alvo": alvo, "itens": [], "risco": "baixo"})
    # primeira vez: não autorizado -> vira pendência (confirmação), não roda ainda
    r = app.agente.processar("verifica a segurança do meu site loja.com.br", canal="texto", falar=False)
    assert app.registro.pendente() is not None and chamadas == []
    assert "confirma que é seu" in app.registro.pendente().descricao
    # "sim" confirma, roda e guarda o escopo
    app.agente.processar("sim", canal="texto", falar=False)
    assert chamadas == ["loja.com.br"] and app.ciberseguranca.escopos.autorizado("site", "loja.com.br")
    # segunda vez: já autorizado, roda direto (sem pendência)
    chamadas.clear()
    app.agente.processar("verifica a segurança do meu site loja.com.br", canal="texto", falar=False)
    assert chamadas == ["loja.com.br"] and app.registro.pendente() is None


def test_escopos_subdominio_e_remover(app):
    esc = app.ciberseguranca.escopos
    esc.autorizar("site", "https://exemplo.com/pagina")
    assert esc.autorizado("site", "exemplo.com") and esc.autorizado("site", "www.exemplo.com")
    assert not esc.autorizado("site", "outro.com")
    assert esc.remover("exemplo.com") and not esc.autorizado("site", "exemplo.com")


def test_rede_recusa_publica_no_atalho(app):
    r = app.agente.processar("audita a rede 8.8.8.8", canal="texto", falar=False)
    # "audita a rede" casa, mas IP público é recusado antes de qualquer varredura
    assert "rede local" in r["texto"] and app.registro.pendente() is None


def test_agente_ciberseguranca_existe():
    from sexta.extensoes.agentes import TIPOS, inferir_tipo

    assert "ciberseguranca" in TIPOS
    assert "ciberseguranca_*" in TIPOS["ciberseguranca"].ferramentas and "rea__*" in TIPOS["ciberseguranca"].ferramentas
    assert TIPOS["ciberseguranca"].confirmar_inicio
    assert inferir_tipo("faz uma auditoria de segurança no meu servidor") == "ciberseguranca"
