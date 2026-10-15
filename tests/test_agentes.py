"""Agentes autônomos: loop com o cérebro, aprovação, conferência, memória, MCP, atalhos e rotas (tudo com dublês)."""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import textwrap
import threading
import time
from types import SimpleNamespace

import pytest

from sexta import mcp_cliente
from sexta.cerebro.ferramentas import CONFIRMAR, LIVRE
from sexta.extensoes import agentes as mod
from sexta.extensoes import agentes_ferramentas as proprias
from sexta.util.texto import normalizar


# ---------------------------------------------------------------- dublês

class CerebroFalso:
    """Cada rodada é um texto (resposta final) ou uma lista de chamadas [(nome, args), ...]."""

    def __init__(self, rodadas, conferencia=None, repetir_ultima=False):
        self.rodadas = list(rodadas)
        self.conferencia = conferencia if conferencia is not None else {
            "status": "concluido", "evidencia": "o passo 2 trouxe o resultado", "resumo_falado": "Achei o preço.",
            "licao": "buscar em sites oficiais primeiro", "conhecimento": "o dólar fechou a 5 reais",
            "etiquetas": ["cambio"]}
        self.repetir_ultima = repetir_ultima
        self.pedidos = []
        self.extras = []
        self.conferencias = []

    def conversar(self, mensagens, ferramentas=None, cancelado=lambda: False, *, modelo=None, max_tokens=None,
                  pensar=False):
        self.pedidos.append([dict(m) for m in mensagens])
        self.extras.append({"pensar": pensar, "ferramentas": [f["function"]["name"] for f in ferramentas or []]})
        rodada = self.rodadas.pop(0) if (len(self.rodadas) > 1 or not self.repetir_ultima) else self.rodadas[0]
        if isinstance(rodada, str):
            yield {"tipo": "texto", "texto": rodada}
            yield {"tipo": "fim", "texto": rodada, "chamadas": [], "bruto": None}
            return
        chamadas = [{"nome": n, "argumentos": a} for n, a in rodada]
        yield {"tipo": "ferramentas", "chamadas": chamadas}
        yield {"tipo": "fim", "texto": "", "chamadas": chamadas, "bruto": None}

    @staticmethod
    def mensagem_assistente(texto, chamadas, bruto):
        return {"role": "assistant", "content": texto,
                "tool_calls": [{"function": {"name": c["nome"], "arguments": c["argumentos"]}} for c in chamadas]}

    @staticmethod
    def mensagens_resultados(chamadas, conteudos):
        return [{"role": "tool", "tool_name": c["nome"], "content": json.dumps(r, ensure_ascii=False)}
                for c, r in zip(chamadas, conteudos)]

    def completar(self, sistema, texto, modelo=None):
        self.conferencias.append(texto)
        return "```json\n" + json.dumps(self.conferencia, ensure_ascii=False) + "\n```"


class MemoriaFalsa:
    def __init__(self):
        self.aprendidos = []

    def aprender(self, tipo, texto, etiquetas=(), origem=""):
        self.aprendidos.append((tipo, texto, list(etiquetas), origem))

    def buscar(self, consulta, limite=5, tipos=None):
        return [{"tipo": "licao", "texto": "use fontes oficiais", "etiquetas": ["agente"]}]

    def para_prompt(self):
        return ""


def esperar(condicao, limite=10.0):
    fim = time.time() + limite
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(0.02)
    raise AssertionError("tempo esgotado")


def esperar_fim(agente, limite=10.0):
    esperar(lambda: not agente.ativo, limite)
    agente.thread.join(5)


@pytest.fixture
def ag(app, monkeypatch):
    """A Sexta-Feira de teste com cérebro e memória falsos para os agentes."""
    app.memoria_original = app.memoria
    app.memoria = MemoriaFalsa()
    monkeypatch.setattr(proprias, "buscar_web", lambda consulta, limite=8, http=None: [
        {"titulo": "Cotação do dólar hoje", "url": "https://exemplo.com/dolar", "trecho": "R$ 5,00"}])
    yield app
    app.agentes.encerrar()


def usar(app, cerebro):
    app.agente.cerebro = cerebro
    return cerebro


# ---------------------------------------------------------------- loop, conferência e memória

