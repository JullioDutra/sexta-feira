"""Fase 1: segurança em níveis, atalhos novos, arquivos, terminal e registro de atividades."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from sexta.cerebro.agente import Agente, interpretar_confirmacao
from sexta.habilidades import arquivos as mod_arquivos
from sexta.habilidades.arquivos import Arquivos, interpretar_consulta
from sexta.habilidades.janelas import Janela, escolher_janela, retangulo_destino
from sexta.habilidades.terminal import Terminal

from test_agente import OllamaFalso, cliente


def sem_ia(app):
    """Agente com um Ollama que falha se for chamado: prova que o pedido não passou pela IA."""
    app.agente = Agente(app, cliente(OllamaFalso([])))
    return app.agente


# ---------------------------------------------------------------- confirmação em níveis

def test_fechar_pede_confirmacao_e_sim_executa(app, monkeypatch):
    fechados = []
    monkeypatch.setattr(app.apps, "fechar", lambda nome: (fechados.append(nome), (True, f"Fechando {nome}."))[1])
    agente = sem_ia(app)
    r = agente.processar("fecha o chrome")
    assert r["texto"] == "Confirma: fechar chrome?" and fechados == []
    r = agente.processar("pode")
    assert fechados == ["chrome"] and r["texto"] == "Fechando chrome."
    assert app.registro.pendente() is None


def test_nao_cancela_e_mudar_de_assunto_descarta(app, monkeypatch):
    fechados = []
    monkeypatch.setattr(app.apps, "fechar", lambda nome: (fechados.append(nome), (True, "ok"))[1])
    agente = sem_ia(app)
    agente.processar("fecha o discord")
    assert agente.processar("não")["texto"] == "Tudo bem, cancelado."
    agente.processar("fecha o discord")
    agente.processar("que horas são")  # outro assunto: a ação pendente cai
    assert app.registro.pendente() is None and fechados == []
    situacoes = [a["situacao"] for a in app.atividades.listar()]
    assert "cancelada" in situacoes and "aguardando" in situacoes


def test_nivel_rosto_nega_sem_reconhecer(app, monkeypatch):
    energia = []
    monkeypatch.setattr("sexta.habilidades.windows.energia", lambda acao: energia.append(acao))
    monkeypatch.setattr(app, "verificar_para_acao", lambda ctx: (False, "Não reconheci você, então não fiz."))
    agente = sem_ia(app)
    r = app.registro.executar("computador", {"acao": "desligar"}, app.contexto())
    assert "Vou conferir seu rosto" in r["resumo"]
    r = agente.processar("sim")
    assert r["texto"] == "Não reconheci você, então não fiz." and energia == []

    monkeypatch.setattr(app, "verificar_para_acao", lambda ctx: (True, ""))
    app.registro.executar("computador", {"acao": "desligar"}, app.contexto())
    agente.processar("confirmo")
    assert energia == ["desligar"]


def test_pendente_expira(app, monkeypatch):
    app.registro.executar("computador", {"acao": "reiniciar"}, app.contexto())
    agora = time.time()
    monkeypatch.setattr("sexta.cerebro.ferramentas.time.time", lambda: agora + 10**4)
    assert app.registro.pendente() is None


def test_rotina_nao_pede_confirmacao(app, monkeypatch):
    fechados = []
    monkeypatch.setattr(app.apps, "fechar", lambda nome: (fechados.append(nome), (True, "ok"))[1])
    monkeypatch.setattr("sexta.habilidades.windows.definir_volume", lambda v: v)
    app.rotinas._executar(app.rotinas.obter("modo foco"), app.contexto())
    assert fechados == ["Discord"] and app.registro.pendente() is None


@pytest.mark.parametrize("texto,esperado", [
    ("sim", True), ("Pode sim.", True), ("confirmo", True), ("Sexta-feira, pode.", True), ("manda ver", True),
    ("não", False), ("cancela", False), ("melhor não", False),
    ("abre o spotify", None), ("sim e abre o spotify", None),
])
def test_interpretar_confirmacao(texto, esperado):
    assert interpretar_confirmacao(texto) is esperado


# ---------------------------------------------------------------- atalhos sem IA

def test_abrir_e_volume_compostos_sem_ia(app, monkeypatch):
    abertos, volumes = [], []
    monkeypatch.setattr(app.apps, "abrir", lambda alvo: (abertos.append(alvo), (True, f"Abrindo {alvo}."))[1])
    monkeypatch.setattr("sexta.habilidades.windows.definir_volume", lambda v: volumes.append(v) or v)
    r = sem_ia(app).processar("Abre o YouTube e coloca o volume em 30, por favor")
    assert abertos == ["youtube"] and volumes == [30]
    assert r["texto"] == "Abrindo youtube. Volume em 30%." and r["caminho"] == "atalho"


def test_composto_com_parte_desconhecida_vai_inteiro_para_ia(app, monkeypatch):
    abertos = []
    monkeypatch.setattr(app.apps, "abrir", lambda alvo: (abertos.append(alvo), (True, "ok"))[1])
    falso = OllamaFalso([httpx.Response(200, content=b'{"message": {"content": "Certo."}, "done": true}\n')])
    app.agente = Agente(app, cliente(falso))
    r = app.agente.processar("abre o youtube e me conta uma piada")
    assert r["caminho"] == "ia" and abertos == []  # nada rodou pela metade


@pytest.mark.parametrize("frase,ferramenta,args", [
    ("brilho 70", "configuracao", {"item": "brilho", "valor": "70"}),
    ("aumenta o brilho", "configuracao", {"item": "brilho", "valor": "mais"}),
    ("desliga o wi-fi", "configuracao", {"item": "wifi", "valor": "desligar"}),
    ("liga o bluetooth", "configuracao", {"item": "bluetooth", "valor": "ligar"}),
    ("ativa o modo escuro", "configuracao", {"item": "modo_escuro", "valor": "ligar"}),
    ("volta pro modo claro", "configuracao", {"item": "modo_escuro", "valor": "desligar"}),
    ("não perturbe", "configuracao", {"item": "nao_perturbe", "valor": "ligar"}),
    ("coloca o pc no modo desempenho máximo", "configuracao", {"item": "plano_energia", "valor": "desempenho maximo"}),
    ("muda o som para o fone", "configuracao", {"item": "saida_audio", "valor": "fone"}),
    ("o que está pesando no pc?", "processos", {"acao": "mais_pesados", "ordem": "cpu"}),
    ("qual programa está usando mais memória", "processos", {"acao": "mais_pesados", "ordem": "ram"}),
    ("consumo de gpu por app", "processos", {"acao": "mais_pesados", "ordem": "gpu"}),
    ("fecha os programas travados", "processos", {"acao": "fechar_travados"}),
    ("arquivos recentes", "arquivos", {"acao": "recentes"}),
    ("organiza a pasta de downloads por data", "arquivos", {"acao": "organizar_downloads", "por_data": True}),
    ("analisa a tela", "ver", {"fonte": "tela"}),
    ("o que é isso?", "ver", {"fonte": "camera"}),
    ("minimiza tudo", "janelas", {"acao": "minimizar_tudo"}),
    ("coloca o vs code na esquerda", "janelas", {"acao": "encaixar", "app": "vs code", "posicao": "esquerda"}),
    ("manda o chrome pro outro monitor", "janelas", {"acao": "mover_monitor", "app": "chrome"}),
    ("minimiza o spotify", "janelas", {"acao": "minimizar", "app": "spotify"}),
    ("salva esse layout como estudo", "janelas", {"acao": "salvar_layout", "app": "estudo"}),
    ("layout trabalho", "janelas", {"acao": "aplicar_layout", "app": "trabalho"}),
    ("pesquisa receita de pão de queijo", "pesquisar", {"termo": "receita de pao de queijo", "onde": "google"}),
    ("toca legião urbana no youtube", "tocar_youtube", {"busca": "legiao urbana"}),
    ("mostra o registro de atividades", "holograma", {"acao": "mostrar", "tipo": "atividades"}),
    ("fecha o clima", "holograma", {"acao": "fechar", "tipo": "clima"}),
])
def test_atalhos_fase1(app, monkeypatch, frase, ferramenta, args):
    chamadas = []

    def executar_falso(nome, argumentos, ctx, **_):
        chamadas.append((nome, argumentos))
        return {"ok": True, "resumo": "ok"}

    monkeypatch.setattr(app.registro, "executar", executar_falso)
    resposta = sem_ia(app).processar(frase)
    assert resposta["caminho"] == "atalho", frase
    nome, argumentos = chamadas[0]
    assert nome == ferramenta
    for chave, valor in args.items():
        assert argumentos.get(chave) == valor, (frase, argumentos)


def test_lado_a_lado(app, monkeypatch):
    chamadas = []
    monkeypatch.setattr(app.registro, "executar",
                        lambda nome, a, ctx, **_: chamadas.append(a) or {"ok": True, "resumo": "ok"})
    assert sem_ia(app).processar("coloca o vs code e o chrome lado a lado")["texto"] == "Lado a lado."
    assert [(c["app"], c["posicao"]) for c in chamadas] == [("vs code", "esquerda"), ("chrome", "direita")]


def test_focar_e_fechar_so_viram_atalho_se_existem(app, monkeypatch):
    monkeypatch.setattr("sexta.cerebro.atalhos._janela_aberta", lambda nome: nome == "spotify")
    chamadas = []
    monkeypatch.setattr(app.registro, "executar",
                        lambda nome, a, ctx, **_: chamadas.append((nome, a)) or {"ok": True, "resumo": "ok"})
    resposta_ia = lambda: httpx.Response(200, content=b'{"message": {"content": "Certo."}, "done": true}\n')
    app.agente = Agente(app, cliente(OllamaFalso([resposta_ia(), resposta_ia()])))
    assert app.agente.processar("foca no spotify")["caminho"] == "atalho"
    assert app.agente.processar("traz as notícias de hoje")["caminho"] == "ia"
    assert app.agente.processar("fecha a conta do restaurante")["caminho"] == "ia"


def test_abrir_desconhecido_vai_para_ia(app):
    falso = OllamaFalso([httpx.Response(200, content=b'{"message": {"content": "Vou procurar."}, "done": true}\n')])
    app.agente = Agente(app, cliente(falso))
    assert app.agente.processar("abre o pdf do contrato de março")["caminho"] == "ia"


# ---------------------------------------------------------------- arquivos

@pytest.fixture
def pasta_usuario(tmp_path, monkeypatch):
    casa = tmp_path / "casa"
    for nome in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"):
        (casa / nome).mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: casa))
    monkeypatch.delenv("OneDrive", raising=False)
    return casa


def criar(caminho: Path, quando: datetime | None = None, conteudo: str = "x") -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(conteudo)
    if quando:
        ts = quando.timestamp()
        os.utime(caminho, (ts, ts))
    return caminho


def test_interpretar_consulta():
    agora = datetime(2026, 10, 9)
    f = interpretar_consulta("acha o PDF do contrato de março", agora=agora)
    assert f.termos == ["contrato"] and f.extensoes == {".pdf"}
    assert datetime.fromtimestamp(f.desde) == datetime(2026, 3, 1) and datetime.fromtimestamp(f.ate) == datetime(2026, 4, 1)
    f = interpretar_consulta("planilha de gastos de novembro", agora=agora)
    assert f.termos == ["gastos"] and ".xlsx" in f.extensoes
    assert datetime.fromtimestamp(f.desde).year == 2025  # novembro ainda não chegou este ano


def test_buscar_arquivo_por_tipo_e_mes(app, pasta_usuario):
    docs = pasta_usuario / "Documents"
    criar(docs / "Contrato aluguel.pdf", datetime(2026, 3, 12))
    criar(docs / "contrato aluguel rascunho.docx", datetime(2026, 3, 12))
    criar(docs / "Contrato antigo.pdf", datetime(2025, 1, 5))
    criar(pasta_usuario / "Downloads" / "foto praia.jpg", datetime(2026, 3, 12))
    arq = Arquivos()
    achados = arq.buscar("o pdf do contrato de março")
    assert [Path(a.caminho).name for a in achados] == ["Contrato aluguel.pdf"]
    assert arq.resolver("1") == docs / "Contrato aluguel.pdf"


def test_ferramenta_buscar_e_abrir_pelo_numero(app, pasta_usuario, monkeypatch):
    criar(pasta_usuario / "Documents" / "relatorio vendas.xlsx")
    app.arquivos = Arquivos()
    abertos = []
    monkeypatch.setattr("sexta.habilidades.windows.abrir_no_sistema", abertos.append)
    r = app.registro.executar("arquivos", {"acao": "buscar", "alvo": "planilha de vendas"}, app.contexto())
    assert r["ok"] and "relatorio vendas.xlsx" in r["resumo"]
    r = app.registro.executar("arquivos", {"acao": "abrir", "alvo": "1"}, app.contexto())
    assert r["resumo"] == "Abrindo relatorio vendas.xlsx." and abertos[0].endswith("relatorio vendas.xlsx")


def test_organizar_downloads(app, pasta_usuario):
    dl = pasta_usuario / "Downloads"
    antigo = datetime(2026, 9, 1)
    criar(dl / "nota.pdf", antigo)
    criar(dl / "foto.png", antigo)
    criar(dl / "setup.exe", antigo)
    criar(dl / "coisa.xyz", antigo)
    criar(dl / "baixando.crdownload", antigo)
    criar(dl / "agora.pdf")  # recém-baixado: fica onde está
    contagem = Arquivos().organizar_downloads(por_data=True)
    assert contagem == {"PDFs": 1, "Imagens": 1, "Instaladores": 1, "Outros": 1}
    assert (dl / "PDFs" / "2026-09" / "nota.pdf").exists()
    assert (dl / "agora.pdf").exists() and (dl / "baixando.crdownload").exists()


def test_mover_e_renomear_so_na_pasta_do_usuario(app, pasta_usuario, tmp_path):
    arquivo = criar(pasta_usuario / "Downloads" / "boleto.pdf")
    arq = Arquivos()
    final = arq.mover(str(arquivo), "Documentos")
    assert final == pasta_usuario / "Documents" / "boleto.pdf"
    final = arq.renomear(str(final), "boleto outubro")
    assert final.name == "boleto outubro.pdf"
    fora = criar(tmp_path / "sistema" / "config.ini")
    with pytest.raises(mod_arquivos.ErroArquivos):
        arq.mover(str(fora), "Documentos")


def test_mover_pede_confirmacao_e_apagar_pede_rosto(app, pasta_usuario):
    criar(pasta_usuario / "Downloads" / "x.pdf")
    app.arquivos = Arquivos()
    r = app.registro.executar("arquivos", {"acao": "mover", "alvo": "x", "destino": "Documentos"}, app.contexto())
    assert r["pendente"] and "Vou conferir" not in r["resumo"]
    r = app.registro.executar("arquivos", {"acao": "apagar", "alvo": "x"}, app.contexto())
    assert r["pendente"] and "Vou conferir seu rosto" in r["resumo"]


# ---------------------------------------------------------------- terminal

def test_terminal_lista_permitida(tmp_path):
    t = Terminal(tmp_path / "nao_existe.yaml")
    assert t.permitido("ipconfig")
    assert t.permitido("ping google.com")
    assert t.permitido("git status")
    assert not t.permitido("git push")
    assert not t.permitido("ipconfig & del /q C:\\")
    assert not t.permitido("ping x | findstr y")
    assert not t.permitido("winget upgrade --all")
    assert not t.permitido("echo %USERPROFILE%")


def test_terminal_fora_da_lista_exige_rosto(app):
    r = app.registro.executar("terminal", {"comando": "rmdir /s /q C:\\pasta"}, app.contexto())
    assert r["pendente"] and "rodar o comando" in r["resumo"]
    r = app.registro.executar("terminal", {"comando": "hostname"}, app.contexto())
    assert "pendente" not in r and "saida" in r


# ---------------------------------------------------------------- janelas (lógica independente do Windows)

def test_escolher_janela():
    janelas = [Janela(1, "Sexta-Feira", "msedge"), Janela(2, "projeto - Visual Studio Code", "code"),
               Janela(3, "YouTube - Google Chrome", "chrome"), Janela(4, "Spotify Premium", "spotify")]
    assert escolher_janela("navegador", janelas).hwnd == 3  # ignora o HUD
    assert escolher_janela("o VS Code", janelas).hwnd == 2
    assert escolher_janela("spotify", janelas).hwnd == 4
    assert escolher_janela("youtube", janelas).hwnd == 3
    assert escolher_janela("photoshop", janelas) is None


def test_retangulo_destino():
    area = (0, 0, 1920, 1040)
    assert retangulo_destino("esquerda", area) == (0, 0, 960, 1040)
    assert retangulo_destino("inferior_direita", area) == (960, 520, 960, 520)
    assert retangulo_destino({"x": .25, "y": 0, "l": .5, "a": 1}, (1920, 0, 3840, 1080)) == (2400, 0, 960, 1080)


# ---------------------------------------------------------------- registro de atividades

def test_registro_de_atividades(app, monkeypatch):
    monkeypatch.setattr("sexta.habilidades.windows.definir_volume", lambda v: v)
    eventos = []
    app.barramento.ouvir(lambda e: eventos.append(e["tipo"]))
    app.registro.executar("holograma", {"acao": "mostrar", "tipo": "atividades"}, app.contexto())
    app.registro.executar("ajustar_volume", {"acao": "definir", "valor": 20}, app.contexto("celular"))
    item = app.atividades.listar()[0]
    assert item["ferramenta"] == "ajustar_volume" and item["canal"] == "celular" and item["situacao"] == "ok"
    assert "atividade" in eventos
    holo = next(h for h in app.hologramas.lista() if h["tipo"] == "atividades")
    assert holo["dados"]["itens"][0]["resumo"] == "Volume em 20%."
    linhas = (app.cfg.dados / "atividades.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 1  # holograma (consulta) não polui o registro
    assert "1 ações" in app.atividades.resumo_de_hoje()
