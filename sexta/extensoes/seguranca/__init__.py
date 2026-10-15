"""Segurança: análise estática de arquivos e revisão de segurança do PC — só defensiva, no PC do próprio usuário.

"Analisa o arquivo setup.exe", "o último download é seguro?", "esse programa é seguro?", "o Discord é
seguro?", "revisa a segurança do PC", "quem está usando a internet?", "o que inicia com o Windows?",
"quais portas estão abertas?", "consulta no VirusTotal".

Análise de arquivo (``arquivo.py``): hashes, tipo real pelos primeiros bytes, PE do Windows (arquitetura,
data de compilação, seções e entropia, importações agrupadas por capacidade), assinatura digital
(``Get-AuthenticodeSignature``), strings interessantes, Electron/ASAR, .NET, ZIP, documentos com macros e
scripts com padrões perigosos. O alvo nunca é executado. O resultado é um veredito (baixo, médio ou alto
risco) com motivos, evidências e os limites da análise estática. VirusTotal (opcional, ``VIRUSTOTAL_API_KEY``):
só o hash sai do PC, e só depois do "sim".

Revisão do PC (``pc.py``, Windows, sem administrador): portas abertas, conexões por processo, inicialização,
tarefas agendadas, processos sem assinatura ou em pastas temporárias, Defender, firewall, atualizações, UAC,
Área de Trabalho Remota e extensões dos navegadores. Correções (desativar um item da inicialização ou
uma tarefa) pedem confirmação e são reversíveis.

Cada análise vira ``conhecimento`` na memória e fica no histórico ``dados/analises.json`` (últimas 50).
As ferramentas começam com ``seguranca_``; o agente de engenharia reversa (extensão ``agentes``) usa as mesmas.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Callable

from ...cerebro.ferramentas import CONFIRMAR, LIVRE, P
from ...util.texto import remover_ativacao
from . import arquivo, padroes, pc
from .arquivo import ErroAnalise
from .servico import Seguranca, chave_virustotal, frase_virustotal

log = logging.getLogger(__name__)

PREFERENCIAS = {"seguranca_revisao_semanal": False, "seguranca_virustotal": True}
HOLOGRAMAS = {"seguranca": "Segurança"}

PARTES_FERRAMENTA = ["tudo", *pc.PARTES]
ACOES_CORRECAO = ["desativar_inicializacao", "reativar_inicializacao", "desativar_tarefa", "reativar_tarefa",
                  "abrir_seguranca_windows", "abrir_windows_update"]
ABRIR = {"abrir_seguranca_windows": ("windowsdefender:", "Abrindo a Segurança do Windows."),
         "abrir_windows_update": ("ms-settings:windowsupdate", "Abrindo o Windows Update.")}


# -- respostas faladas -----------------------------------------------------------------------------
def _lista_falada(nomes: list[str], limite: int = 5) -> str:
    nomes = [n for n in nomes if n]
    if not nomes:
        return ""
    mostrados = nomes[:limite]
    texto = ", ".join(mostrados[:-1]) + (" e " if len(mostrados) > 1 else "") + mostrados[-1]
    if len(nomes) > limite:
        texto += f", e mais {len(nomes) - limite}"
    return texto


def resumo_parte(r: dict, parte: str) -> str:
    """O que falar depois de revisar uma parte do PC."""
    itens = r["itens"]
    atencao = [i["titulo"] for i in itens if i["risco"] in ("alto", "medio")]
    alerta = f" Merece{'m' if len(atencao) > 1 else ''} atenção: {_lista_falada(atencao, 3)}." if atencao else ""
    if r["erros"] and not itens:
        return "Não consegui fazer a revisão: " + r["erros"][0]
    if parte == "conexoes":
        usando = [f"{c['processo'].removesuffix('.exe')} ({c['conexoes']})" for c in r["conexoes"]]
        if not usando:
            return "Nenhum programa está conectado à internet agora."
        return f"Usando a internet agora: {_lista_falada(usando)}.{alerta}"
    if parte == "inicializacao":
        ligados = [i["titulo"] for i in itens if i["categoria"] == "inicializacao" and i["risco"] != "ok"]
        if not ligados:
            return "Nenhum programa está configurado para iniciar com o Windows."
        return f"Iniciam com o Windows: {_lista_falada(ligados, 8)}.{alerta}"
    if parte == "portas":
        abertas = [i["titulo"].removeprefix("Porta ") for i in itens if i["categoria"] == "portas" and i["id"].startswith("porta-")
                   and i["risco"] != "ok"]
        if not abertas:
            return "Nenhuma porta aberta para a rede além das do próprio Windows."
        return f"Portas abertas para a rede: {_lista_falada(abertas)}.{alerta}"
    return r["veredito"]


def _resposta_analise(r: dict) -> dict:
    resumo = r["veredito"]
    if chave_virustotal() and r["categoria"] in ("pe", "script", "ole", "lnk", "zip") and r["risco"] != "baixo":
        resumo += " Se quiser, consulto o hash no VirusTotal."
    return {"ok": True, "resumo": resumo, "analise": arquivo.resumo_curto(r)}


# -- protocolos ---------------------------------------------------------------------------------------
def _passo_revisao(app, valor, ctx, variaveis) -> None:
    app.fala.falar(app.registro.executar("seguranca_revisar_pc", {"parte": "tudo"}, ctx)["resumo"])


ACOES_PROTOCOLO = {
    "revisao_seguranca": {"rotulo": "Revisão de segurança do PC", "entrada": "nenhum",
                          "dica": "portas, inicialização, Defender, firewall e atualizações",
                          "executar": _passo_revisao},
}


# -- ganchos ------------------------------------------------------------------------------------------
def instalar(app) -> None:
    app.seguranca = Seguranca(app, app.cfg.dados)


def _descrever_correcao(args: dict) -> str:
    nome = args.get("nome") or "o item"
    return {"desativar_inicializacao": f"desativar {nome} da inicialização do Windows (dá para reativar depois)",
            "reativar_inicializacao": f"reativar {nome} na inicialização do Windows",
            "desativar_tarefa": f"desativar a tarefa agendada {nome} (dá para reativar depois)",
            "reativar_tarefa": f"reativar a tarefa agendada {nome}"}.get(args.get("acao"), "fazer a correção")


def _nivel_virustotal(app) -> Callable[[dict], int]:
    def nivel(_args: dict) -> int:
        # sem chave (ou desligado em Ajustes) nada sai do PC: responde na hora explicando
        return CONFIRMAR if chave_virustotal() and app.prefs.get("seguranca_virustotal", True) else LIVRE
    return nivel


def registrar(app, registro) -> None:
    seg: Seguranca = app.seguranca

    @registro.ferramenta(
        "seguranca_analisar_arquivo",
        "Análise estática de segurança de um arquivo do usuário, SEM executá-lo: hashes, tipo real, programa do Windows "
        "(importações por capacidade, seções, entropia, .NET, Electron), assinatura digital, strings e scripts perigosos. "
        "Devolve o veredito (baixo, médio ou alto risco) com motivos. Use para 'esse arquivo/programa é seguro?'. "
        "Informe caminho (completo, só o nome, que é procurado em Downloads/Área de Trabalho/Documentos, ou "
        "'último download') OU programa (nome de um programa aberto, ou 'janela_ativa'). Responda com o veredito, "
        "sem afirmar que é vírus sem evidência.",
        caminho=P("string", "Caminho ou nome do arquivo, ou 'último download'."),
        programa=P("string", "Nome de um programa aberto (ex.: 'discord') ou 'janela_ativa'."),
    )
    def seguranca_analisar_arquivo(ctx, caminho: str | None = None, programa: str | None = None):
        try:
            alvo = seg.programa(programa) if programa and not caminho else seg.resolver_arquivo(caminho or "")
            return _resposta_analise(seg.analisar(alvo))
        except ErroAnalise as erro:
            return {"ok": False, "resumo": str(erro)}

    @registro.ferramenta(
        "seguranca_revisar_pc",
        "Revisão de segurança do PC (Windows, sem administrador). parte: tudo; protecao (Defender, firewall, "
        "atualizações, UAC, acesso remoto); inicializacao (o que inicia com o Windows); tarefas (agendadas); portas "
        "(abertas e quem escuta); conexoes (quem está usando a internet); processos (sem assinatura ou em pastas "
        "temporárias); extensoes (dos navegadores). Mostra o relatório no holograma.",
        direta=True,
        parte=P("string", "Parte a revisar (padrão: tudo).", enum=PARTES_FERRAMENTA),
    )
    def seguranca_revisar_pc(ctx, parte: str | None = None):
        parte = parte if parte in PARTES_FERRAMENTA else "tudo"
        partes = pc.PARTES if parte == "tudo" else (parte,)
        try:
            r = seg.revisar(partes)
        except ErroAnalise as erro:
            return {"ok": False, "resumo": str(erro)}
        itens = [f"[{i['risco']}] {i['titulo']}: {i['detalhe']}" for i in r["itens"] if i["risco"] != "ok"][:15]
        return {"ok": True, "resumo": resumo_parte(r, parte), "itens": itens, "erros": r["erros"]}

    @registro.ferramenta(
        "seguranca_corrigir",
        "Correções sugeridas pela revisão de segurança: desativar_inicializacao/reativar_inicializacao (nome, local, "
        "comando do item), desativar_tarefa/reativar_tarefa (nome, pasta da tarefa agendada), abrir_seguranca_windows, "
        "abrir_windows_update. Desativar é reversível e pede confirmação.",
        direta=True,
        nivel=lambda a: LIVRE if a.get("acao") in ABRIR else CONFIRMAR,
        descrever=_descrever_correcao,
        acao=P("string", "Correção.", enum=ACOES_CORRECAO, obrigatorio=True),
        nome=P("string", "Nome do item da inicialização ou da tarefa."),
        local=P("string", "Local do item da inicialização (como veio da revisão)."),
        comando=P("string", "Comando do item da inicialização (como veio da revisão)."),
        pasta=P("string", "Pasta da tarefa agendada (ex.: '\\\\')."),
    )
    def seguranca_corrigir(ctx, acao: str, nome: str | None = None, local: str | None = None,
                           comando: str | None = None, pasta: str | None = None):
        return corrigir(app, acao, nome or "", local or "", comando or "", pasta or "\\")

    @registro.ferramenta(
        "seguranca_virustotal",
        "Consulta no VirusTotal o hash (SHA-256) de um arquivo já analisado. Só o hash sai do PC, nunca o arquivo. "
        "Sem argumentos, usa o último arquivo analisado.",
        direta=True,
        nivel=_nivel_virustotal(app),
        descrever=lambda a: (f"consultar no VirusTotal o hash de {a.get('caminho') or 'último arquivo analisado'} "
                             "(só o hash sai do PC)"),
        caminho=P("string", "Arquivo (caminho ou nome); vazio = o último analisado."),
        sha256=P("string", "Hash SHA-256, se já souber."),
    )
    def seguranca_virustotal(ctx, caminho: str | None = None, sha256: str | None = None):
        if not app.prefs.get("seguranca_virustotal", True):
            return {"ok": False, "resumo": "A consulta ao VirusTotal está desligada em Ajustes, na seção Segurança."}
        try:
            if not chave_virustotal():
                raise ErroAnalise("Para consultar o VirusTotal, crie uma chave grátis em virustotal.com e coloque "
                                  "VIRUSTOTAL_API_KEY no arquivo .env.")
            nome = "o arquivo"
            if not sha256:
                if caminho:
                    alvo = seg.resolver_arquivo(caminho)
                    sha256, nome = arquivo.hashes(alvo)["sha256"], alvo.name
                else:
                    ultima = seg.ultima_analise_de_arquivo()
                    if ultima is None:
                        raise ErroAnalise("Ainda não analisei nenhum arquivo. Diga qual.")
                    sha256, nome = ultima["sha256"], ultima["arquivo"]
            vt = seg.virustotal(sha256)
        except (ErroAnalise, OSError) as erro:
            return {"ok": False, "resumo": str(erro)}
        seg.registrar_virustotal(sha256, vt)
        return {"ok": True, "resumo": frase_virustotal(nome, vt), "virustotal": vt}

    @registro.ferramenta(
        "seguranca_historico",
        "Histórico das análises de segurança feitas (arquivos e revisões do PC), para perguntas como 'aquele "
        "instalador que você analisou ontem era assinado?'. busca filtra por nome do arquivo, hash ou risco.",
        busca=P("string", "Trecho do nome do arquivo, hash ou risco; vazio = as mais recentes."),
    )
    def seguranca_historico(ctx, busca: str | None = None):
        achados = seg.buscar(busca or "")
        if not achados:
            return {"ok": True, "resumo": "Não encontrei nenhuma análise com isso no histórico."}
        linhas = []
        for h in achados:
            if h["tipo"] == "arquivo":
                vt = h.get("virustotal")
                linhas.append(f"{h['quando']}: {h['arquivo']} ({h['descricao']}), risco {h['risco']}, assinatura "
                              f"{(h.get('assinatura') or {}).get('texto')}"
                              + (f" por {h['assinatura']['assinante']}" if (h.get('assinatura') or {}).get('assinante') else "")
                              + (f", VirusTotal {vt.get('maliciosos')}/{vt.get('total')}" if vt and vt.get("conhecido") else "")
                              + f", caminho {h['caminho']}")
            else:
                linhas.append(f"{h['quando']}: revisão do PC, risco {h['risco']}: {h['veredito']}")
        return {"ok": True, "resumo": " | ".join(linhas), "analises": linhas}

    @registro.ferramenta(
        "seguranca_strings",
        "Textos legíveis de dentro de um arquivo binário (como o 'strings'), filtrados por um trecho. Só leitura.",
        caminho=P("string", "Caminho ou nome do arquivo.", obrigatorio=True),
        filtro=P("string", "Trecho a procurar (ex.: 'http', 'HKEY', '.dll')."),
    )
    def seguranca_strings(ctx, caminho: str, filtro: str | None = None):
        try:
            alvo = seg.resolver_arquivo(caminho)
            with open(alvo, "rb") as f:
                textos = padroes.extrair_strings(f.read(arquivo.LER_STRINGS_MAX))
        except (ErroAnalise, OSError) as erro:
            return {"ok": False, "resumo": str(erro)}
        achadas = padroes.filtrar_strings(textos, filtro) if filtro else padroes.strings_interessantes(textos)
        return {"ok": True, "resumo": f"{len(textos)} textos em {alvo.name}.", "strings": achadas}

    @registro.ferramenta(
        "seguranca_asar",
        "Lista os arquivos de um pacote Electron (app.asar, ou a pasta/exe do app) ou lê um arquivo de dentro dele, "
        "sem executar nada. Útil para entender como um app Electron funciona.",
        caminho=P("string", "app.asar, o .exe do app ou a pasta dele.", obrigatorio=True),
        filtro=P("string", "Trecho do caminho para filtrar a lista (ex.: '.js', 'preload')."),
        ler=P("string", "Caminho interno de um arquivo para ler (ex.: 'package.json')."),
    )
    def seguranca_asar(ctx, caminho: str, filtro: str | None = None, ler: str | None = None):
        try:
            alvo = _achar_asar(seg.resolver_arquivo(caminho))
            if ler:
                return {"ok": True, "resumo": f"Conteúdo de {ler}.", "conteudo": arquivo.ler_arquivo_asar(alvo, ler)}
            cabecalho, _ = arquivo.ler_asar(alvo)
            itens = arquivo.listar_asar(cabecalho)
        except (ErroAnalise, OSError) as erro:
            return {"ok": False, "resumo": str(erro)}
        lista = [f"{i['caminho']} ({i['tamanho']} bytes)" for i in itens if not filtro or filtro.lower() in i["caminho"].lower()]
        return {"ok": True, "resumo": f"{len(itens)} arquivos em {alvo}.", "arquivos": lista[:300]}


def _achar_asar(caminho: Path) -> Path:
    if caminho.suffix.lower() == ".asar":
        return caminho
    pasta = caminho if caminho.is_dir() else caminho.parent
    achado = arquivo.electron_vizinho(pasta / "x.exe")
    if achado is None:
        raise ErroAnalise(f"Não achei o app.asar de {caminho.name}: não parece um app Electron.")
    return achado


def corrigir(app, acao: str, nome: str, local: str, comando: str, pasta: str) -> dict:
    from ...habilidades import windows

    if acao in ABRIR:
        destino, frase = ABRIR[acao]
        try:
            _abrir(destino)
        except (windows.NaoSuportado, OSError) as erro:
            return {"ok": False, "resumo": str(erro)}
        return {"ok": True, "resumo": frase}
    if not nome:
        return {"ok": False, "resumo": "Qual item? Diga o nome como aparece na revisão."}
    desativar = acao.startswith("desativar")
    try:
        if acao.endswith("inicializacao"):
            script = pc.script_inicializacao("desativar" if desativar else "reativar", local, comando, nome)
        else:
            script = pc.script_tarefa("desativar" if desativar else "reativar", nome, pasta)
        windows.powershell(script, timeout=30)
    except windows.NaoSuportado as erro:
        return {"ok": False, "resumo": str(erro)}
    except OSError as erro:
        if re.search(r"acess|access|permiss|negad|denied", str(erro), re.I):
            onde = "Gerenciador de Tarefas, aba Aplicativos de inicialização" if acao.endswith("inicializacao") else \
                "Agendador de Tarefas"
            return {"ok": False, "resumo": f"Esse item é do sistema todo e precisa de administrador. Faça pelo {onde}."}
        return {"ok": False, "resumo": f"O Windows não deixou: {erro}"}
    if acao.endswith("inicializacao"):
        app.seguranca.marcar_corrigido({"acao": acao, "nome": nome, "local": local},
                                       f"{nome} (desativado)" if desativar else nome)
        frase = f"Pronto, {nome} não inicia mais com o Windows." if desativar else f"{nome} volta a iniciar com o Windows."
    else:
        app.seguranca.marcar_corrigido({"acao": acao, "nome": nome}, f"Tarefa {nome} (desativada)" if desativar else nome)
        frase = f"Tarefa {nome} desativada." if desativar else f"Tarefa {nome} reativada."
    return {"ok": True, "resumo": frase}


def _abrir(destino: str) -> None:
    import os

    from ...habilidades import windows

    if not windows.WINDOWS:
        raise windows.NaoSuportado("Essa ação só funciona no Windows.")
    os.startfile(destino)  # noqa: S606 - URI fixa do próprio Windows


# -- atalhos (sem IA) ---------------------------------------------------------------------------------
_VERBO_ANALISAR = r"(?:analisa|analise|analisar|verifica|verifique|verificar|checa|cheque|checar|examina|examine|escaneia|escaneie)"
_ANALISAR = re.compile(rf"^{_VERBO_ANALISAR}(?: pra mim| para mim)? (?:o |a |esse |essa |este |esta |aquele )?"
                       r"(arquivo|programa|instalador|executavel|script) (.+)$")
_ANALISAR_ORIGINAL = re.compile(r"(?:arquivo|programa|instalador|execut[aá]vel|script)\s+(.+?)[\s?!.]*$", re.I)
_ULTIMO = re.compile(rf"^(?:{_VERBO_ANALISAR}(?: o| a)? (?:ultimo download|ultimo arquivo baixado|ultimo arquivo que (?:eu )?baixei)|"
                     r"(?:o )?ultimo (?:download|arquivo baixado|arquivo que (?:eu )?baixei) (?:e|eh) (?:seguro|confiavel|perigoso|virus))$")
_ARQUIVO_SEGURO = re.compile(r"^(?:o |esse |este )?arquivo (.+) (?:e|eh) (?:seguro|confiavel|perigoso|um virus|virus)$")
_ARQUIVO_SEGURO_ORIGINAL = re.compile(r"arquivo\s+(.+?)\s+(?:é|e|eh)\s+(?:seguro|confi[aá]vel|perigoso|um v[ií]rus|v[ií]rus)", re.I)
_ESSE_PROGRAMA = re.compile(r"^(?:esse|este|o) (?:programa|app|aplicativo)(?: aberto| da tela| na tela)? (?:e|eh) "
                            r"(?:seguro|confiavel)$|^(?:analisa|verifica|checa) (?:esse|este) (?:programa|app|aplicativo)$")
_PROGRAMA_SEGURO = re.compile(r"^(?:o |a )?([a-z0-9][a-z0-9 ]{1,29}) (?:e|eh) (?:seguro|confiavel)$")
_NAO_PROGRAMAS = {"isso", "isto", "aqui", "ele", "ela", "esse", "este", "site", "link", "pix", "email", "wifi", "meu pc",
                  "computador", "pc", "meu computador", "o pc", "esse site", "esse link", "esse email"}
_REVISAR = re.compile(r"^(?:(?:revisa|revise|revisar|verifica|verifique|checa|cheque|analisa|analise|faz|faca|roda|rode)"
                      r"(?: uma| a)? (?:revisao de |analise de )?seguranca(?: (?:do|no|deste|desse|do meu|no meu) "
                      r"(?:pc|computador|notebook|sistema|windows))?|revisao de seguranca(?: (?:do|no) (?:meu )?"
                      r"(?:pc|computador|notebook))?|(?:o |meu )?(?:pc|computador|notebook) (?:esta|ta) seguro)$")
_INTERNET = re.compile(r"^(?:quem|que programas?|quais programas?|o que|qual programa|quais apps?)(?: que)?"
                       r"(?: esta| estao| ta| tao)? (?:usando|acessando|conectad[oa]s? (?:a|na|com a)) (?:a )?(?:internet|rede)"
                       r"(?: agora)?$")
_INICIALIZACAO = re.compile(r"^(?:o que|que programas?|quais programas?|quais apps?|quais aplicativos)(?: que)? "
                            r"(?:inicia|iniciam|abre|abrem|liga|ligam|comeca|comecam|roda|rodam) (?:junto )?(?:com|quando) "
                            r"(?:o )?(?:windows|pc|computador)(?: liga| inicia)?$|^(?:quais (?:sao )?(?:os )?)?programas "
                            r"(?:na|da) inicializacao$")
_PORTAS = re.compile(r"^(?:quais |que )?portas (?:estao |tao )?abertas(?: no (?:meu )?(?:pc|computador))?$")
_HOLOGRAMA = re.compile(r"^(?:abre|abrir|mostra|mostrar)(?: o| a| as)? (?:painel de |central de |historico de |analises de )?"
                        r"seguranca$|^(?:abre|mostra)(?: o| as)? (?:historico das )?analises de seguranca$")
_VIRUSTOTAL = re.compile(r"^(?:consulta|consultar|confere|conferir|checa|checar|verifica|verificar|olha|joga|manda)"
                         r"(?: isso| esse arquivo| o hash| ele)?(?: no| pelo| na) virus ?total$")


def _argumento(original: str | None, regex: re.Pattern, normalizado: str) -> str:
    if original:
        achado = regex.search(remover_ativacao(original))
        if achado:
            return achado.group(1).strip().strip("\"'“”")
    return normalizado


def atalho(t: str, ctx, rodar, original: str | None) -> Callable[[], str] | None:
    if _ULTIMO.match(t):
        return rodar("seguranca_analisar_arquivo", {"caminho": "último download"})
    if _ESSE_PROGRAMA.match(t):
        return rodar("seguranca_analisar_arquivo", {"programa": "janela_ativa"})
    if m := _ANALISAR.match(t):
        if m.group(2) in ("aberto", "da tela", "na tela"):
            return rodar("seguranca_analisar_arquivo", {"programa": "janela_ativa"})
        alvo = _argumento(original, _ANALISAR_ORIGINAL, m.group(2))
        if m.group(1) == "programa" and not re.search(r"[\\/.]", alvo):  # "analisa o programa discord": o aberto
            return rodar("seguranca_analisar_arquivo", {"programa": alvo})
        return rodar("seguranca_analisar_arquivo", {"caminho": alvo})
    if m := _ARQUIVO_SEGURO.match(t):
        return rodar("seguranca_analisar_arquivo", {"caminho": _argumento(original, _ARQUIVO_SEGURO_ORIGINAL, m.group(1))})
    if _REVISAR.match(t):
        return rodar("seguranca_revisar_pc", {"parte": "tudo"})
    if _INTERNET.match(t):
        return rodar("seguranca_revisar_pc", {"parte": "conexoes"})
    if _INICIALIZACAO.match(t):
        return rodar("seguranca_revisar_pc", {"parte": "inicializacao"})
    if _PORTAS.match(t):
        return rodar("seguranca_revisar_pc", {"parte": "portas"})
    if _VIRUSTOTAL.match(t):
        return rodar("seguranca_virustotal", {})
    if _HOLOGRAMA.match(t):
        return rodar("holograma", {"acao": "mostrar", "tipo": "seguranca"})
    if (m := _PROGRAMA_SEGURO.match(t)) and m.group(1) not in _NAO_PROGRAMAS:
        try:
            ctx.app.seguranca.programa(m.group(1))
        except Exception:  # noqa: BLE001 - não é um programa aberto (ou psutil falhou): a IA responde
            return None
        return rodar("seguranca_analisar_arquivo", {"programa": m.group(1)})
    return None


# -- rotas HTTP ---------------------------------------------------------------------------------------
def rotas(api, app, autenticado, so_pc) -> None:
    from fastapi import Body, Depends, HTTPException

    seg: Seguranca = app.seguranca

    def _executar(cliente, nome: str, args: dict) -> dict:
        if cliente.tipo == "pc" and app.sessao.bloqueada:
            raise HTTPException(423, "A Sexta-Feira está bloqueada. Olhe para a câmera ou use o PIN.")
        ctx = app.contexto("texto" if cliente.tipo == "pc" else "celular", cliente)
        resultado = app.registro.executar(nome, args, ctx)
        return {"texto": resultado["resumo"], "ok": resultado["ok"], "pendente": bool(resultado.get("pendente"))}

    @api.get("/api/seguranca/estado")
    async def estado_seguranca(_=Depends(autenticado)):
        return await asyncio.to_thread(seg.estado)

    @api.get("/api/seguranca/historico")
    async def historico_seguranca(_=Depends(autenticado)):
        return {"historico": seg.resumo_historico()}

    @api.get("/api/seguranca/analise/{id_}")
    async def analise_seguranca(id_: str, _=Depends(autenticado)):
        achada = seg.obter(id_)
        if achada is None:
            raise HTTPException(404, "Análise não encontrada.")
        return achada

    @api.post("/api/seguranca/mostrar")
    async def mostrar_seguranca(corpo: dict = Body(...), _=Depends(autenticado)):
        achada = seg.obter(str(corpo.get("id") or ""))
        if achada is None:
            raise HTTPException(404, "Análise não encontrada.")
        seg.mostrar(achada)
        return {"ok": True}

    @api.post("/api/seguranca/analisar")
    async def analisar_seguranca(corpo: dict = Body(...), cliente=Depends(so_pc)):
        caminho = str(corpo.get("caminho") or "").strip()[:1000]
        if not caminho:
            raise HTTPException(400, "Diga qual arquivo.")
        return await asyncio.to_thread(_executar, cliente, "seguranca_analisar_arquivo", {"caminho": caminho})

    @api.post("/api/seguranca/revisar")
    async def revisar_seguranca(corpo: dict = Body(default={}), cliente=Depends(autenticado)):
        parte = corpo.get("parte") if corpo.get("parte") in PARTES_FERRAMENTA else "tudo"
        return await asyncio.to_thread(_executar, cliente, "seguranca_revisar_pc", {"parte": parte})

    @api.post("/api/seguranca/corrigir")
    async def corrigir_seguranca(corpo: dict = Body(...), cliente=Depends(so_pc)):
        if corpo.get("acao") not in ACOES_CORRECAO:
            raise HTTPException(400, "Correção inválida.")
        args = {k: str(corpo[k])[:500] for k in ("acao", "nome", "local", "comando", "pasta") if corpo.get(k)}
        return await asyncio.to_thread(_executar, cliente, "seguranca_corrigir", args)

    @api.post("/api/seguranca/virustotal")
    async def virustotal_seguranca(corpo: dict = Body(default={}), cliente=Depends(so_pc)):
        achada = seg.obter(str(corpo.get("id") or "")) if corpo.get("id") else None
        args = {"sha256": achada["sha256"], "caminho": achada["arquivo"]} if achada and achada.get("sha256") else {}
        return await asyncio.to_thread(_executar, cliente, "seguranca_virustotal", args)


def dados_holograma(app, tipo: str) -> dict | None:
    return app.seguranca.dados_holograma() if tipo == "seguranca" else None


def diagnostico(app) -> list[dict]:
    from ...habilidades import windows
    from . import pe

    itens = []
    if windows.WINDOWS:
        ok = shutil.which("powershell") is not None
        itens.append({"nome": "PowerShell (segurança)", "ok": ok,
                      "detalhe": "assinaturas e revisão do PC" if ok else "powershell.exe não encontrado",
                      "dica": "" if ok else "O PowerShell vem com o Windows: confira se C:\\Windows\\System32\\WindowsPowerShell\\v1.0 está no PATH"})
    else:
        itens.append({"nome": "PowerShell (segurança)", "ok": False, "detalhe": "só no Windows",
                      "dica": "A revisão do PC e a assinatura digital só funcionam no Windows"})
    tem_pefile = pe.pefile_disponivel()
    itens.append({"nome": "pefile (análise de programas)", "ok": tem_pefile,
                  "detalhe": "instalado" if tem_pefile else "usando o leitor próprio (mais simples)",
                  "dica": "" if tem_pefile else "pip install pefile"})
    vt = bool(chave_virustotal())
    itens.append({"nome": "VirusTotal (opcional)", "ok": True,
                  "detalhe": "chave configurada (só o hash é enviado, com confirmação)" if vt else "sem chave",
                  "dica": "" if vt else "Crie uma chave grátis em virustotal.com e ponha VIRUSTOTAL_API_KEY no .env"})
    return itens


def iniciar(app) -> None:
    app.seguranca.iniciar()


def encerrar(app) -> None:
    app.seguranca.encerrar()