def test_agente_pesquisador_conclui_confere_e_aprende(ag):
    cerebro = usar(ag, CerebroFalso([[("web_buscar", {"consulta": "dólar hoje"})],
                                     "O dólar está em R$ 5,00. Fonte: exemplo.com/dolar."]))
    agente = ag.agentes.iniciar("pesquisador", "pesquisar o preço do dólar", "voz")
    esperar_fim(agente)

    assert agente.status == "concluido"
    assert "R$ 5,00" in agente.relatorio
    assert agente.resumo == "Achei o preço."
    tipos = [p["tipo"] for p in agente.passos]
    assert tipos[0] == "inicio" and "ferramenta" in tipos and "resultado" in tipos and tipos[-1] == "conferencia"
    assert any(p["tipo"] == "resultado" and p["ok"] for p in agente.passos)
    # modelo principal com pensamento, só com as ferramentas do tipo, e a memória relevante no pedido
    assert cerebro.extras[0]["pensar"] is True
    assert set(cerebro.extras[0]["ferramentas"]) >= {"web_buscar", "web_ler", "memoria_buscar"}
    assert "agente" not in cerebro.extras[0]["ferramentas"] and "terminal" not in cerebro.extras[0]["ferramentas"]
    assert "use fontes oficiais" in cerebro.pedidos[0][1]["content"]
    # conferência recebeu os passos; lição e conhecimento foram para a memória
    assert "web_buscar" in cerebro.conferencias[0]
    assert [a[0] for a in ag.memoria.aprendidos] == ["licao", "conhecimento"]
    assert "pesquisador" in ag.memoria.aprendidos[0][2]
    # aviso falado e histórico salvo
    assert "O agente pesquisador terminou. Achei o preço." in ag.fala.tudo()
    salvo = json.loads((ag.cfg.dados / "agentes.json").read_text(encoding="utf-8"))
    assert salvo["agentes"][0]["status"] == "concluido" and salvo["agentes"][0]["objetivo"] == "pesquisar o preço do dólar"


def test_conferencia_sem_evidencia_marca_parcial_e_falha(ag):
    usar(ag, CerebroFalso(["Feito!"], conferencia={"status": "parcial", "evidencia": "sem prova",
                                                   "resumo_falado": "Fiz só uma parte."}))
    agente = ag.agentes.iniciar("pesquisador", "descobrir algo", "voz")
    esperar_fim(agente)
    assert agente.status == "parcial"
    assert "terminou em parte" in ag.fala.tudo()

    usar(ag, CerebroFalso(["Nada."], conferencia={"status": "falhou", "resumo_falado": "Não achei."}))
    agente = ag.agentes.iniciar("pesquisador", "descobrir outra coisa", "voz")
    esperar_fim(agente)
    assert agente.status == "falhou"
    assert not any(a[0] == "conhecimento" for a in ag.memoria.aprendidos)  # falha não vira conhecimento


def test_conferencia_ilegivel_vira_parcial(ag):
    cerebro = usar(ag, CerebroFalso(["Pronto."]))
    cerebro.completar = lambda *a, **k: "não sei"
    agente = ag.agentes.iniciar("pesquisador", "x", "voz")
    esperar_fim(agente)
    assert agente.status == "parcial"


def test_limite_de_passos_pede_relatorio(ag):
    ag.prefs.atualizar({"agentes_max_passos": 2}, interno=True)
    cerebro = usar(ag, CerebroFalso([[("memoria_buscar", {"consulta": "a"})], [("memoria_buscar", {"consulta": "b"})],
                                     "Relatório parcial: busquei duas vezes."]))
    agente = ag.agentes.iniciar("pesquisador", "loop", "voz")
    esperar_fim(agente)
    assert agente.relatorio == "Relatório parcial: busquei duas vezes."
    assert any("Limite de passos" in p["texto"] for p in agente.passos)
    ultimo = cerebro.pedidos[-1]
    assert mod.FINAL_AGORA in ultimo[-1]["content"] or ultimo[-1]["role"] == "user"


