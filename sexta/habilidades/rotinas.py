"""Rotinas: sequências de ações disparadas por uma frase ("modo trabalho") ou por horário.

As rotinas ficam em ``config/rotinas.yaml`` (edite à vontade). As que a própria
Sexta-Feira cria por voz vão para ``config/rotinas_criadas.yaml``.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ..util.texto import normalizar

log = logging.getLogger(__name__)

DIAS = {"seg": 0, "segunda": 0, "ter": 1, "terca": 1, "qua": 2, "quarta": 2, "qui": 3, "quinta": 3,
        "sex": 4, "sexta": 4, "sab": 5, "sabado": 5, "dom": 6, "domingo": 6}
# Ações que a IA pode usar ao criar rotinas (sem "executar", que roda comandos do sistema)
ACOES_SEGURAS = ["falar", "abrir", "fechar", "tocar_youtube", "pesquisar", "volume", "midia", "esperar",
                 "clima", "noticias", "briefing", "lembretes", "holograma", "print", "bloquear"]
ACOES = ACOES_SEGURAS + ["executar"]


@dataclass
class Rotina:
    nome: str
    passos: list[dict[str, Any]]
    frases: list[str] = field(default_factory=list)
    horario: str | None = None
    dias: list[int] = field(default_factory=list)
    criada_pela_ia: bool = False

    def para_dict(self) -> dict:
        return {"nome": self.nome, "frases": self.frases, "horario": self.horario, "dias": self.dias,
                "passos": len(self.passos), "criada_pela_ia": self.criada_pela_ia,
                "acoes": [next(iter(p)) for p in self.passos if p]}


def _ler_dias(valor) -> list[int]:
    if not valor:
        return []
    if isinstance(valor, str):
        valor = [v.strip() for v in valor.replace(";", ",").split(",")]
    dias = []
    for v in valor:
        chave = normalizar(str(v))[:7]
        if chave in ("todos", "todo dia", "todo"):
            return list(range(7))
        if chave in ("uteis", "dias ute", "dias uteis"):
            dias.extend(range(5))
            continue
        for nome, numero in DIAS.items():
            if chave.startswith(nome[:3]):
                dias.append(numero)
                break
    return sorted(set(dias))


def _validar_passos(passos: Any, permitidas: list[str]) -> list[dict[str, Any]]:
    validos = []
    for passo in passos or []:
        if isinstance(passo, dict) and "acao" in passo:  # formato da IA: {"acao": "abrir", "valor": "Spotify"}
            passo = {str(passo["acao"]): passo.get("valor", True)}
        if not isinstance(passo, dict) or len(passo) != 1:
            continue
        acao, valor = next(iter(passo.items()))
        acao = normalizar(str(acao)).replace(" ", "_")
        if acao in permitidas:
            validos.append({acao: valor})
        else:
            log.warning("Passo de rotina ignorado (ação desconhecida ou não permitida): %s", acao)
    return validos


class Rotinas:
    def __init__(self, app, arquivo: Path, arquivo_criadas: Path) -> None:
        self.app = app
        self.arquivo = arquivo
        self.arquivo_criadas = arquivo_criadas
        self._rotinas: dict[str, Rotina] = {}
        self._executadas_hoje: dict[str, str] = {}
        self._lock = threading.Lock()
        self._rodando = False
        self.recarregar()

    def recarregar(self) -> None:
        rotinas: dict[str, Rotina] = {}
        for arquivo, da_ia in ((self.arquivo, False), (self.arquivo_criadas, True)):
            if not arquivo.exists():
                continue
            try:
                dados = yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as erro:
                log.error("Erro lendo %s: %s", arquivo.name, erro)
                continue
            for nome, conf in (dados.get("rotinas") or {}).items():
                conf = conf or {}
                horario = conf.get("horario")
                if isinstance(horario, int):  # YAML lê 07:30 sem aspas como minutos (450)
                    horario = f"{horario // 60:02d}:{horario % 60:02d}"
                rotina = Rotina(
                    nome=str(nome).strip(),
                    passos=_validar_passos(conf.get("passos"), ACOES_SEGURAS if da_ia else ACOES),
                    frases=[str(f) for f in conf.get("frases") or []],
                    horario=str(horario) if horario else None,
                    dias=_ler_dias(conf.get("dias")),
                    criada_pela_ia=da_ia,
                )
                rotinas[normalizar(rotina.nome)] = rotina
        with self._lock:
            self._rotinas = rotinas
        log.info("%d rotinas carregadas", len(rotinas))

    def listar(self) -> list[Rotina]:
        with self._lock:
            return list(self._rotinas.values())

    def obter(self, nome: str) -> Rotina | None:
        alvo = normalizar(nome)
        alvo = alvo[5:] if alvo.startswith("modo ") and alvo not in self._rotinas else alvo
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
                                         f"executa {chave}", f"rotina {chave}", f"ativa o {chave}"):
                    return rotina
        return None

    def criar(self, nome: str, passos: list, frases: list[str] | None = None, horario: str | None = None,
              dias: list | None = None) -> Rotina:
        validos = _validar_passos(passos, ACOES_SEGURAS)
        if not validos:
            raise ValueError("A rotina precisa de pelo menos um passo válido.")
        dados: dict = {"rotinas": {}}
        if self.arquivo_criadas.exists():
            dados = yaml.safe_load(self.arquivo_criadas.read_text(encoding="utf-8")) or {"rotinas": {}}
            dados.setdefault("rotinas", {})
        conf: dict[str, Any] = {"frases": frases or [nome], "passos": validos}
        if horario:
            conf["horario"] = horario
            conf["dias"] = dias or ["todos"]
        dados["rotinas"][nome] = conf
        cabecalho = "# Rotinas criadas pela Sexta-Feira por voz. Pode editar ou apagar.\n"
        self.arquivo_criadas.write_text(cabecalho + yaml.safe_dump(dados, allow_unicode=True, sort_keys=False),
                                        encoding="utf-8")
        self.recarregar()
        return self.obter(nome)  # type: ignore[return-value]

    def apagar(self, nome: str) -> bool:
        rotina = self.obter(nome)
        if rotina is None or not rotina.criada_pela_ia:
            return False
        dados = yaml.safe_load(self.arquivo_criadas.read_text(encoding="utf-8")) or {}
        (dados.get("rotinas") or {}).pop(rotina.nome, None)
        self.arquivo_criadas.write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.recarregar()
        return True

    # -- execução ------------------------------------------------------------
    def executar(self, rotina: Rotina, ctx) -> None:
        threading.Thread(target=self._executar, args=(rotina, ctx), name=f"rotina-{rotina.nome}", daemon=True).start()

    def _executar(self, rotina: Rotina, ctx) -> None:
        app = self.app
        log.info("Executando rotina: %s", rotina.nome)
        total = len(rotina.passos)
        for i, passo in enumerate(rotina.passos, start=1):
            acao, valor = next(iter(passo.items()))
            app.barramento.publicar("rotina", nome=rotina.nome, passo=i, total=total, acao=acao)
            try:
                self._passo(acao, valor, ctx)
            except Exception:  # noqa: BLE001
                log.exception("Erro no passo %s da rotina %s", acao, rotina.nome)
        app.barramento.publicar("rotina", nome=rotina.nome, passo=total, total=total, concluida=True)

    def _passo(self, acao: str, valor: Any, ctx) -> None:
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
        elif acao == "executar":
            subprocess.Popen(str(valor), shell=True)  # noqa: S602 - só vale em rotinas escritas à mão no YAML
        if acao in ("falar", "clima", "noticias", "lembretes", "briefing"):
            app.fala.aguardar(30)  # espera terminar de falar antes do próximo passo

    # -- agendamento ----------------------------------------------------------
    def iniciar(self, contexto_fabrica) -> None:
        self._rodando = True
        self._contexto = contexto_fabrica
        threading.Thread(target=self._laco, name="rotinas", daemon=True).start()

    def _laco(self) -> None:
        while self._rodando:
            agora = datetime.now()
            hoje = agora.strftime("%Y-%m-%d")
            for rotina in self.listar():
                if not rotina.horario or (rotina.dias and agora.weekday() not in rotina.dias):
                    continue
                try:
                    h, m = (int(x) for x in rotina.horario.replace("h", ":").split(":")[:2])
                except ValueError:
                    continue
                if (agora.hour, agora.minute) == (h, m) and self._executadas_hoje.get(rotina.nome) != hoje:
                    self._executadas_hoje[rotina.nome] = hoje
                    log.info("Rotina agendada: %s", rotina.nome)
                    self.executar(rotina, self._contexto())
            time.sleep(15)
