"""Revisão de segurança do PC (Windows, sem administrador): portas abertas, conexões por processo,
programas que iniciam com o Windows, tarefas agendadas, processos sem assinatura ou rodando de pastas
temporárias, Defender, firewall, atualizações, UAC, Área de Trabalho Remota e extensões dos navegadores.

A coleta (``Coletor``) fica separada da avaliação (funções ``avaliar_*``), que só recebe dados: assim os
testes usam saídas simuladas do PowerShell. Nada aqui muda o sistema; as correções (desativar um item
da inicialização ou uma tarefa) são scripts montados aqui e executados pela extensão só depois do "sim".
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from . import padroes
from .arquivo import aspas_ps, nome_do_assinante

ORDEM_RISCO = {"alto": 0, "medio": 1, "baixo": 2, "ok": 3}
PARTES = ("protecao", "inicializacao", "tarefas", "portas", "conexoes", "processos", "extensoes")
MAX_ASSINATURAS = 80

PASTAS_SUSPEITAS = (("\\appdata\\local\\temp\\", "pasta temporária"), ("\\windows\\temp\\", "pasta temporária do Windows"),
                    ("\\downloads\\", "pasta Downloads"), ("\\users\\public\\", "pasta pública"),
                    ("\\$recycle.bin\\", "Lixeira"), ("\\perflogs\\", "pasta PerfLogs"))
PASTAS_DE_PROGRAMAS = ("\\program files\\", "\\program files (x86)\\", "\\windows\\", "\\programdata\\microsoft\\",
                       "\\windowsapps\\")
INTERPRETADORES = re.compile(r"\b(?:powershell|pwsh|wscript|cscript|mshta|rundll32|regsvr32|cmd)(?:\.exe)?\b", re.I)

PORTAS_CONHECIDAS = {
    3389: ("Área de Trabalho Remota (RDP)", "medio"), 5900: ("VNC (acesso remoto)", "medio"),
    5901: ("VNC (acesso remoto)", "medio"), 23: ("Telnet (sem criptografia)", "medio"), 21: ("FTP", "medio"),
    22: ("SSH (acesso remoto)", "baixo"), 5985: ("WinRM (administração remota)", "medio"),
    5986: ("WinRM (administração remota)", "medio"), 3306: ("banco MySQL", "medio"), 5432: ("banco PostgreSQL", "medio"),
    1433: ("banco SQL Server", "medio"), 27017: ("banco MongoDB", "medio"), 6379: ("Redis", "medio"),
    445: ("compartilhamento de arquivos (SMB)", "ok"), 139: ("compartilhamento de arquivos (NetBIOS)", "ok"),
    135: ("serviço RPC do Windows", "ok"), 5040: ("serviço do Windows", "ok"), 7680: ("Otimização de Entrega do Windows", "ok"),
}
PROCESSOS_DO_SISTEMA = {"system", "svchost.exe", "lsass.exe", "wininit.exe", "services.exe", "spoolsv.exe",
                        "smss.exe", "csrss.exe", "searchindexer.exe", "msmpeng.exe", "nissrv.exe", "system idle process"}
PERMISSOES_AMPLAS = {"<all_urls>", "*://*/*", "http://*/*", "https://*/*"}
PERMISSOES_SENSIVEIS = {"debugger": "controlar o navegador (debugger)", "nativeMessaging": "falar com programas do PC",
                        "webRequest": "ver o tráfego das páginas", "webRequestBlocking": "alterar o tráfego das páginas",
                        "cookies": "ler cookies", "proxy": "mudar o proxy", "management": "gerenciar outras extensões",
                        "clipboardRead": "ler a área de transferência", "history": "ler o histórico",
                        "declarativeNetRequest": "bloquear ou alterar requisições"}
LOJAS = ("clients2.google.com/service/update2/crx", "edge.microsoft.com/extensionwebstorebase")


@dataclass
class Item:
    id: str
    categoria: str
    titulo: str
    risco: str
    detalhe: str = ""
    evidencias: list[str] = field(default_factory=list)
    sugestao: str = ""
    acao: dict | None = None

    def como_dict(self) -> dict:
        return {"id": self.id, "categoria": self.categoria, "titulo": self.titulo, "risco": self.risco,
                "detalhe": self.detalhe, "evidencias": self.evidencias[:12], "sugestao": self.sugestao, "acao": self.acao}


def _risco_por_pontos(pontos: int, alto: int = 5, medio: int = 2) -> str:
    return "alto" if pontos >= alto else "medio" if pontos >= medio else "baixo"


def pasta_suspeita(caminho: str | None) -> str | None:
    """Nome da pasta suspeita onde o programa está ("pasta temporária"), ou ``None``."""
    if not caminho:
        return None
    baixo = "\\" + caminho.lower().replace("/", "\\")
    for trecho, nome in PASTAS_SUSPEITAS:
        if trecho in baixo:
            return nome
    partes = PureWindowsPath(caminho).parts
    if len(partes) >= 5 and [p.lower() for p in partes[-3:-1]] == ["appdata", "roaming"]:
        return "raiz da pasta AppData\\Roaming"
    return None


def pasta_de_programas(caminho: str | None) -> bool:
    return bool(caminho) and any(t in "\\" + caminho.lower().replace("/", "\\") for t in PASTAS_DE_PROGRAMAS)


def executavel_do_comando(comando: str) -> str:
    """ '"C:\\Program Files\\X\\x.exe" --min' -> 'C:\\Program Files\\X\\x.exe'."""
    comando = os.path.expandvars((comando or "").strip())
    if comando.startswith('"'):
        return comando[1:].split('"', 1)[0]
    m = re.match(r"(.+?\.(?:exe|bat|cmd|com|vbs|js|ps1|lnk|scr))(?:\s|$)", comando, re.I)
    return m.group(1) if m else comando.split(" ", 1)[0]


def avaliar_comando(comando: str) -> tuple[int, list[str]]:
    """Pontos de risco e motivos de uma linha de comando (inicialização ou tarefa agendada)."""
    pontos, motivos = 0, []
    exe = executavel_do_comando(comando)
    if pasta := pasta_suspeita(exe):
        pontos += 3
        motivos.append(f"roda de {pasta}")
    if INTERPRETADORES.search(comando):
        pontos += 2
        motivos.append("usa um interpretador de comandos (PowerShell, script ou rundll32)")
    for m in padroes.analisar_texto(comando, script=True):
        if m.peso > 0:
            pontos += m.peso
            motivos.append(m.texto)
    if pontos and pasta_de_programas(exe) and not INTERPRETADORES.search(comando):
        pontos -= 1
    return max(0, pontos), list(dict.fromkeys(motivos))


# -- leitura das saídas do PowerShell ---------------------------------------------------------------------
def _lista(valor: Any) -> list:
    if valor is None:
        return []
    return valor if isinstance(valor, list) else [valor]


def interpretar_json(saida: str) -> Any:
    try:
        return json.loads(saida or "null")
    except json.JSONDecodeError:
        inicio = min((i for i in (saida.find("{"), saida.find("[")) if i >= 0), default=-1)
        if inicio < 0:
            return None
        try:
            return json.loads(saida[inicio:])
        except json.JSONDecodeError:
            return None


def chave_aprovacao(local: str, comando: str, nome: str) -> tuple[str, str]:
    """(chave do registro StartupApproved, nome do valor) que liga/desliga um item como o Gerenciador de Tarefas."""
    base = "\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\"
    baixo = (local or "").lower()
    if baixo in ("startup", "common startup"):
        raiz = "HKCU:" if baixo == "startup" else "HKLM:"
        valor = comando if comando.lower().endswith(".lnk") else f"{nome}.lnk"
        return raiz + base + "StartupFolder", Path(valor).name
    raiz = "HKLM:" if baixo.startswith(("hklm", "hkey_local_machine")) else "HKCU:"
    return raiz + base + ("Run32" if "wow6432node" in baixo else "Run"), nome


def desativado(aprovados: dict, local: str, comando: str, nome: str) -> bool:
    chave, valor = chave_aprovacao(local, comando, nome)
    estado = (aprovados or {}).get(f"{chave}|{valor}")
    return estado is not None and int(estado) % 2 == 1  # 0x02/0x06 = ligado; 0x03/0x01 = desligado


def avaliar_inicializacao(dados: dict, assinaturas: dict[str, dict] | None = None) -> list[Item]:
    itens = []
    for i, entrada in enumerate(_lista(dados.get("inicializacao"))):
        nome, comando, local = entrada.get("Name") or "?", entrada.get("Command") or "", entrada.get("Location") or ""
        exe = executavel_do_comando(comando)
        if desativado(dados.get("aprovados") or {}, local, comando, nome):
            itens.append(Item(f"ini-{i}", "inicializacao", f"{nome} (desativado)", "ok", "Já está desativado.",
                              [comando], acao={"acao": "reativar_inicializacao", "nome": nome, "local": local,
                                               "comando": comando}))
            continue
        pontos, motivos = avaliar_comando(comando)
        assinatura = (assinaturas or {}).get(exe.lower())
        if assinatura and assinatura.get("status") == "NotSigned" and not pasta_de_programas(exe):
            pontos += 1
            motivos.append("o programa não tem assinatura digital")
        elif assinatura and assinatura.get("status") == "HashMismatch":
            pontos += 4
            motivos.append("a assinatura do programa não confere (foi alterado)")
        risco = _risco_por_pontos(pontos)
        detalhe = "; ".join(motivos) if motivos else "Programa instalado que abre junto com o Windows."
        if assinatura and assinatura.get("status") == "Valid":
            detalhe += f" Assinado por {assinatura.get('assinante') or '?'}."
        sugestao = ("Se não reconhece, desative da inicialização e analise o arquivo." if risco != "baixo" else
                    "Se não usa sempre, desativar deixa o Windows iniciar mais rápido.")
        itens.append(Item(f"ini-{i}", "inicializacao", nome, risco, detalhe, [comando, f"registro: {local}"], sugestao,
                          {"acao": "desativar_inicializacao", "nome": nome, "local": local, "comando": comando}))
    return itens


def avaliar_tarefas(dados: dict) -> list[Item]:
    itens, comuns = [], []
    for i, t in enumerate(_lista(dados.get("tarefas"))):
        nome, pasta_tarefa, acoes = t.get("Nome") or "?", t.get("Pasta") or "\\", (t.get("Acoes") or "").strip()
        if not acoes:
            continue  # tarefas só com ação COM: nada para avaliar pelo comando
        pontos, motivos = avaliar_comando(acoes)
        risco = _risco_por_pontos(pontos)
        if risco == "baixo":
            comuns.append(f"{pasta_tarefa}{nome}: {acoes[:160]}")
            continue
        itens.append(Item(f"tarefa-{i}", "tarefas", f"Tarefa agendada {nome}", risco, "; ".join(motivos),
                          [acoes, f"pasta: {pasta_tarefa}", f"autor: {t.get('Autor') or '?'}"],
                          "Se não reconhece, desative a tarefa e analise o programa que ela roda.",
                          {"acao": "desativar_tarefa", "nome": nome, "pasta": pasta_tarefa}))
    if comuns:
        itens.append(Item("tarefas-comuns", "tarefas", f"{len(comuns)} tarefas agendadas de programas instalados", "baixo",
                          "Atualizadores e manutenções de programas comuns.", comuns))
    return itens


def _decodificar_estado_av(estado: int) -> tuple[bool, bool]:
    """productState do Central de Segurança -> (ligado, atualizado)."""
    return bool(estado & 0x1000), not bool(estado & 0x10)


def avaliar_protecao(dados: dict, hoje: date | None = None) -> list[Item]:
    hoje = hoje or date.today()
    itens = []
    outros = []
    for av in _lista(dados.get("antivirus")):
        nome = av.get("displayName") or "?"
        if "defender" in nome.lower():
            continue
        ligado, atualizado = _decodificar_estado_av(int(av.get("productState") or 0))
        if ligado:
            outros.append(nome)
        itens.append(Item(f"av-{nome}", "protecao", f"Antivírus {nome}", "ok" if ligado and atualizado else "medio",
                          "Ligado." if ligado else "Desligado.", [f"productState {av.get('productState')}"],
                          "" if ligado and atualizado else f"Abra o {nome} e atualize ou ligue a proteção."))
    defender = dados.get("defender")
    if isinstance(defender, dict):
        tempo_real = defender.get("RealTimeProtectionEnabled")
        idade = defender.get("AntivirusSignatureAge")
        if tempo_real is False and not outros:
            itens.append(Item("defender-tempo-real", "protecao", "Proteção em tempo real do Defender desligada", "alto",
                              "Nenhum antivírus está vigiando o PC agora.", ["RealTimeProtectionEnabled = False"],
                              "Ligue em Segurança do Windows > Proteção contra vírus e ameaças.",
                              {"acao": "abrir_seguranca_windows"}))
        elif tempo_real is False:
            itens.append(Item("defender-tempo-real", "protecao", "Defender em modo passivo", "ok",
                              f"Outro antivírus cuida da proteção: {', '.join(outros)}."))
        else:
            itens.append(Item("defender-tempo-real", "protecao", "Proteção em tempo real do Defender ligada", "ok"))
        if isinstance(idade, int) and 7 < idade < 10_000 and tempo_real is not False:
            itens.append(Item("defender-definicoes", "protecao", "Definições do antivírus desatualizadas",
                              "alto" if idade > 30 else "medio", f"A última atualização foi há {idade} dias.",
                              [f"AntivirusSignatureAge = {idade}"], "Rode o Windows Update ou atualize pelo Defender.",
                              {"acao": "abrir_seguranca_windows"}))
        if defender.get("IsTamperProtected") is False and tempo_real is not False:
            itens.append(Item("defender-violacao", "protecao", "Proteção contra violação desligada", "baixo",
                              "Programas podem mudar as configurações do Defender.", ["IsTamperProtected = False"],
                              "Ligue em Segurança do Windows > Configurações de proteção contra vírus.",
                              {"acao": "abrir_seguranca_windows"}))
    elif dados.get("erro_defender") and not outros:
        itens.append(Item("defender-erro", "protecao", "Não consegui ler o estado do Defender", "baixo",
                          str(dados.get("erro_defender"))[:200]))
    desligados = [p.get("Name") for p in _lista(dados.get("firewall")) if str(p.get("Enabled")).lower() in ("false", "0")]
    if desligados:
        publico = any((n or "").lower() in ("public", "private") for n in desligados)
        itens.append(Item("firewall", "protecao", "Firewall desligado", "alto" if publico else "medio",
                          "Perfis desligados: " + ", ".join(desligados) + ".", [f"{n}: Enabled = False" for n in desligados],
                          "Ligue em Segurança do Windows > Firewall e proteção de rede.",
                          {"acao": "abrir_seguranca_windows"}))
    elif dados.get("firewall"):
        itens.append(Item("firewall", "protecao", "Firewall ligado em todos os perfis", "ok"))
    if ultima := dados.get("ultima_atualizacao"):
        try:
            dias = (hoje - datetime.strptime(str(ultima)[:10], "%Y-%m-%d").date()).days
        except ValueError:
            dias = -1
        if dias > 60:
            itens.append(Item("atualizacoes", "protecao", "Windows sem atualizações recentes", "alto" if dias > 120 else "medio",
                              f"A última atualização instalada foi há {dias} dias.",
                              [f"{dados.get('ultima_atualizacao_id') or 'KB?'} em {ultima}"],
                              "Abra o Windows Update e instale o que estiver pendente.", {"acao": "abrir_windows_update"}))
        elif dias >= 0:
            itens.append(Item("atualizacoes", "protecao", "Windows atualizado", "ok",
                              f"Última atualização há {dias} dia{'s' if dias != 1 else ''}."))
    if dados.get("uac") == 0:
        itens.append(Item("uac", "protecao", "Controle de Conta de Usuário (UAC) desligado", "alto",
                          "Programas ganham poderes de administrador sem perguntar.", ["EnableLUA = 0"],
                          "Ligue o UAC no Painel de Controle > Contas de Usuário."))
    if dados.get("rdp_negado") == 0:
        itens.append(Item("rdp", "protecao", "Área de Trabalho Remota ligada", "medio",
                          "O PC aceita acesso remoto. Se você não usa, é melhor desligar.", ["fDenyTSConnections = 0"],
                          "Desligue em Configurações > Sistema > Área de Trabalho Remota."))
    return itens


def _endereco_exposto(ip: str) -> bool:
    return ip in ("0.0.0.0", "::", "", "*") or not (ip.startswith("127.") or ip == "::1")


def avaliar_portas(conexoes: list[dict], pid_proprio: int | None = None) -> list[Item]:
    itens, internas, sistema = [], 0, []
    vistas: set[tuple] = set()
    for c in conexoes:
        if c.get("status") != "LISTEN":
            continue
        porta, ip, processo = c.get("lport"), c.get("lip") or "", (c.get("processo") or "?")
        chave = (processo.lower(), porta)
        if chave in vistas:
            continue
        vistas.add(chave)
        if not _endereco_exposto(ip):
            internas += 1
            continue
        conhecido, risco_porta = PORTAS_CONHECIDAS.get(porta, (None, None))
        exe = c.get("exe")
        if processo.lower() in PROCESSOS_DO_SISTEMA and risco_porta in (None, "ok"):
            sistema.append(f"{porta} ({processo}{', ' + conhecido if conhecido else ''})")
            continue
        if pid_proprio is not None and c.get("pid") == pid_proprio:
            itens.append(Item(f"porta-{porta}", "portas", f"Porta {porta}: a própria Sexta-Feira", "ok",
                              "O servidor do HUD (celular e navegador).", [f"{ip}:{porta}"]))
            continue
        pontos = 0
        motivos = []
        if pasta := pasta_suspeita(exe):
            pontos += 5
            motivos.append(f"o programa roda de {pasta}")
        if risco_porta == "medio":
            pontos += 2
            motivos.append(f"{conhecido} aberto para a rede")
        risco = _risco_por_pontos(pontos)
        titulo = f"Porta {porta} aberta por {processo}" + (f" ({conhecido})" if conhecido else "")
        detalhe = "; ".join(motivos) if motivos else "Aceita conexões de outros aparelhos da rede."
        itens.append(Item(f"porta-{porta}-{processo}", "portas", titulo, risco, detalhe,
                          [f"escutando em {ip or '*'}:{porta}", f"programa: {exe or processo}"],
                          "Se não reconhece, feche o programa ou bloqueie a porta no firewall." if risco != "baixo" else ""))
    if sistema:
        itens.append(Item("portas-sistema", "portas", f"{len(sistema)} portas de serviços do Windows", "ok",
                          "Normais em qualquer Windows (compartilhamento e serviços internos).", sistema))
    if internas:
        itens.append(Item("portas-internas", "portas", f"{internas} portas só para este PC", "ok",
                          "Escutam apenas no próprio computador (127.0.0.1): não ficam expostas à rede."))
    return itens


def _privado(ip: str) -> bool:
    import ipaddress

    try:
        endereco = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    return endereco.is_private or endereco.is_loopback or endereco.is_link_local


def resumir_conexoes(conexoes: list[dict]) -> list[dict]:
    """Por processo: quantas conexões com a internet, para quais endereços e portas."""
    por_processo: dict[str, dict] = {}
    for c in conexoes:
        if c.get("status") != "ESTABLISHED" or not c.get("rip") or _privado(c["rip"]):
            continue
        nome = c.get("processo") or "?"
        dados = por_processo.setdefault(nome.lower(), {"processo": nome, "exe": c.get("exe"), "pids": set(),
                                                       "conexoes": 0, "destinos": {}})
        dados["pids"].add(c.get("pid"))
        dados["conexoes"] += 1
        destino = f"{c['rip']}:{c.get('rport')}"
        dados["destinos"][destino] = dados["destinos"].get(destino, 0) + 1
    resumo = []
    for d in sorted(por_processo.values(), key=lambda d: -d["conexoes"]):
        resumo.append({"processo": d["processo"], "exe": d["exe"], "conexoes": d["conexoes"],
                       "destinos": sorted(d["destinos"], key=lambda k: -d["destinos"][k])[:8],
                       "portas": sorted({int(k.rsplit(":", 1)[1]) for k in d["destinos"] if k.rsplit(":", 1)[1].isdigit()})})
    return resumo


def avaliar_conexoes(resumo: list[dict], assinaturas: dict[str, dict] | None = None) -> list[Item]:
    itens = []
    for d in resumo:
        pontos, motivos = 0, []
        if pasta := pasta_suspeita(d.get("exe")):
            pontos += 5
            motivos.append(f"o programa roda de {pasta}")
        assinatura = (assinaturas or {}).get((d.get("exe") or "").lower())
        if assinatura and assinatura.get("status") == "HashMismatch":
            pontos += 4
            motivos.append("a assinatura do programa não confere")
        elif assinatura and assinatura.get("status") == "NotSigned" and not pasta_de_programas(d.get("exe")):
            pontos += 1
            motivos.append("o programa não tem assinatura digital")
        estranhas = [p for p in d["portas"] if p not in (80, 443, 853, 993, 995, 587, 465, 5222, 3478, 19302)]
        if estranhas and pontos:
            pontos += 1
            motivos.append("usa portas fora do comum (" + ", ".join(map(str, estranhas[:5])) + ")")
        risco = _risco_por_pontos(pontos, alto=5, medio=2)
        detalhe = f"{d['conexoes']} conexão{'ões' if d['conexoes'] != 1 else ''} com a internet"
        if motivos:
            detalhe += "; " + "; ".join(motivos)
        itens.append(Item(f"conexao-{d['processo']}", "conexoes", d["processo"], risco, detalhe + ".",
                          d["destinos"] + ([f"programa: {d['exe']}"] if d.get("exe") else []),
                          "Se não reconhece, analise o programa e bloqueie no firewall." if risco != "baixo" else ""))
    return itens


def avaliar_processos(processos: list[dict], assinaturas: dict[str, dict] | None = None) -> list[Item]:
    itens, sem_assinatura = [], []
    vistos: set[str] = set()
    for p in processos:
        exe = p.get("exe")
        if not exe or exe.lower() in vistos:
            continue
        vistos.add(exe.lower())
        assinatura = (assinaturas or {}).get(exe.lower()) or {}
        status = assinatura.get("status")
        pasta = pasta_suspeita(exe)
        if pasta or status == "HashMismatch":
            motivos = ([f"roda de {pasta}"] if pasta else []) + (["a assinatura não confere (o arquivo foi alterado)"]
                                                                  if status == "HashMismatch" else [])
            if status == "NotSigned":
                motivos.append("sem assinatura digital")
            risco = "alto" if status in ("NotSigned", "HashMismatch") else "medio"
            itens.append(Item(f"processo-{p.get('pid')}", "processos", f"{p.get('nome') or Path(exe).name} rodando agora",
                              risco, "; ".join(motivos) + ".", [exe, f"PID {p.get('pid')}"],
                              "Se não reconhece, peça para eu analisar o arquivo; feche o programa se for estranho.",
                              {"acao": "analisar", "caminho": exe}))
        elif status == "NotSigned" and not pasta_de_programas(exe):
            sem_assinatura.append(f"{p.get('nome') or Path(exe).name}: {exe}")
    if sem_assinatura:
        itens.append(Item("processos-sem-assinatura", "processos", f"{len(sem_assinatura)} programas abertos sem assinatura digital",
                          "baixo" if len(sem_assinatura) < 8 else "medio",
                          "Fora das pastas de programas e sem assinatura: comum em ferramentas pequenas e jogos, "
                          "mas vale conhecer cada um.", sem_assinatura))
    return itens


def avaliar_extensoes(extensoes: list[dict]) -> list[Item]:
    itens = []
    for e in extensoes:
        permissoes = set(e.get("permissoes") or [])
        amplas = permissoes & PERMISSOES_AMPLAS or {p for p in permissoes if p.endswith("://*/*")}
        sensiveis = [PERMISSOES_SENSIVEIS[p] for p in sorted(permissoes) if p in PERMISSOES_SENSIVEIS]
        pontos, motivos = 0, []
        if amplas:
            pontos += 1
            motivos.append("pode ler e alterar todos os sites")
        if amplas and sensiveis:
            pontos += 1
        if {"debugger", "nativeMessaging"} & permissoes:
            pontos += 1
        if not e.get("da_loja"):
            pontos += 2
            motivos.append("não veio da loja oficial")
        motivos += sensiveis[:4]
        risco = _risco_por_pontos(pontos, alto=4, medio=2)
        itens.append(Item(f"ext-{e.get('navegador')}-{e.get('id')}", "extensoes", f"{e.get('nome')} ({e.get('navegador')})",
                          risco, "; ".join(motivos) + "." if motivos else "Permissões comuns.",
                          sorted(permissoes)[:12] + [f"id: {e.get('id')}", f"versão: {e.get('versao')}"],
                          "Se não usa ou não reconhece, remova pela página de extensões do navegador." if risco != "baixo" else ""))
    return itens


# -- relatório -----------------------------------------------------------------------------------------
def montar_relatorio(itens: list[Item], *, conexoes: list[dict] | None = None, erros: list[str] | None = None,
                     partes: tuple[str, ...] = PARTES, agora: datetime | None = None) -> dict:
    lista = sorted((i.como_dict() for i in itens), key=lambda i: (ORDEM_RISCO.get(i["risco"], 9), i["categoria"]))
    contagem = {r: sum(1 for i in lista if i["risco"] == r) for r in ORDEM_RISCO}
    risco = "alto" if contagem["alto"] else "medio" if contagem["medio"] else "baixo"
    relatorio = {"tipo": "pc", "risco": risco, "itens": lista, "contagem": contagem, "partes": list(partes),
                 "conexoes": conexoes or [], "erros": erros or [],
                 "quando": (agora or datetime.now()).isoformat(timespec="seconds")}
    relatorio["veredito"] = veredito_pc(relatorio)
    return relatorio


def veredito_pc(r: dict) -> str:
    c = r["contagem"]
    altos = [i["titulo"] for i in r["itens"] if i["risco"] == "alto"]
    medios = [i["titulo"] for i in r["itens"] if i["risco"] == "medio"]
    if altos:
        lista = "; ".join(altos[:2])
        return (f"Encontrei {c['alto']} ponto{'s' if c['alto'] != 1 else ''} importante{'s' if c['alto'] != 1 else ''}: "
                f"{lista}. Os detalhes e o que fazer estão no holograma.")
    if medios:
        return (f"Nada grave, mas {c['medio']} ponto{'s' if c['medio'] != 1 else ''} merece{'m' if c['medio'] != 1 else ''} "
                f"atenção: {'; '.join(medios[:2])}. Detalhes no holograma.")
    return "Tudo em ordem: não vi nenhum problema de segurança no que consegui olhar sem administrador."


# -- scripts do PowerShell ------------------------------------------------------------------------------
_APROVADOS = ("'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run',"
              "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run32',"
              "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\StartupFolder',"
              "'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run',"
              "'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run32',"
              "'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\StartupFolder'")

BLOCOS_PS = {
    "inicializacao": (
        "try { $r.inicializacao = @(Get-CimInstance Win32_StartupCommand -ErrorAction Stop | "
        "Select-Object Name, Command, Location, User) } catch { $r.erro_inicializacao = $_.Exception.Message }; "
        "$a = @{}; foreach ($k in @(" + _APROVADOS + ")) { if (Test-Path $k) { $i = Get-Item $k; "
        "foreach ($n in $i.GetValueNames()) { $v = $i.GetValue($n); if ($v -is [byte[]] -and $v.Length -gt 0) "
        "{ $a[\"$k|$n\"] = [int]$v[0] } } } }; $r.aprovados = $a; "
    ),
    "tarefas": (
        "try { $r.tarefas = @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.State -ne 'Disabled' -and "
        "$_.TaskPath -notlike '\\Microsoft\\*' } | ForEach-Object { [pscustomobject]@{ Nome=$_.TaskName; "
        "Pasta=$_.TaskPath; Autor=$_.Author; Acoes=(@($_.Actions | Where-Object { $_.Execute } | "
        "ForEach-Object { ($_.Execute + ' ' + $_.Arguments).Trim() }) -join ' ; ') } }) } "
        "catch { $r.erro_tarefas = $_.Exception.Message }; "
    ),
    "protecao": (
        "try { $r.defender = Get-MpComputerStatus -ErrorAction Stop | Select-Object AMServiceEnabled, AntivirusEnabled, "
        "RealTimeProtectionEnabled, IsTamperProtected, AntivirusSignatureAge, QuickScanAge } "
        "catch { $r.erro_defender = $_.Exception.Message }; "
        "try { $r.antivirus = @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntivirusProduct "
        "-ErrorAction Stop | Select-Object displayName, productState) } catch { }; "
        "try { $r.firewall = @(Get-NetFirewallProfile -ErrorAction Stop | ForEach-Object { [pscustomobject]@{ "
        "Name=$_.Name; Enabled=$_.Enabled.ToString() } }) } catch { $r.erro_firewall = $_.Exception.Message }; "
        "try { $h = Get-HotFix -ErrorAction Stop | Where-Object { $_.InstalledOn } | Sort-Object InstalledOn "
        "-Descending | Select-Object -First 1; if ($h) { $r.ultima_atualizacao = $h.InstalledOn.ToString('yyyy-MM-dd'); "
        "$r.ultima_atualizacao_id = $h.HotFixID } } catch { }; "
        "try { $r.uac = [int](Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System' "
        "-ErrorAction Stop).EnableLUA } catch { }; "
        "try { $r.rdp_negado = [int](Get-ItemProperty 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server' "
        "-ErrorAction Stop).fDenyTSConnections } catch { }; "
    ),
}


def script_revisao(partes: tuple[str, ...]) -> str | None:
    blocos = [BLOCOS_PS[p] for p in partes if p in BLOCOS_PS]
    if not blocos:
        return None
    return "$r = [ordered]@{}; " + "".join(blocos) + "$r | ConvertTo-Json -Depth 4 -Compress"


def script_assinaturas(caminhos: list[str]) -> str:
    lista = aspas_ps(json.dumps(caminhos[:MAX_ASSINATURAS], ensure_ascii=False))
    return ("$l = '" + lista + "' | ConvertFrom-Json; @($l | ForEach-Object { try { $s = Get-AuthenticodeSignature "
            "-LiteralPath $_ -ErrorAction Stop; [pscustomobject]@{ Caminho=$_; Status=$s.Status.ToString(); "
            "Assinante=$(if($s.SignerCertificate){$s.SignerCertificate.Subject}) } } catch { } }) | ConvertTo-Json -Compress")


def interpretar_assinaturas(saida: str) -> dict[str, dict]:
    resultado = {}
    for item in _lista(interpretar_json(saida)):
        if isinstance(item, dict) and item.get("Caminho"):
            resultado[str(item["Caminho"]).lower()] = {"status": item.get("Status"),
                                                       "assinante": nome_do_assinante(item.get("Assinante"))}
    return resultado


def script_inicializacao(acao: str, local: str, comando: str, nome: str) -> str:
    """Desativa (ou reativa) um item da inicialização do jeito do Gerenciador de Tarefas: reversível."""
    chave, valor = chave_aprovacao(local, comando, nome)
    primeiro = 3 if acao == "desativar" else 2
    bytes_ps = ",".join(str(b) for b in [primeiro] + [0] * 11)
    return (f"$k = '{aspas_ps(chave)}'; if (-not (Test-Path $k)) {{ New-Item -Path $k -Force | Out-Null }}; "
            f"Set-ItemProperty -Path $k -Name '{aspas_ps(valor)}' -Value ([byte[]]({bytes_ps})) -Type Binary; 'ok'")


def script_tarefa(acao: str, nome: str, pasta: str) -> str:
    verbo = "Disable-ScheduledTask" if acao == "desativar" else "Enable-ScheduledTask"
    return f"{verbo} -TaskName '{aspas_ps(nome)}' -TaskPath '{aspas_ps(pasta or chr(92))}' -ErrorAction Stop | Out-Null; 'ok'"


# -- coleta -----------------------------------------------------------------------------------------------
class Coletor:
    """Coleta real no Windows (PowerShell e psutil). Os testes usam um dublê com os mesmos métodos."""

    def powershell(self, script: str, timeout: float = 90) -> str:
        from ...habilidades import windows

        return windows.powershell(script, timeout=timeout)

    def conexoes(self) -> list[dict]:
        import psutil

        nomes: dict[int, tuple[str, str | None]] = {}
        resultado = []
        for c in psutil.net_connections(kind="inet"):
            if c.pid and c.pid not in nomes:
                try:
                    processo = psutil.Process(c.pid)
                    nome = processo.name()
                    try:
                        exe = processo.exe() or None
                    except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
                        exe = None
                    nomes[c.pid] = (nome, exe)
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    nomes[c.pid] = ("?", None)
            nome, exe = nomes.get(c.pid, ("System" if c.pid == 4 else "?", None))
            resultado.append({"pid": c.pid, "processo": nome, "exe": exe, "status": c.status,
                              "lip": c.laddr.ip if c.laddr else "", "lport": c.laddr.port if c.laddr else None,
                              "rip": c.raddr.ip if c.raddr else "", "rport": c.raddr.port if c.raddr else None})
        return resultado

    def processos(self) -> list[dict]:
        import psutil

        lista = []
        for p in psutil.process_iter(["pid", "name", "exe"]):
            info = p.info
            lista.append({"pid": info.get("pid"), "nome": info.get("name"), "exe": info.get("exe")})
        return lista

    def assinaturas(self, caminhos: list[str]) -> dict[str, dict]:
        if not caminhos:
            return {}
        return interpretar_assinaturas(self.powershell(script_assinaturas(caminhos), timeout=120))

    def extensoes(self) -> list[dict]:
        return listar_extensoes(Path(os.environ.get("LOCALAPPDATA", "")))


NAVEGADORES = {"Chrome": "Google/Chrome/User Data", "Edge": "Microsoft/Edge/User Data",
               "Brave": "BraveSoftware/Brave-Browser/User Data"}


def _mensagem_locale(pasta: Path, chave: str) -> str | None:
    for idioma in ("pt_BR", "pt_PT", "en", "en_US"):
        arquivo = pasta / "_locales" / idioma / "messages.json"
        if arquivo.is_file():
            try:
                mensagens = json.loads(arquivo.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            achada = next((v for k, v in mensagens.items() if k.lower() == chave.lower()), None)
            if achada and achada.get("message"):
                return achada["message"]
    return None


def listar_extensoes(local_appdata: Path) -> list[dict]:
    """Extensões instaladas no Chrome, Edge e Brave (lendo o manifest.json de cada uma; nada é aberto)."""
    extensoes = []
    if not str(local_appdata) or not local_appdata.is_dir():
        return extensoes
    for navegador, relativo in NAVEGADORES.items():
        dados = local_appdata / relativo
        if not dados.is_dir():
            continue
        perfis = [p for p in dados.iterdir() if p.is_dir() and (p.name == "Default" or p.name.startswith("Profile "))]
        vistas: set[str] = set()
        for perfil in perfis:
            pasta_ext = perfil / "Extensions"
            if not pasta_ext.is_dir():
                continue
            for ext in pasta_ext.iterdir():
                versoes = sorted((v for v in ext.iterdir() if (v / "manifest.json").is_file()), key=lambda v: v.name) \
                    if ext.is_dir() else []
                if not versoes or ext.name in vistas:
                    continue
                vistas.add(ext.name)
                pasta = versoes[-1]
                try:
                    manifesto = json.loads((pasta / "manifest.json").read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError):
                    continue
                nome = str(manifesto.get("name") or ext.name)
                if nome.startswith("__MSG_"):
                    nome = _mensagem_locale(pasta, nome[6:].rstrip("_")) or nome
                permissoes = [p for p in (manifesto.get("permissions") or []) + (manifesto.get("host_permissions") or [])
                              if isinstance(p, str)]
                for script in manifesto.get("content_scripts") or []:
                    permissoes += [m for m in script.get("matches") or [] if isinstance(m, str)]
                atualizacao = str(manifesto.get("update_url") or "")
                extensoes.append({"navegador": navegador, "id": ext.name, "nome": nome,
                                  "versao": manifesto.get("version"), "permissoes": sorted(set(permissoes)),
                                  "da_loja": any(loja in atualizacao for loja in LOJAS)})
    return extensoes


def revisar(coletor: Coletor, partes: tuple[str, ...] = PARTES, pid_proprio: int | None = None,
            agora: datetime | None = None) -> dict:
    """Roda as partes pedidas e monta o relatório (cada parte que falha vira um erro, não derruba o resto)."""
    itens: list[Item] = []
    erros: list[str] = []
    dados: dict = {}
    script = script_revisao(partes)
    if script:
        try:
            dados = interpretar_json(coletor.powershell(script)) or {}
        except Exception as erro:  # noqa: BLE001 - PowerShell ausente, tempo esgotado...
            erros.append(f"PowerShell: {erro}")
        for chave in ("erro_inicializacao", "erro_tarefas", "erro_firewall"):
            if dados.get(chave):
                erros.append(f"{chave.removeprefix('erro_')}: {dados[chave]}")
    conexoes: list[dict] = []
    if {"portas", "conexoes"} & set(partes):
        try:
            conexoes = coletor.conexoes()
        except Exception as erro:  # noqa: BLE001 - psutil sem permissão
            erros.append(f"conexões de rede: {erro}")
    processos: list[dict] = []
    if "processos" in partes:
        try:
            processos = coletor.processos()
        except Exception as erro:  # noqa: BLE001
            erros.append(f"processos: {erro}")
    resumo_rede = resumir_conexoes(conexoes) if "conexoes" in partes else []

    # assinaturas só dos programas fora do Windows (os do sistema são do próprio Windows)
    caminhos = []
    for entrada in _lista(dados.get("inicializacao")):
        caminhos.append(executavel_do_comando(entrada.get("Command") or ""))
    caminhos += [d.get("exe") for d in resumo_rede]
    caminhos += [p.get("exe") for p in processos]
    unicos = list(dict.fromkeys(c for c in caminhos if c and c.lower().endswith(".exe")
                                and "\\windows\\" not in c.lower().replace("/", "\\")))
    assinaturas: dict[str, dict] = {}
    if unicos:
        try:
            assinaturas = coletor.assinaturas(unicos)
        except Exception as erro:  # noqa: BLE001
            erros.append(f"assinaturas: {erro}")

    if "protecao" in partes:
        itens += avaliar_protecao(dados)
    if "inicializacao" in partes:
        itens += avaliar_inicializacao(dados, assinaturas)
    if "tarefas" in partes:
        itens += avaliar_tarefas(dados)
    if "portas" in partes:
        itens += avaliar_portas(conexoes, pid_proprio)
    if "conexoes" in partes:
        itens += avaliar_conexoes(resumo_rede, assinaturas)
    if "processos" in partes:
        itens += avaliar_processos(processos, assinaturas)
    if "extensoes" in partes:
        try:
            itens += avaliar_extensoes(coletor.extensoes())
        except Exception as erro:  # noqa: BLE001
            erros.append(f"extensões: {erro}")
    return montar_relatorio(itens, conexoes=resumo_rede, erros=erros, partes=partes, agora=agora)