def test_ferramenta_inexistente_e_tipos_ignoram_o_que_falta(ag):
    cerebro = usar(ag, CerebroFalso([[("terminal", {"comando": "dir"})], "Não deu."]))
    agente = ag.agentes.iniciar("video", "cortar um vídeo", "voz")
    esperar_fim(agente)
    # a extensão de vídeo não existe nesta base: video_* é ignorado, sobra arquivos e memória
    assert set(cerebro.extras[0]["ferramentas"]) == {"arquivos", "memoria_buscar"}
    assert any("não está disponível" in p["texto"] for p in agente.passos if p["tipo"] == "resultado")


# ---------------------------------------------------------------- aprovação

def test_acao_sensivel_pausa_e_continua_com_aprovacao(ag, monkeypatch):
    chamadas = []
    original = ag.registro._ferramentas["fechar_programa"].funcao
    ag.registro._ferramentas["fechar_programa"].funcao = lambda ctx, **a: chamadas.append(a) or "Fechei o Bloco de Notas."
    usar(ag, CerebroFalso([[("fechar_programa", {"nome": "notepad"})], "Fechei."]))
    agente = ag.agentes.iniciar("automacao", "fechar o bloco de notas", "voz")
    esperar(lambda: agente.status == "aguardando")

    assert chamadas == []                          # nada roda antes do "sim"
    assert ag.registro.pendente() is None          # a pendência é do agente, não do "sim" da conversa
    assert ag.agentes.dados()["agentes"][0]["pendente"]["descricao"]
    assert "aprova o agente" in ag.fala.tudo()
    assert "esperando sua aprovação" in mod.descrever_status(ag.agentes)

    resposta = ag.agentes.aprovar(None, ag.contexto("texto"))
    assert resposta.startswith("Aprovado")
    esperar_fim(agente)
    assert chamadas == [{"nome": "notepad"}]
    assert any(p["tipo"] == "aprovado" for p in agente.passos)
    ag.registro._ferramentas["fechar_programa"].funcao = original


def test_acao_sensivel_recusada_nao_executa(ag):
    chamadas = []
    ag.registro._ferramentas["fechar_programa"].funcao = lambda ctx, **a: chamadas.append(a) or "x"
    cerebro = usar(ag, CerebroFalso([[("fechar_programa", {"nome": "notepad"})], "Não fechei."]))
    agente = ag.agentes.iniciar("automacao", "fechar", "voz")
    esperar(lambda: agente.status == "aguardando")
    assert ag.agentes.aprovar("1", ag.contexto("texto"), aprovar=False).startswith("Certo")
    esperar_fim(agente)
    assert chamadas == []
    resultado = json.loads(cerebro.pedidos[1][-1]["content"])
    assert resultado["ok"] is False and resultado["recusado"] is True


def test_nivel_rosto_confere_identidade_na_aprovacao(ag, monkeypatch):
    usar(ag, CerebroFalso([[("terminal", {"comando": "format c:"})], "ok"]))
    monkeypatch.setattr(ag, "verificar_para_acao", lambda ctx: (False, "Não reconheci você, então não fiz."))
    agente = ag.agentes.iniciar("automacao", "rodar comando", "voz")
    esperar(lambda: agente.status == "aguardando")
    assert agente.pendencia.nivel == 3
    assert ag.agentes.aprovar(None, ag.contexto("voz")) == "Não reconheci você, então não fiz."
    assert agente.status == "aguardando"
    ag.agentes.cancelar(agente.id)
    esperar_fim(agente)
    assert agente.status == "cancelado"


def test_sem_resposta_a_acao_e_recusada(ag, monkeypatch):
    ag.registro._ferramentas["fechar_programa"].funcao = lambda ctx, **a: pytest.fail("não podia rodar")
    usar(ag, CerebroFalso([[("fechar_programa", {"nome": "x"})], "fim"]))
    monkeypatch.setattr(mod, "_inteiro", lambda valor, padrao, minimo, maximo: 0 if padrao == 10 else
                        max(minimo, min(maximo, int(valor) if str(valor).isdigit() else padrao)))
    agente = ag.agentes.iniciar("automacao", "x", "voz")
    esperar_fim(agente)
    assert any(p["tipo"] == "recusado" and "Sem resposta" in p["texto"] for p in agente.passos)


