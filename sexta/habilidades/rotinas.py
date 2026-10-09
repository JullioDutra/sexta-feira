"""Protocolos (rotinas 2.0): gatilho → condições → ações.

Exemplo em YAML::

    modo valorant:
      gatilhos:
        - app_aberto: Valorant
      condicoes:
        - entre: "18:00-23:59"
        - em_reuniao: false
      passos:
        - fechar: Chrome
        - plano_energia: desempenho maximo

Os protocolos escritos à mão ficam em ``config/rotinas.yaml``. Os criados por voz
ou no editor do HUD vão para ``config/rotinas_criadas.yaml``. O formato antigo
(``frases``, ``horario`` e ``dias`` no topo) continua valendo.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ..util.texto import normalizar

log = logging.getLogger(__name__)

DIAS = {"seg": 0, "segunda": 0, "ter": 1, "terca": 1, "qua": 2, "quarta": 2, "qui": 3, "quinta": 3,
        "sex": 4, "sexta": 4, "sab": 5, "sabado": 5, "dom": 6, "domingo": 6}
NOMES_DIAS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]

# Ações que a IA e o editor podem usar (sem "executar", que roda comandos do sistema)
ACOES_SEGURAS = ["falar", "abrir", "fechar", "tocar_youtube", "pesquisar", "volume", "midia", "esperar",
                 "clima", "noticias", "briefing", "lembretes", "holograma", "print", "bloquear",
                 "layout", "minimizar_tudo", "plano_energia", "nao_perturbe", "modo_escuro", "organizar_downloads",
                 "brilho", "notificar", "mover_arquivo"]
ACOES = ACOES_SEGURAS + ["executar"]
GATILHOS = ["frase", "horario", "desbloquear", "app_aberto", "app_fechado", "bateria_baixa", "pendrive",
            "arquivo_novo", "wifi", "voltar_ao_pc"]
CONDICOES = ["dias", "entre", "em_reuniao", "chovendo", "wifi"]
AUTOMATICOS = set(GATILHOS) - {"frase"}

# Catálogo para o editor visual do HUD e para a IA (rótulo, tipo de entrada, dica)
CATALOGO: dict[str, list[dict[str, Any]]] = {
    "gatilhos": [
        {"tipo": "frase", "rotulo": "Quando eu disser", "entrada": "texto", "dica": "modo estudo"},
        {"tipo": "horario", "rotulo": "No horário", "entrada": "hora", "dica": "07:30"},
        {"tipo": "desbloquear", "rotulo": "Ao desbloquear o PC", "entrada": "nenhum"},
        {"tipo": "app_aberto", "rotulo": "Quando abrir o app", "entrada": "texto", "dica": "Valorant"},
        {"tipo": "app_fechado", "rotulo": "Quando fechar o app", "entrada": "texto", "dica": "Valorant"},
        {"tipo": "bateria_baixa", "rotulo": "Bateria abaixo de (%)", "entrada": "numero", "dica": "20"},
        {"tipo": "pendrive", "rotulo": "Pendrive conectado", "entrada": "texto", "dica": "(qualquer)"},
        {"tipo": "arquivo_novo", "rotulo": "Arquivo novo na pasta", "entrada": "texto", "dica": "Downloads"},
        {"tipo": "wifi", "rotulo": "Conectar na rede Wi-Fi", "entrada": "texto", "dica": "(qualquer)"},
        {"tipo": "voltar_ao_pc", "rotulo": "Quando eu voltar ao PC (min fora)", "entrada": "numero", "dica": "5"},
    ],
    "condicoes": [
        {"tipo": "dias", "rotulo": "Nos dias", "entrada": "dias"},
        {"tipo": "entre", "rotulo": "Entre os horários", "entrada": "intervalo", "dica": "18:00-23:59"},
        {"tipo": "em_reuniao", "rotulo": "Em reunião", "entrada": "bool"},
        {"tipo": "chovendo", "rotulo": "Chovendo", "entrada": "bool"},
        {"tipo": "wifi", "rotulo": "Na rede Wi-Fi", "entrada": "texto", "dica": "MinhaCasa"},
    ],
    "acoes": [
        {"tipo": "falar", "rotulo": "Falar", "entrada": "texto", "dica": "Bom trabalho, chefe."},
        {"tipo": "notificar", "rotulo": "Notificar no celular", "entrada": "texto", "dica": "Chegou um arquivo: {nome_arquivo}"},
        {"tipo": "abrir", "rotulo": "Abrir", "entrada": "texto", "dica": "Spotify"},
        {"tipo": "fechar", "rotulo": "Fechar programa", "entrada": "texto", "dica": "Chrome"},
        {"tipo": "layout", "rotulo": "Layout de janelas", "entrada": "texto", "dica": "trabalho"},
        {"tipo": "minimizar_tudo", "rotulo": "Minimizar tudo", "entrada": "nenhum"},
        {"tipo": "volume", "rotulo": "Volume", "entrada": "texto", "dica": "30 ou mudo"},
        {"tipo": "midia", "rotulo": "Mídia", "entrada": "opcoes", "opcoes": ["tocar_pausar", "proxima", "anterior"]},
        {"tipo": "tocar_youtube", "rotulo": "Tocar no YouTube", "entrada": "texto", "dica": "lofi"},
        {"tipo": "pesquisar", "rotulo": "Pesquisar", "entrada": "texto"},
        {"tipo": "plano_energia", "rotulo": "Plano de energia", "entrada": "opcoes",
         "opcoes": ["economia", "equilibrado", "alto desempenho", "desempenho maximo"]},
        {"tipo": "nao_perturbe", "rotulo": "Não perturbe", "entrada": "bool"},
        {"tipo": "modo_escuro", "rotulo": "Modo escuro", "entrada": "bool"},
        {"tipo": "brilho", "rotulo": "Brilho", "entrada": "texto", "dica": "40, mais ou menos"},
        {"tipo": "holograma", "rotulo": "Abrir holograma", "entrada": "opcoes",
         "opcoes": ["clima", "noticias", "sistema", "relogio", "globo", "lembretes", "rotinas", "atividades"]},
        {"tipo": "clima", "rotulo": "Dizer o clima", "entrada": "nenhum"},
        {"tipo": "noticias", "rotulo": "Dizer as notícias", "entrada": "nenhum"},
        {"tipo": "briefing", "rotulo": "Resumo do dia", "entrada": "nenhum"},
        {"tipo": "lembretes", "rotulo": "Ler lembretes de hoje", "entrada": "nenhum"},
        {"tipo": "organizar_downloads", "rotulo": "Organizar Downloads", "entrada": "nenhum"},
        {"tipo": "mover_arquivo", "rotulo": "Mover o arquivo novo para", "entrada": "texto", "dica": "Documentos"},
        {"tipo": "print", "rotulo": "Tirar print", "entrada": "nenhum"},
        {"tipo": "bloquear", "rotulo": "Bloquear o PC", "entrada": "nenhum"},
        {"tipo": "esperar", "rotulo": "Esperar (segundos)", "entrada": "numero", "dica": "2"},
    ],
}


@dataclass
class Rotina:
    nome: str
    passos: list[dict[str, Any]]
    gatilhos: list[dict[str, Any]] = field(default_factory=list)   # [{"tipo", "valor", ("dias")}]
    condicoes: list[dict[str, Any]] = field(default_factory=list)  # [{"tipo", "valor"}]
    criada_pela_ia: bool = False
    ativo: bool = True

    # -- compatibilidade com o formato antigo -------------------------------------
    @property
    def frases(self) -> list[str]:
        return [str(g["valor"]) for g in self.gatilhos if g["tipo"] == "frase"]

    @property
    def horario(self) -> str | None:
        return next((str(g["valor"]) for g in self.gatilhos if g["tipo"] == "horario"), None)

    @property
    def dias(self) -> list[int]:
        return next((g.get("dias") or [] for g in self.gatilhos if g["tipo"] == "horario"), [])

    def automatico(self) -> bool:
        return any(g["tipo"] in AUTOMATICOS for g in self.gatilhos)

    def editavel(self) -> bool:
        return not any("executar" in p for p in self.passos)

    def para_dict(self) -> dict:
        return {"nome": self.nome, "frases": self.frases, "horario": self.horario, "dias": self.dias,
                "passos": len(self.passos), "criada_pela_ia": self.criada_pela_ia, "ativo": self.ativo,
                "acoes": [next(iter(p)) for p in self.passos if p],
                "gatilhos": [descrever_gatilho(g) for g in self.gatilhos if g["tipo"] != "frase"]}

    def para_editor(self) -> dict:
        return {"nome": self.nome, "ativo": self.ativo, "criada_pela_ia": self.criada_pela_ia,
                "editavel": self.editavel(),
                "gatilhos": [dict(g) for g in self.gatilhos],
                "condicoes": [dict(c) for c in self.condicoes],
                "acoes": [{"tipo": next(iter(p)), "valor": next(iter(p.values()))} for p in self.passos]}

    def para_yaml(self) -> dict:
        gatilhos = []
        for g in self.gatilhos:
            item = {g["tipo"]: g.get("valor", True)}
            if g.get("dias"):
                item["dias"] = [NOMES_DIAS[d] for d in g["dias"]]
            gatilhos.append(item)
        condicoes = []
        for c in self.condicoes:
            valor = [NOMES_DIAS[d] for d in c["valor"]] if c["tipo"] == "dias" else c["valor"]
            condicoes.append({c["tipo"]: valor})
        dados: dict[str, Any] = {"gatilhos": gatilhos}
        if condicoes:
            dados["condicoes"] = condicoes
        dados["passos"] = self.passos
        return dados

    def resumo(self) -> str:
        """Frase legível, para a aprovação por voz."""
        quando = "; ".join(descrever_gatilho(g) for g in self.gatilhos) or "quando você pedir"
        se = "; ".join(descrever_condicao(c) for c in self.condicoes)
        faz = "; ".join(descrever_passo(p) for p in self.passos)
        return f"{quando}{', se ' + se if se else ''}: {faz}"


# -- leitura e validação -----------------------------------------------------------------

def _ler_dias(valor) -> list[int]:
    if valor in (None, "", [], True):
        return []
    if isinstance(valor, int) and 0 <= valor <= 6:
        return [valor]
    if isinstance(valor, str):
        valor = [v.strip() for v in valor.replace(";", ",").split(",")]
    dias = []
    for v in valor:
        if isinstance(v, int):
            dias.append(v)
            continue
        completo = normalizar(str(v))
        chave = completo[:7]
        if completo in ("todos", "todo dia", "todo", "todos os dias"):
            return list(range(7))
        if "uteis" in completo:
            dias.extend(range(5))
            continue
        if completo.startswith("fim de semana") or completo == "fds":
            dias.extend([5, 6])
            continue
        for nome, numero in DIAS.items():
            if chave.startswith(nome[:3]):
                dias.append(numero)
                break
    return sorted(set(d for d in dias if 0 <= d <= 6))


def _hora(valor) -> str | None:
    if isinstance(valor, int):  # YAML lê 07:30 sem aspas como minutos (450)
        return f"{valor // 60:02d}:{valor % 60:02d}"
    m = re.match(r"^\s*(\d{1,2})\s*(?:[:h]\s*(\d{2})?)?\s*$", str(valor or ""))
    if not m or int(m.group(1)) > 23:
        return None
    return f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}"


def _bool(valor) -> bool:
    if isinstance(valor, str):
        return normalizar(valor) not in ("false", "nao", "0", "desligar", "desligado", "off", "")
    return bool(valor)


def _item(bruto: Any, permitidos: list[str]) -> dict[str, Any] | None:
    """Aceita {"tipo": x, "valor": y} (IA/editor) ou {x: y} (YAML)."""
    if not isinstance(bruto, dict):
        return None
    if "tipo" in bruto:
        tipo, valor, extra = bruto.get("tipo"), bruto.get("valor"), {k: v for k, v in bruto.items() if k not in ("tipo", "valor")}
    else:
        chaves = [k for k in bruto if normalizar(str(k)).replace(" ", "_") in permitidos]
        if not chaves:
            return None
        tipo = chaves[0]
        valor = bruto[tipo]
        extra = {k: v for k, v in bruto.items() if k != tipo}
    tipo = normalizar(str(tipo)).replace(" ", "_")
    if tipo not in permitidos:
        return None
    return {"tipo": tipo, "valor": valor, **extra}


def validar_gatilho(bruto: Any) -> dict[str, Any] | None:
    g = _item(bruto, GATILHOS)
    if g is None:
        return None
    tipo, valor = g["tipo"], g.get("valor")
    if tipo == "horario":
        hora = _hora(valor)
        return {"tipo": tipo, "valor": hora, "dias": _ler_dias(g.get("dias"))} if hora else None
    if tipo in ("frase", "app_aberto", "app_fechado", "arquivo_novo"):
        texto = str(valor or "").strip()
        return {"tipo": tipo, "valor": texto} if texto and texto != "True" else None
    if tipo in ("bateria_baixa", "voltar_ao_pc"):
        try:
            numero = int(float(str(valor).replace("%", ""))) if valor not in (None, "", True) else None
        except ValueError:
            numero = None
        padrao = 20 if tipo == "bateria_baixa" else 5
        return {"tipo": tipo, "valor": max(1, min(99, numero or padrao))}
    texto = "" if valor in (None, True) else str(valor).strip()
    return {"tipo": tipo, "valor": texto}  # desbloquear, pendrive, wifi


def validar_condicao(bruto: Any) -> dict[str, Any] | None:
    c = _item(bruto, CONDICOES)
    if c is None:
        return None
    tipo, valor = c["tipo"], c.get("valor")
    if tipo == "dias":
        dias = _ler_dias(valor)
        return {"tipo": tipo, "valor": dias} if dias else None
    if tipo == "entre":
        partes = re.split(r"\s*(?:-|a|ate|até)\s*", str(valor or "").strip())
        horas = [_hora(p) for p in partes if p]
        return {"tipo": tipo, "valor": f"{horas[0]}-{horas[1]}"} if len(horas) == 2 and all(horas) else None
    if tipo in ("em_reuniao", "chovendo"):
        return {"tipo": tipo, "valor": _bool(True if valor is None else valor)}
    return {"tipo": tipo, "valor": str(valor or "").strip()}


def _validar_passos(passos: Any, permitidas: list[str]) -> list[dict[str, Any]]:
    validos = []
    for passo in passos or []:
        if isinstance(passo, dict) and ("acao" in passo or "tipo" in passo):  # formato da IA/editor
            acao = passo.get("acao", passo.get("tipo"))
            passo = {str(acao): passo.get("valor", True) if passo.get("valor") not in (None, "") else True}
        if not isinstance(passo, dict) or len(passo) != 1:
            continue
        acao, valor = next(iter(passo.items()))
        acao = normalizar(str(acao)).replace(" ", "_")
        if acao in permitidas:
            validos.append({acao: valor})
        else:
            log.warning("Passo de protocolo ignorado (ação desconhecida ou não permitida): %s", acao)
    return validos


def montar(nome: str, conf: dict, *, da_ia: bool, permitidas: list[str]) -> Rotina:
    """Monta um protocolo a partir do YAML (formato novo ou antigo) ou do editor."""
    gatilhos = [g for g in (validar_gatilho(x) for x in conf.get("gatilhos") or []) if g]
    for frase in conf.get("frases") or []:  # formato antigo
        gatilhos.append({"tipo": "frase", "valor": str(frase)})
    if conf.get("horario") is not None:
        hora = _hora(conf.get("horario"))
        if hora:
            gatilhos.append({"tipo": "horario", "valor": hora, "dias": _ler_dias(conf.get("dias"))})
    condicoes = [c for c in (validar_condicao(x) for x in conf.get("condicoes") or []) if c]
    return Rotina(nome=str(nome).strip(), passos=_validar_passos(conf.get("passos") or conf.get("acoes"), permitidas),
                  gatilhos=gatilhos, condicoes=condicoes, criada_pela_ia=da_ia)


# -- descrições em português --------------------------------------------------------------

def _dias_texto(dias: list[int]) -> str:
    if sorted(dias) == list(range(5)):
        return "nos dias úteis"
    if sorted(dias) == [5, 6]:
        return "no fim de semana"
    if not dias or len(dias) == 7:
        return "todo dia"
    return "às " + ", ".join(NOMES_DIAS[d] for d in dias)


def descrever_gatilho(g: dict) -> str:
    tipo, v = g.get("tipo", ""), g.get("valor")
    if tipo == "frase":
        return f'quando você disser "{v}"'
    if tipo == "horario":
        return f"às {v} {_dias_texto(g.get('dias') or [])}"
    if tipo == "pendrive":
        return f"quando conectar o pendrive {v}" if v else "quando conectar um pendrive"
    if tipo == "wifi":
        return f"ao conectar na rede {v}" if v else "ao conectar no Wi-Fi"
    return {
        "desbloquear": "ao desbloquear o PC",
        "app_aberto": f"quando abrir {v}",
        "app_fechado": f"quando fechar {v}",
        "bateria_baixa": f"com a bateria abaixo de {v}%",
        "arquivo_novo": f"quando chegar um arquivo em {v}",
        "voltar_ao_pc": f"quando você voltar ao PC (depois de {v} min fora)",
    }.get(tipo, str(tipo))


def descrever_condicao(c: dict) -> str:
    tipo, v = c.get("tipo", ""), c.get("valor")
    if tipo == "dias":
        return _dias_texto(v or [])
    if tipo == "entre":
        return f"entre {str(v).replace('-', ' e ')}"
    if tipo == "em_reuniao":
        return "estiver em reunião" if v else "não estiver em reunião"
    if tipo == "chovendo":
        return "estiver chovendo" if v else "não estiver chovendo"
    if tipo == "wifi":
        return f"estiver na rede {v}"
    return str(tipo)


def descrever_passo(p: dict) -> str:
    acao, valor = next(iter(p.items()))
    rotulo = next((a["rotulo"].lower() for a in CATALOGO["acoes"] if a["tipo"] == acao), acao)
    return rotulo if valor in (True, None, "") else f"{rotulo} {valor}"


# -- condições e combinação de eventos --------------------------------------------------

def _no_intervalo(intervalo: str, agora: datetime) -> bool:
    inicio, fim = intervalo.split("-")
    atual = agora.strftime("%H:%M")
    return inicio <= atual <= fim if inicio <= fim else (atual >= inicio or atual <= fim)


def app_combina(pedido: str, exe: str) -> bool:
    """ "Valorant" combina com "VALORANT-Win64-Shipping"; "VS Code" com "Code"."""
    from .apps import PROCESSOS
    from .janelas import APELIDOS

    alvo = normalizar(pedido)
    base = normalizar(exe.rsplit(".", 1)[0] if exe.lower().endswith(".exe") else exe).replace(" ", "")
    if not alvo or not base:
        return False
    conhecidos = {normalizar(e.rsplit(".", 1)[0]).replace(" ", "") for e in PROCESSOS.get(alvo, [])}
    conhecidos |= {a.replace(" ", "") for a in APELIDOS.get(alvo, [])}
    if base in conhecidos:
        return True
    compacto = alvo.replace(" ", "")
    return base == compacto or (len(compacto) >= 4 and base.startswith(compacto))


def _substituir(valor: Any, variaveis: dict[str, Any]) -> Any:
    if not isinstance(valor, str) or "{" not in valor:
        return valor
    return re.sub(r"\{(\w+)\}", lambda m: str(variaveis.get(m.group(1), m.group(0))), valor)


class Rotinas:
    INTERVALO_MINIMO_S = 60  # um protocolo automático não dispara de novo antes disso

    def __init__(self, app, arquivo: Path, arquivo_criadas: Path) -> None:
        self.app = app
        self.arquivo = arquivo
        self.arquivo_criadas = arquivo_criadas
        self._rotinas: dict[str, Rotina] = {}
        self._executadas_hoje: dict[str, str] = {}
        self._ultimo_disparo: dict[str, float] = {}
        self._lock = threading.Lock()
        self._rodando = False
        self._contexto = None
        self.recarregar()

    # -- arquivos ----------------------------------------------------------------------
    def recarregar(self) -> None:
        rotinas: dict[str, Rotina] = {}
        desativados: set[str] = set()
        for arquivo, da_ia in ((self.arquivo, False), (self.arquivo_criadas, True)):
            dados = self._ler(arquivo)
            if dados is None:
                continue
            blocos = {**(dados.get("rotinas") or {}), **(dados.get("protocolos") or {})}
            for nome, conf in blocos.items():
                rotina = montar(nome, conf or {}, da_ia=da_ia, permitidas=ACOES_SEGURAS if da_ia else ACOES)
                rotinas[normalizar(rotina.nome)] = rotina
            if da_ia:
                desativados = {normalizar(str(n)) for n in dados.get("desativados") or []}
        for chave in desativados:
            if chave in rotinas:
                rotinas[chave].ativo = False
        with self._lock:
            self._rotinas = rotinas
        log.info("%d protocolos carregados", len(rotinas))
        barramento = getattr(self.app, "barramento", None)
        if barramento is not None:
            barramento.publicar("rotinas", rotinas=[r.para_dict() for r in rotinas.values()])

    @staticmethod
    def _ler(arquivo: Path) -> dict | None:
        if not arquivo.exists():
            return None
        try:
            return yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as erro:
            log.error("Erro lendo %s: %s", arquivo.name, erro)
            return None

    def _gravar_criadas(self, alterar) -> None:
        dados = self._ler(self.arquivo_criadas) or {}
        if dados.get("rotinas"):  # migra o formato antigo do arquivo
            dados.setdefault("protocolos", {}).update(dados.pop("rotinas"))
        dados.setdefault("protocolos", {})
        dados.setdefault("desativados", [])
        alterar(dados)
        if not dados["desativados"]:
            dados.pop("desativados")
        cabecalho = "# Protocolos criados pela Sexta-Feira (por voz ou no editor do HUD). Pode editar ou apagar.\n"
        self.arquivo_criadas.write_text(cabecalho + yaml.safe_dump(dados, allow_unicode=True, sort_keys=False),
                                        encoding="utf-8")
        self.recarregar()

    # -- consulta ------------------------------------------------------------------------
    def listar(self) -> list[Rotina]:
        with self._lock:
            return list(self._rotinas.values())

    def obter(self, nome: str) -> Rotina | None:
        alvo = normalizar(nome)
        for prefixo in ("modo ", "protocolo "):
            if alvo.startswith(prefixo) and alvo not in self._rotinas:
                alvo = alvo[len(prefixo):]
        with self._lock:
            if alvo in self._rotinas:
                return self._rotinas[alvo]
            for chave, rotina in self._rotinas.items():
                if alvo in (normalizar(f) for f in rotina.frases) or chave.endswith(alvo) or alvo.endswith(chave):
                    return rotina
        return None

    def encontrar_por_frase(self, texto_normalizado: str) -> Rotina | None:
        with self._lock:
            for chave, rotina in self._rotinas.items():
                if texto_normalizado == chave or texto_normalizado in (normalizar(f) for f in rotina.frases):
                    return rotina
                if texto_normalizado in (f"modo {chave}", f"ativar {chave}", f"ativa {chave}", f"executar {chave}",
                                         f"executa {chave}", f"rotina {chave}", f"ativa o {chave}",
                                         f"protocolo {chave}", f"ativa o protocolo {chave}", f"iniciar protocolo {chave}"):
                    return rotina
        return None

    # -- criação e edição ---------------------------------------------------------------
    def rascunho(self, nome: str, passos: list, frases: list[str] | None = None, horario: str | None = None,
                 dias: list | None = None, gatilhos: list | None = None, condicoes: list | None = None) -> Rotina:
        conf: dict[str, Any] = {"passos": passos, "frases": frases or [], "gatilhos": gatilhos or [],
                                "condicoes": condicoes or []}
        if horario:
            conf["horario"] = horario
            conf["dias"] = dias or ["todos"]
        rotina = montar(nome, conf, da_ia=True, permitidas=ACOES_SEGURAS)
        if not rotina.passos:
            raise ValueError("O protocolo precisa de pelo menos uma ação válida.")
        if not rotina.gatilhos:
            rotina.gatilhos.append({"tipo": "frase", "valor": rotina.nome})
        return rotina

    def criar(self, nome: str, passos: list, frases: list[str] | None = None, horario: str | None = None,
              dias: list | None = None, gatilhos: list | None = None, condicoes: list | None = None) -> Rotina:
        return self.salvar(self.rascunho(nome, passos, frases, horario, dias, gatilhos, condicoes))

    def salvar(self, rotina: Rotina, nome_antigo: str | None = None) -> Rotina:
        if not rotina.nome:
            raise ValueError("Dê um nome ao protocolo.")
        if not rotina.passos:
            raise ValueError("O protocolo precisa de pelo menos uma ação.")

        def alterar(dados: dict) -> None:
            protocolos = dados["protocolos"]
            if nome_antigo and nome_antigo != rotina.nome:
                for chave in [k for k in protocolos if normalizar(k) == normalizar(nome_antigo)]:
                    protocolos.pop(chave)
            for chave in [k for k in protocolos if normalizar(k) == normalizar(rotina.nome)]:
                protocolos.pop(chave)
            protocolos[rotina.nome] = rotina.para_yaml()
            dados["desativados"] = [n for n in dados["desativados"] if normalizar(n) != normalizar(rotina.nome)]
            if not rotina.ativo:
                dados["desativados"].append(rotina.nome)

        self._gravar_criadas(alterar)
        return self.obter(rotina.nome)  # type: ignore[return-value]

    def salvar_do_editor(self, dados: dict, nome_antigo: str | None = None) -> Rotina:
        anterior = self.obter(nome_antigo) if nome_antigo else None
        if anterior is not None and not anterior.editavel():
            raise ValueError("Este protocolo roda comandos do sistema: edite-o no arquivo config/rotinas.yaml.")
        rotina = montar(str(dados.get("nome") or "").strip(), dados, da_ia=True, permitidas=ACOES_SEGURAS)
        rotina.ativo = bool(dados.get("ativo", True))
        if not rotina.gatilhos:
            rotina.gatilhos.append({"tipo": "frase", "valor": rotina.nome})
        return self.salvar(rotina, nome_antigo)

    def definir_ativo(self, nome: str, ativo: bool) -> bool:
        rotina = self.obter(nome)
        if rotina is None:
            return False

        def alterar(dados: dict) -> None:
            dados["desativados"] = [n for n in dados["desativados"] if normalizar(n) != normalizar(rotina.nome)]
            if not ativo:
                dados["desativados"].append(rotina.nome)

        self._gravar_criadas(alterar)
        return True

    def apagar(self, nome: str) -> bool:
        rotina = self.obter(nome)
        if rotina is None or not rotina.criada_pela_ia:
            return False

        def alterar(dados: dict) -> None:
            for chave in [k for k in dados["protocolos"] if normalizar(k) == normalizar(rotina.nome)]:
                dados["protocolos"].pop(chave)
            dados["desativados"] = [n for n in dados["desativados"] if normalizar(n) != normalizar(rotina.nome)]

        self._gravar_criadas(alterar)
        return True

    # -- condições ------------------------------------------------------------------------
    def condicoes_ok(self, rotina: Rotina, agora: datetime | None = None) -> tuple[bool, str]:
        from . import gatilhos as sensores

        agora = agora or datetime.now()
        for c in rotina.condicoes:
            tipo, valor = c["tipo"], c["valor"]
            if tipo == "dias" and agora.weekday() not in valor:
                return False, descrever_condicao(c)
            if tipo == "entre" and not _no_intervalo(valor, agora):
                return False, descrever_condicao(c)
            if tipo == "em_reuniao" and sensores.em_reuniao() != valor:
                return False, descrever_condicao(c)
            if tipo == "chovendo" and sensores.chovendo(self.app) != valor:
                return False, descrever_condicao(c)
            if tipo == "wifi" and normalizar(sensores.rede_wifi() or "") != normalizar(valor):
                return False, descrever_condicao(c)
        return True, ""

    # -- disparo ---------------------------------------------------------------------------
    def disparar(self, tipo: str, **dados: Any) -> list[str]:
        """Um sensor detectou algo (app aberto, pendrive...): roda os protocolos que combinam."""
        disparados = []
        for rotina in self.listar():
            if not rotina.ativo:
                continue
            gatilho = next((g for g in rotina.gatilhos if g["tipo"] == tipo and self._combina(g, dados)), None)
            if gatilho is None:
                continue
            if time.monotonic() - self._ultimo_disparo.get(rotina.nome, -1e9) < self.INTERVALO_MINIMO_S:
                continue
            ok, motivo = self.condicoes_ok(rotina)
            if not ok:
                log.info("Protocolo %s não rodou: condição '%s' não atendida", rotina.nome, motivo)
                continue
            self._ultimo_disparo[rotina.nome] = time.monotonic()
            log.info("Protocolo %s disparado por %s %s", rotina.nome, tipo, dados)
            self.app.barramento.publicar("protocolo.disparado", nome=rotina.nome, gatilho=descrever_gatilho(gatilho))
            contexto = self._contexto() if self._contexto else self.app.contexto("voz")
            self.executar(rotina, contexto, dados)
            disparados.append(rotina.nome)
        return disparados

    def _combina(self, g: dict, dados: dict) -> bool:
        tipo, valor = g["tipo"], g.get("valor")
        if tipo in ("app_aberto", "app_fechado"):
            return app_combina(str(valor), str(dados.get("app", "")))
        if tipo == "bateria_baixa":
            return dados.get("pct") is not None and dados["pct"] <= int(valor) and not dados.get("carregando")
        if tipo == "pendrive":
            return not valor or normalizar(str(valor)) in normalizar(f"{dados.get('rotulo', '')} {dados.get('unidade', '')}")
        if tipo == "arquivo_novo":
            from .gatilhos import resolver_pasta

            pasta = resolver_pasta(str(valor))
            return pasta is not None and Path(str(dados.get("pasta", ""))) == pasta
        if tipo == "wifi":
            return not valor or normalizar(str(valor)) == normalizar(str(dados.get("rede", "")))
        if tipo == "voltar_ao_pc":
            return float(dados.get("ausente_min", 0)) >= float(valor or 5)
        return True  # desbloquear

    def sensores_necessarios(self) -> dict[str, list]:
        """Quais sensores ligar e com quais parâmetros (só o que os protocolos ativos usam)."""
        uso: dict[str, list] = {}
        for rotina in self.listar():
            if not rotina.ativo:
                continue
            for g in rotina.gatilhos:
                if g["tipo"] in AUTOMATICOS:
                    uso.setdefault(g["tipo"], []).append(g.get("valor"))
        return uso

    # -- execução -----------------------------------------------------------------------
    def executar(self, rotina: Rotina, ctx, variaveis: dict[str, Any] | None = None) -> None:
        threading.Thread(target=self._executar, args=(rotina, ctx, variaveis), name=f"rotina-{rotina.nome}",
                         daemon=True).start()

    def _executar(self, rotina: Rotina, ctx, variaveis: dict[str, Any] | None = None) -> None:
        app = self.app
        log.info("Executando protocolo: %s", rotina.nome)
        # o protocolo foi escrito (ou aprovado) pelo usuário: os passos não pedem confirmação de novo
        ctx = replace(ctx, confiavel=True, resultados=[])
        variaveis = dict(variaveis or {})
        if variaveis.get("arquivo"):
            variaveis.setdefault("nome_arquivo", Path(str(variaveis["arquivo"])).name)
        total = len(rotina.passos)
        for i, passo in enumerate(rotina.passos, start=1):
            acao, valor = next(iter(passo.items()))
            app.barramento.publicar("rotina", nome=rotina.nome, passo=i, total=total, acao=acao)
            try:
                self._passo(acao, _substituir(valor, variaveis), ctx, variaveis)
            except Exception:  # noqa: BLE001
                log.exception("Erro no passo %s do protocolo %s", acao, rotina.nome)
        app.barramento.publicar("rotina", nome=rotina.nome, passo=total, total=total, concluida=True)

    def _passo(self, acao: str, valor: Any, ctx, variaveis: dict[str, Any] | None = None) -> None:
        app = self.app
        executar = app.registro.executar
        falar = app.fala.falar
        if acao == "falar":
            falar(str(valor))
        elif acao == "esperar":
            time.sleep(min(float(valor or 1), 600))
        elif acao == "abrir":
            executar("abrir", {"alvo": str(valor)}, ctx)
        elif acao == "fechar":
            executar("fechar_programa", {"nome": str(valor)}, ctx)
        elif acao == "tocar_youtube":
            executar("tocar_youtube", {"busca": str(valor)}, ctx)
        elif acao == "pesquisar":
            executar("pesquisar", {"termo": str(valor)}, ctx)
        elif acao == "volume":
            if str(valor).lower() in ("mudo", "silencio"):
                executar("ajustar_volume", {"acao": "mudo"}, ctx)
            else:
                executar("ajustar_volume", {"acao": "definir", "valor": int(valor)}, ctx)
        elif acao == "midia":
            executar("controlar_midia", {"acao": str(valor)}, ctx)
        elif acao == "clima":
            falar(executar("obter_clima", {}, ctx)["resumo"])
        elif acao == "noticias":
            args = {"categoria": str(valor)} if isinstance(valor, str) else {}
            falar(executar("obter_noticias", {**args, "quantidade": 3}, ctx)["resumo"])
        elif acao == "lembretes":
            falar(executar("gerenciar_lembretes", {"acao": "hoje"}, ctx)["resumo"])
        elif acao == "briefing":
            falar(app.briefing(ctx))
        elif acao == "holograma":
            executar("holograma", {"acao": "mostrar", "tipo": str(valor)}, ctx)
        elif acao == "print":
            executar("computador", {"acao": "print"}, ctx)
        elif acao == "bloquear":
            app.fala.aguardar(15)
            executar("computador", {"acao": "bloquear"}, ctx)
        elif acao == "layout":
            executar("janelas", {"acao": "aplicar_layout", "app": str(valor)}, ctx)
        elif acao == "minimizar_tudo":
            executar("janelas", {"acao": "minimizar_tudo"}, ctx)
        elif acao == "plano_energia":
            executar("configuracao", {"item": "plano_energia", "valor": str(valor)}, ctx)
        elif acao in ("nao_perturbe", "modo_escuro"):
            executar("configuracao", {"item": acao, "valor": "ligar" if _bool(valor) else "desligar"}, ctx)
        elif acao == "brilho":
            executar("configuracao", {"item": "brilho", "valor": str(valor)}, ctx)
        elif acao == "organizar_downloads":
            executar("arquivos", {"acao": "organizar_downloads", "por_data": str(valor).lower() == "data"}, ctx)
        elif acao == "notificar":
            from .notificacoes import notificar

            notificar(app, str(valor))
        elif acao == "mover_arquivo":
            arquivo = (variaveis or {}).get("arquivo")
            if arquivo:
                executar("arquivos", {"acao": "mover", "alvo": str(arquivo), "destino": str(valor)}, ctx)
        elif acao == "executar":
            subprocess.Popen(str(valor), shell=True)  # noqa: S602 - só vale em protocolos escritos à mão no YAML
        if acao in ("falar", "clima", "noticias", "lembretes", "briefing"):
            app.fala.aguardar(30)  # espera terminar de falar antes do próximo passo

    # -- agendamento por horário ----------------------------------------------------------
    def iniciar(self, contexto_fabrica) -> None:
        self._rodando = True
        self._contexto = contexto_fabrica
        threading.Thread(target=self._laco, name="rotinas", daemon=True).start()

    def parar(self) -> None:
        self._rodando = False

    def _laco(self) -> None:
        while self._rodando:
            self.verificar_horarios(datetime.now())
            time.sleep(15)

    def verificar_horarios(self, agora: datetime) -> None:
        hoje = agora.strftime("%Y-%m-%d")
        for rotina in self.listar():
            if not rotina.ativo:
                continue
            for g in rotina.gatilhos:
                if g["tipo"] != "horario" or (g.get("dias") and agora.weekday() not in g["dias"]):
                    continue
                h, m = (int(x) for x in g["valor"].split(":"))
                chave = f"{rotina.nome}@{g['valor']}"
                if (agora.hour, agora.minute) == (h, m) and self._executadas_hoje.get(chave) != hoje:
                    self._executadas_hoje[chave] = hoje
                    ok, motivo = self.condicoes_ok(rotina, agora)
                    if not ok:
                        log.info("Protocolo %s (horário) não rodou: %s", rotina.nome, motivo)
                        continue
                    log.info("Protocolo agendado: %s", rotina.nome)
                    self.executar(rotina, self._contexto() if self._contexto else self.app.contexto("voz"))
