"""Defesa: links suspeitos, segredos esquecidos em projetos e vigilância de mudanças (sem rede, sem Windows)."""

from __future__ import annotations

import pytest

from sexta.extensoes.defesa import analisar_link, mascarar, procurar_segredos


@pytest.mark.parametrize("url,risco", [
    ("https://www.mercadolivre.com.br/ofertas", "baixo"),
    ("https://www.nubank.com.br", "baixo"),
    ("https://www.gov.br/receitafederal", "baixo"),
    ("http://mercadolivre.atualiza-cadastro.xyz/login", "alto"),
    ("https://nubank-seguranca.com/verifica", "alto"),
    ("https://itau.com.br.acesso-seguro.top", "alto"),
    ("http://192.168.0.10/pix", "alto"),
    ("https://www.paypal.com@golpe.net/entrar", "alto"),
    ("https://xn--nubnk-wra.com", "alto"),
    ("bit.ly/abc123", "medio"),
    ("https://amaz0n.com/conta", "alto"),
])
def test_links(url, risco):
    r = analisar_link(url)
    assert r["risco"] == risco, r


def test_segredos_mascarados_e_env_fora_do_gitignore(tmp_path):
    projeto = tmp_path / "loja"
    (projeto / "src").mkdir(parents=True)
    (projeto / "node_modules").mkdir()
    chave = "AKIA" + "ABCDEFGHIJKLMNOP"
    (projeto / "src" / "config.py").write_text(f'AWS = "{chave}"\nsenha = "Xk9#vB2q!Lm7"\nnome = "loja"\n',
                                               encoding="utf-8")
    (projeto / "src" / "exemplo.py").write_text('api_key = "your_api_key_here"\n', encoding="utf-8")
    (projeto / "node_modules" / "lib.js").write_text(f'k="{chave}"', encoding="utf-8")
    (projeto / ".env").write_text("TOKEN=abc", encoding="utf-8")
    r = procurar_segredos(projeto)
    tipos = {(a["arquivo"].replace("\\", "/"), a["linha"], a["tipo"]) for a in r["achados"]}
    assert tipos == {("src/config.py", 1, "chave da AWS"), ("src/config.py", 2, "senha no código")}
    assert all(chave not in a["trecho"] for a in r["achados"]) and mascarar(chave) == "AKIA…OP"
    assert r["avisos"] and ".gitignore" in r["avisos"][0]
    (projeto / ".gitignore").write_text(".env\n", encoding="utf-8")
    assert procurar_segredos(projeto)["avisos"] == []


def test_atalhos_link_e_segredos(app, tmp_path, monkeypatch):
    r = app.agente.processar("esse link é seguro? http://bradesco-premio.click/pix", canal="texto", falar=False)
    assert r["caminho"] == "atalho" and r["texto"].startswith("Cuidado: bradesco-premio.click tem cara de golpe")
    monkeypatch.setattr("sexta.habilidades.area_transferencia.ler", lambda: "olha isso https://www.google.com")
    r = app.agente.processar("verifica o link que eu copiei", canal="texto", falar=False)
    assert r["texto"].startswith("www.google.com parece normal")

    projeto = tmp_path / "Projetos" / "bolaocopa"
    projeto.mkdir(parents=True)
    (projeto / "app.js").write_text('const t = "ghp_' + "a1B2" * 9 + '";\n', encoding="utf-8")
    app.prefs.atualizar({"projetos_pastas": [str(tmp_path / "Projetos")]})
    r = app.agente.processar("procura senhas esquecidas no projeto bolaocopa", canal="texto", falar=False)
    assert r["caminho"] == "atalho" and "Achei 1 possível segredo no projeto bolaocopa" in r["texto"]


class SegurancaFalsa:
    def __init__(self):
        self.itens = [{"id": "run:onedrive", "categoria": "inicializacao", "titulo": "OneDrive", "risco": "baixo"}]

    def revisar(self, partes, mostrar=False):
        return {"itens": list(self.itens)}


def test_vigilancia_linha_de_base_alerta_e_ignorar(app):
    falsa = SegurancaFalsa()
    app.seguranca = falsa
    v = app.vigilancia
    assert v.verificar() == []  # primeira passada só aprende
    falsa.itens.append({"id": "run:x", "categoria": "inicializacao", "titulo": "Programa novo na inicialização: x.exe",
                        "risco": "alto", "sugestao": "Desative se não foi você."})
    falsa.itens.append({"id": "porta:5000", "categoria": "portas", "titulo": "Porta 5000 aberta", "risco": "baixo"})
    alertas = v.verificar()
    assert [a["id"] for a in alertas] == ["run:x"]
    assert "Atenção: Programa novo na inicialização" in app.fala.tudo()
    assert any("Vigilância" in i["texto"] for i in app.memoria.itens("conhecimento"))
    r = app.agente.processar("o que mudou no PC?", canal="texto", falar=False)
    assert "x.exe" in r["texto"] and "Desative" in r["texto"]
    assert app.agente.processar("pode ignorar", canal="texto", falar=False)["texto"].startswith("Tudo bem, marquei 1 item")
    assert v.verificar() == []  # agora faz parte da linha de base