def test_cancelar_agente_rodando(ag):
    liberar = threading.Event()

    class Lento(CerebroFalso):
        def conversar(self, *a, **k):
            cancelado = a[2]
            while not cancelado():
                time.sleep(0.02)
            yield {"tipo": "fim", "texto": "", "chamadas": [], "bruto": None}

    usar(ag, Lento([]))
    agente = ag.agentes.iniciar("pesquisador", "algo demorado", "voz")
    resposta = ag.registro.executar("agente", {"acao": "cancelar"}, ag.contexto("voz"))
    assert resposta["resumo"] == "Cancelei o agente pesquisador."
    esperar_fim(agente)
    assert agente.status == "cancelado"
    assert "terminou" not in ag.fala.tudo()
    liberar.set()


def test_limite_de_agentes_simultaneos(ag):
    ag.prefs.atualizar({"agentes_max_simultaneos": 1}, interno=True)
    usar(ag, CerebroFalso([[("fechar_programa", {"nome": "x"})], "fim"]))
    agente = ag.agentes.iniciar("automacao", "um", "voz")
    esperar(lambda: agente.status == "aguardando")
    resposta = ag.registro.executar("agente", {"acao": "iniciar", "tipo": "pesquisador", "objetivo": "dois"},
                                    ag.contexto("voz"))
    assert resposta["ok"] is False and "Já tem 1" in resposta["resumo"]
    ag.agentes.cancelar(todos=True)
    esperar_fim(agente)


# ---------------------------------------------------------------- ferramenta "agente" e atalhos

def test_ferramenta_iniciar_responde_na_hora(ag):
    usar(ag, CerebroFalso(["ok"]))
    resposta = ag.registro.executar("agente", {"acao": "iniciar", "tipo": "pesquisador", "objetivo": "x"},
                                    ag.contexto("voz"))
    assert resposta["resumo"] == "Pode deixar, coloquei o agente pesquisador nisso."
    assert ag.hologramas.aberto("agentes")
    esperar_fim(ag.agentes.encontrar(resposta["agente"]))


def test_programador_pede_confirmacao_para_iniciar(ag):
    resposta = ag.registro.executar("agente", {"acao": "iniciar", "tipo": "programador", "objetivo": "corrigir bug"},
                                    ag.contexto("voz"))
    assert resposta.get("pendente") is True and "programador" in resposta["resumo"]
    assert ag.agentes.ativos() == []
    ag.registro.cancelar_pendente()


@pytest.mark.parametrize("fala, esperado", [
    ("Sexta-feira, coloca um agente para pesquisar o preço do dólar hoje",
     {"acao": "iniciar", "tipo": "pesquisador", "objetivo": "pesquisar o preço do dólar hoje"}),
    ("agente navegador, abre o site da Prefeitura e vê o horário do IPTU",
     {"acao": "iniciar", "tipo": "navegador", "objetivo": "abre o site da Prefeitura e vê o horário do IPTU"}),
    ("coloca o agente programador para corrigir o bug do login no projeto Loja",
     {"acao": "iniciar", "tipo": "programador", "objetivo": "corrigir o bug do login no projeto Loja"}),
    ("bota um agente pra analisar o executável C:\\Apps\\app.exe",
     {"acao": "iniciar", "tipo": "engenharia_reversa", "objetivo": "analisar o executável C:\\Apps\\app.exe"}),
    ("status dos agentes", {"acao": "status"}),
    ("O que os agentes estão fazendo?", {"acao": "status"}),
    ("cancela o agente", {"acao": "cancelar"}),
    ("cancela o agente navegador", {"acao": "cancelar", "agente": "navegador"}),
    ("cancela todos os agentes", {"acao": "cancelar", "agente": "todos"}),
    ("aprova o agente", {"acao": "aprovar"}),
    ("aprova o agente 3", {"acao": "aprovar", "agente": "3"}),
    ("nega o agente", {"acao": "negar"}),
    ("mostra os agentes", {"acao": "listar"}),
])
def test_atalhos(ag, fala, esperado):
    rodadas = []
    ctx = ag.contexto("voz")
    t = re.sub(r"^(sexta feira|sexta) ", "", normalizar(fala))  # como em cerebro.atalhos.tentar
    plano = mod.atalho(t, ctx, lambda nome, args, padrao=None: rodadas.append((nome, args)) or "ok", fala)
    assert plano == "ok"
    assert rodadas == [("agente", esperado)]


def test_pode_continuar_so_com_agente_esperando(ag):
    ctx = ag.contexto("voz")
    rodar = lambda nome, args, padrao=None: (nome, args)  # noqa: E731
    assert mod.atalho("pode continuar", ctx, rodar, "pode continuar") is None
    assert mod.atalho("que horas sao", ctx, rodar, "que horas são") is None


def test_inferir_tipo():
    assert mod.inferir_tipo("pesquisar notebooks") == "pesquisador"
    assert mod.inferir_tipo("organiza a pasta downloads") == "automacao"
    assert mod.inferir_tipo("editar o vídeo da viagem") == "video"
    assert mod.inferir_tipo("entra no site do banco e vê o saldo") == "navegador"


def test_acao_de_protocolo(ag):
    usar(ag, CerebroFalso(["ok"]))
    mod.ACOES_PROTOCOLO["agente"]["executar"](ag, "pesquisador: notícias de IA", ag.contexto("voz"), {})
    agente = ag.agentes.encontrar("pesquisador")
    assert agente.objetivo == "notícias de IA" and agente.origem == "protocolo"
    esperar_fim(agente)
    from sexta.habilidades import rotinas
    assert "agente" in rotinas.ACOES and "agente" in rotinas.ACOES_EXTRAS


# ---------------------------------------------------------------- persistência, rotas, diagnóstico

def test_historico_marca_interrompidos(ag):
    arquivo = ag.cfg.dados / "agentes2.json"
    arquivo.write_text(json.dumps({"agentes": [{"id": "a7", "numero": 7, "status": "rodando", "objetivo": "x"}]}),
                       encoding="utf-8")
    gerente = mod.GerenteAgentes(ag, arquivo)
    assert gerente.historico[0]["status"] == "interrompido"
    assert next(gerente._numeros) == 8


def test_rotas_e_holograma(ag):
    from fastapi.testclient import TestClient
    from sexta.servidor import criar_api

    usar(ag, CerebroFalso(["ok"]))
    with TestClient(criar_api(ag), base_url="http://127.0.0.1:8765") as c:
        c.headers["Authorization"] = f"Bearer {ag.acesso.token_pc}"
        r = c.post("/api/agentes", json={"tipo": "pesquisador", "objetivo": "teste"})
        assert r.status_code == 200 and r.json()["ok"]
        agente = ag.agentes.encontrar("pesquisador")
        esperar_fim(agente)
        dados = c.get("/api/agentes").json()
        assert dados["agentes"][0]["status"] == "concluido"
        assert {t["tipo"] for t in dados["tipos"]} == set(mod.TIPOS)
        assert c.post("/api/agentes", json={"tipo": "xyz", "objetivo": "a"}).status_code == 400
        assert c.post("/api/agentes/a99/cancelar").status_code == 404
        ajustes = c.get("/api/agentes/ajustes").json()
        assert {s["nome"] for s in ajustes["mcp"]} == {"rea", "chrome-devtools"}
    assert mod.dados_holograma(ag, "agentes")["agentes"]


def test_diagnostico_lista_programas_e_mcp(ag):
    nomes = [i["nome"] for i in mod.diagnostico(ag)]
    assert "Node.js (agentes)" in nomes and "agent-browser (agente navegador)" in nomes
    assert "Claude Code (agente programador)" in nomes and "MCP rea" in nomes and "MCP chrome-devtools" in nomes


def test_mcp_yaml_padrao_criado(ag):
    texto = (ag.cfg.pasta_config / "mcp.yaml").read_text(encoding="utf-8")
    assert "rea-agents@latest" in texto and "chrome-devtools-mcp@latest" in texto


# ---------------------------------------------------------------- cliente MCP (dublê)

class SessaoFalsa:
    def __init__(self):
        self.chamadas = []

    async def list_tools(self):
        anot = SimpleNamespace(read_only_hint=True, destructive_hint=False)
        perigosa = SimpleNamespace(read_only_hint=False, destructive_hint=True)
        return SimpleNamespace(tools=[
            SimpleNamespace(name="ler_strings", description="Lista strings", input_schema={"type": "object"},
                            annotations=anot),
            SimpleNamespace(name="executar_alvo", description="Roda o binário", input_schema={"type": "object"},
                            annotations=perigosa),
            SimpleNamespace(name="mapa", description="Mapa", input_schema={"type": "object"}, annotations=None),
        ])

    async def call_tool(self, nome, argumentos):
        self.chamadas.append((nome, argumentos))
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=f"{nome} ok {argumentos}")], is_error=False)


def cliente_falso(sessao, nivel="confirmar"):
    @contextlib.asynccontextmanager
    async def conectar():
        yield sessao

    cliente = mcp_cliente.ClienteMCP(None, conectores={"rea": conectar})
    cfg = mcp_cliente.ConfigServidor("rea", sys.executable, habilitado=True, nivel=nivel)
    cliente.servidores["rea"] = mcp_cliente.ServidorMCP(cfg, cliente, conectar)
    return cliente


def test_cliente_mcp_prefixo_niveis_e_chamada():
    sessao = SessaoFalsa()
    cliente = cliente_falso(sessao)
    try:
        assert not cliente.servidores["rea"].rodando  # preguiçoso
        ferramentas = {f.nome_completo: f for f in cliente.ferramentas(["rea__*"])}
        assert set(ferramentas) == {"rea__ler_strings", "rea__executar_alvo", "rea__mapa"}
        assert ferramentas["rea__ler_strings"].nivel == LIVRE       # só leitura
        assert ferramentas["rea__executar_alvo"].nivel == CONFIRMAR  # destrutiva
        assert ferramentas["rea__mapa"].nivel == CONFIRMAR           # padrão do servidor
        resultado = cliente.chamar("rea__ler_strings", {"alvo": "a.exe"})
        assert resultado == {"ok": True, "resumo": "ler_strings ok {'alvo': 'a.exe'}"}
        assert cliente.chamar("outro__x", {})["ok"] is False
        assert cliente.estado()[0]["rodando"] and cliente.estado()[0]["ferramentas"] == 3
    finally:
        cliente.encerrar()
    assert not cliente.servidores["rea"].rodando


def test_servidor_mcp_sem_comando_avisa():
    cliente = mcp_cliente.ClienteMCP(None)
    cliente.servidores["x"] = mcp_cliente.ServidorMCP(
        mcp_cliente.ConfigServidor("x", "comando-que-nao-existe-123"), cliente)
    avisos = []
    assert cliente.ferramentas(["x__*"], avisar=avisos.append) == []
    assert "Node.js" in avisos[0]
    cliente.encerrar()


def test_linha_de_comando_no_windows(monkeypatch):
    cfg = mcp_cliente.ConfigServidor("rea", "npx", ["-y", "rea-agents@latest", "mcp"])
    monkeypatch.setattr(mcp_cliente.os, "name", "nt")
    assert cfg.linha_de_comando() == ("cmd.exe", ["/d", "/c", "npx", "-y", "rea-agents@latest", "mcp"])
    monkeypatch.setattr(mcp_cliente.os, "name", "posix")
    assert cfg.linha_de_comando() == ("npx", ["-y", "rea-agents@latest", "mcp"])


def test_agente_engenharia_reversa_usa_mcp_e_pede_aprovacao_para_executar(ag):
    sessao = SessaoFalsa()
    ag.mcp.encerrar()
    ag.mcp = cliente_falso(sessao)
    cerebro = usar(ag, CerebroFalso([[("rea__ler_strings", {"alvo": "a.exe"})],
                                     [("rea__executar_alvo", {"alvo": "a.exe"})],
                                     "O app usa a API X. Aprendizado: guarda o token no registro."],
                                    conferencia={"status": "concluido", "evidencia": "strings",
                                                 "resumo_falado": "Descobri como funciona.",
                                                 "conhecimento": "a.exe guarda o token no registro",
                                                 "etiquetas": ["a.exe", "strings"]}))
    agente = ag.agentes.iniciar("engenharia_reversa", "como o a.exe faz login?", "voz")
    esperar(lambda: agente.status == "aguardando")
    assert sessao.chamadas == [("ler_strings", {"alvo": "a.exe"})]  # leitura rodou direto; execução espera
    assert "rea__ler_strings" in cerebro.extras[0]["ferramentas"]
    ag.agentes.aprovar("engenharia reversa", ag.contexto("texto"), aprovar=False)
    esperar_fim(agente)
    assert [c[0] for c in sessao.chamadas] == ["ler_strings"]
    assert ("conhecimento", "a.exe guarda o token no registro", ["engenharia_reversa", "a.exe", "strings"],
            f"agente engenharia_reversa {agente.id}") in ag.memoria.aprendidos
    ag.mcp.encerrar()


def test_cliente_mcp_de_verdade_por_stdio(tmp_path):
    """Servidor MCP real (Python, stdio) — sem rede."""
    pytest.importorskip("mcp")
    try:
        from mcp.server.mcpserver import MCPServer as Servidor
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Servidor  # mcp 1.x
    assert Servidor
    script = tmp_path / "servidor_mcp.py"
    script.write_text(textwrap.dedent("""
        try:
            from mcp.server.mcpserver import MCPServer as Servidor
        except ImportError:
            from mcp.server.fastmcp import FastMCP as Servidor
        s = Servidor("teste")

        @s.tool()
        def somar(a: int, b: int) -> str:
            \"\"\"Soma dois números.\"\"\"
            return str(a + b)

        s.run()
    """), encoding="utf-8")
    arquivo = tmp_path / "mcp.yaml"
    arquivo.write_text(f"servidores:\n  calc:\n    comando: {json.dumps(sys.executable)}\n"
                       f"    args: [{json.dumps(str(script))}]\n    habilitado: true\n    nivel: livre\n",
                       encoding="utf-8")
    cliente = mcp_cliente.ClienteMCP(arquivo, tmp_path / "logs")
    try:
        ferramentas = cliente.ferramentas(["calc__*"])
        assert [f.nome_completo for f in ferramentas] == ["calc__somar"]
        assert cliente.chamar("calc__somar", {"a": 2, "b": 3}) == {"ok": True, "resumo": "5"}
    finally:
        cliente.encerrar()


# ---------------------------------------------------------------- ferramentas próprias

class Trabalho:
    def __init__(self, app, tmp_path):
        self.app = app
        self.id = "a1"
        self.pasta = tmp_path
        self.passos = []
        self._cancelado = False

    def cancelado(self):
        return self._cancelado

    def restante(self):
        return 600

    def passo(self, tipo, texto, ok=None, **extra):
        self.passos.append((tipo, texto))


def test_agent_browser_ausente_e_comando(ag, tmp_path, monkeypatch):
    trabalho = Trabalho(ag, tmp_path)
    monkeypatch.setattr(proprias.shutil, "which", lambda nome: None)
    assert proprias.rodar_agent_browser(trabalho, "open", "https://x.com")["resumo"] == proprias.SEM_AGENT_BROWSER
    vistos = []
    monkeypatch.setattr(proprias.shutil, "which", lambda nome: "/usr/bin/agent-browser")
    monkeypatch.setattr(proprias.subprocess, "run", lambda cmd, **k: vistos.append(cmd) or
                        SimpleNamespace(returncode=0, stdout="- button \"Entrar\" [ref=e1]", stderr=""))
    ferramentas = {f.nome: f for f in proprias.ferramentas_navegador()}
    assert ferramentas["navegador_abrir"].funcao(trabalho, url="exemplo.com")["ok"]
    ferramentas["navegador_preencher"].funcao(trabalho, alvo="@e3", texto="olá")
    assert vistos[0] == ["/usr/bin/agent-browser", "--session", "sexta-a1", "--content-boundaries", "--max-output",
                         str(proprias.MAX_SAIDA), "open", "https://exemplo.com"]
    assert vistos[1][-3:] == ["fill", "@e3", "olá"]
    assert ferramentas["navegador_abrir"].funcao(trabalho, url="file:///c:/x")["ok"] is False


def test_web_ler_converte_html_e_bloqueia_rede_local():
    titulo, texto = proprias.html_para_texto("<html><title>Oi &amp; tchau</title><script>x()</script>"
                                             "<p>Linha 1</p><p>Linha&nbsp;2</p></html>")
    assert titulo == "Oi & tchau" and texto == "Linha 1\nLinha 2"
    with pytest.raises(ValueError):
        proprias.ler_pagina("http://127.0.0.1:8765/api")
    assert proprias._link_real("//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.com%2Fb&rut=1") == "https://a.com/b"


def test_projetos_so_dentro_das_pastas(ag, tmp_path):
    raiz = tmp_path / "Projetos"
    (raiz / "Loja Virtual").mkdir(parents=True)
    with pytest.raises(ValueError, match="Nenhuma pasta"):
        proprias.resolver_projeto(ag, "loja")
    ag.prefs.atualizar({"projetos_pastas": [str(raiz)]})
    assert proprias.resolver_projeto(ag, "loja virtual") == (raiz / "Loja Virtual").resolve()
    assert proprias.resolver_projeto(ag, "loja") == (raiz / "Loja Virtual").resolve()
    with pytest.raises(ValueError, match="segurança"):
        proprias.resolver_projeto(ag, str(tmp_path))


def test_claude_code_headless(ag, tmp_path, monkeypatch):
    linhas = [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Plano: escrever o teste."}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit",
                                                        "input": {"file_path": "app.py"}}]}},
        {"type": "result", "subtype": "success", "is_error": False, "result": "Corrigi; 12 testes passando.",
         "num_turns": 5, "total_cost_usd": 0.1234},
    ]
    recebido = {}

    class Processo:
        def __init__(self, cmd, **k):
            recebido["cmd"], recebido["cwd"] = cmd, k["cwd"]
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("".join(json.dumps(l) + "\n" for l in linhas))
            self.stderr = io.StringIO("")
            self.returncode = 0
            self.pid = 1
            recebido["stdin"] = self.stdin
            self.stdin.close = lambda: recebido.setdefault("prompt", self.stdin.getvalue())

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(proprias.shutil, "which", lambda nome: "/bin/claude" if nome == "claude" else None)
    trabalho = Trabalho(ag, tmp_path)
    resultado = proprias.rodar_claude_code(trabalho, "corrigir o login", tmp_path, popen=Processo)
    assert resultado["ok"] and resultado["resumo"] == "Corrigi; 12 testes passando."
    assert resultado["arquivos"] == ["app.py"] and resultado["custo_usd"] == 0.1234
    cmd = recebido["cmd"]
    assert cmd[:8] == ["/bin/claude", "-p", "--output-format", "stream-json", "--verbose", "--permission-mode",
                       "acceptEdits", "--allowedTools"]
    assert "Bash(git status:*)" in cmd and "Bash" not in cmd  # Bash só com comandos restritos
    assert "verification-before-completion" in recebido["prompt"] and "corrigir o login" in recebido["prompt"]
    assert ("claude", "Edit app.py") in trabalho.passos


def test_claude_code_ausente(ag, tmp_path, monkeypatch):
    monkeypatch.setattr(proprias.shutil, "which", lambda nome: None)
    assert proprias.rodar_claude_code(Trabalho(ag, tmp_path), "x", tmp_path)["resumo"] == proprias.SEM_CLAUDE


def test_niveis_do_rea_pelo_yaml_padrao(tmp_path):
    import yaml

    dados = yaml.safe_load(mcp_cliente.MODELO_YAML)["servidores"]
    rea = mcp_cliente.ConfigServidor.de_dict("rea", dados["rea"])
    leitura = SimpleNamespace(read_only_hint=False, destructive_hint=False, open_world_hint=False)
    assert rea.nivel_de("binary_session", leitura) == LIVRE                       # só mexe na sessão do REA
    assert rea.nivel_de("analyze_web_bundle", SimpleNamespace(open_world_hint=True)) == CONFIRMAR  # processo/rede
    assert rea.nivel_de("run_target", SimpleNamespace(destructive_hint=True)) == CONFIRMAR
    assert rea.nivel_de("capture_process_scenario", SimpleNamespace(read_only_hint=True)) == CONFIRMAR
    chrome = mcp_cliente.ConfigServidor.de_dict("chrome-devtools", dados["chrome-devtools"])
    assert chrome.nivel_de("navigate_page") == LIVRE and chrome.nivel_de("evaluate_script") == CONFIRMAR
