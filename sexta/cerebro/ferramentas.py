"""Registro de ferramentas que a IA pode chamar (formato de tools do Ollama).

Cada ferramenta tem um nível de segurança:

- ``LIVRE`` (1): roda na hora (abrir, ler, consultar);
- ``CONFIRMAR`` (2): pergunta antes e espera um "sim" (fechar, mover);
- ``ROSTO`` (3): pergunta antes e confere o rosto (apagar, desligar, rodar comando).

A confirmação é feita aqui, não pelo modelo de IA: a ação fica pendente e o próximo
"sim" do usuário a executa. Assim nenhum modelo consegue "se autoconfirmar".
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

LIVRE, CONFIRMAR, ROSTO = 1, 2, 3
PENDENTE_EXPIRA_S = 90


def P(tipo: str, descricao: str, *, enum: list[str] | None = None, obrigatorio: bool = False,
      itens: dict | None = None) -> dict[str, Any]:
    """Descreve um parâmetro de ferramenta."""
    esquema: dict[str, Any] = {"type": tipo, "description": descricao}
    if enum:
        esquema["enum"] = enum
    if itens:
        esquema["items"] = itens
    esquema["_obrigatorio"] = obrigatorio
    return esquema


@dataclass
class Contexto:
    """O que uma ferramenta recebe: a aplicação inteira e de onde veio o pedido."""

    app: Any
    canal: str = "voz"          # "voz", "texto" (HUD) ou "celular"
    cliente: Any = None
    resultados: list[dict] = field(default_factory=list)
    confiavel: bool = False     # rotinas e protocolos escritos pelo usuário: não pedem confirmação


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    parametros: dict[str, dict[str, Any]]
    funcao: Callable[..., Any]
    nivel: int | Callable[[dict[str, Any]], int] = LIVRE
    direta: bool = False        # o resumo já é a resposta: não precisa voltar ao modelo
    descrever: Callable[[dict[str, Any]], str] | None = None  # texto da pergunta de confirmação

    def nivel_para(self, args: dict[str, Any]) -> int:
        return self.nivel(args) if callable(self.nivel) else self.nivel

    def esquema(self) -> dict[str, Any]:
        propriedades = {}
        obrigatorios = []
        for nome, p in self.parametros.items():
            limpo = {k: v for k, v in p.items() if not k.startswith("_")}
            propriedades[nome] = limpo
            if p.get("_obrigatorio"):
                obrigatorios.append(nome)
        return {
            "type": "function",
            "function": {
                "name": self.nome,
                "description": self.descricao,
                "parameters": {"type": "object", "properties": propriedades, "required": obrigatorios},
            },
        }


@dataclass
class Pendente:
    """Ação esperando o "sim" do usuário."""

    nome: str
    argumentos: dict[str, Any]
    nivel: int
    descricao: str
    canal: str
    criado: float = field(default_factory=time.time)

    def expirou(self) -> bool:
        return time.time() - self.criado > PENDENTE_EXPIRA_S


class Registro:
    def __init__(self) -> None:
        self._ferramentas: dict[str, Ferramenta] = {}
        self._pendente: Pendente | None = None
        self._lock = threading.Lock()
        self.ao_executar: Callable[[dict[str, Any]], None] | None = None  # registro de atividades

    def ferramenta(self, nome_ferramenta: str, descricao: str, /, *, nivel: int | Callable = LIVRE,
                   direta: bool = False, descrever: Callable | None = None, **parametros: dict[str, Any]):
        """Decorador. Os parâmetros da ferramenta vão como kwargs (podem se chamar "nome", "acao"...)."""
        def decorador(funcao: Callable[..., Any]):
            self._ferramentas[nome_ferramenta] = Ferramenta(nome_ferramenta, descricao, parametros, funcao,
                                                            nivel, direta, descrever)
            return funcao
        return decorador

    # -- confirmação ---------------------------------------------------------
    def pendente(self) -> Pendente | None:
        with self._lock:
            if self._pendente and self._pendente.expirou():
                self._pendente = None
            return self._pendente

    def cancelar_pendente(self) -> Pendente | None:
        with self._lock:
            pendente, self._pendente = self._pendente, None
        if pendente:
            self._anotar({"ferramenta": pendente.nome, "argumentos": pendente.argumentos, "nivel": pendente.nivel,
                          "situacao": "cancelada", "resumo": f"Cancelado: {pendente.descricao}.", "canal": pendente.canal})
        return pendente

    def confirmar(self, ctx: Contexto, verificar_rosto: Callable[[Contexto], tuple[bool, str]] | None = None
                  ) -> dict[str, Any]:
        """Executa a ação pendente depois do "sim" (e do rosto, no nível 3)."""
        with self._lock:
            pendente, self._pendente = self._pendente, None
        if pendente is None or pendente.expirou():
            return {"ok": False, "resumo": "Não havia nada esperando confirmação."}
        if pendente.nivel >= ROSTO and verificar_rosto is not None:
            ok, motivo = verificar_rosto(ctx)
            if not ok:
                self._anotar({"ferramenta": pendente.nome, "argumentos": pendente.argumentos, "nivel": pendente.nivel,
                              "situacao": "negada", "resumo": motivo, "canal": ctx.canal})
                return {"ok": False, "resumo": motivo}
        return self.executar(pendente.nome, pendente.argumentos, ctx, confirmado=True)

    def nomes(self) -> list[str]:
        return list(self._ferramentas)

    def esquemas(self) -> list[dict[str, Any]]:
        return [f.esquema() for f in self._ferramentas.values()]

    def executar(self, nome: str, argumentos: dict[str, Any], ctx: Contexto, *, confirmado: bool = False
                 ) -> dict[str, Any]:
        """Executa e devolve sempre um dict com ao menos ``ok`` e ``resumo``.

        Ações de nível 2 ou 3 não confirmadas ficam pendentes e devolvem a pergunta.
        """
        ferramenta = self._ferramentas.get(nome)
        if ferramenta is None:
            return {"ok": False, "resumo": f"Ferramenta '{nome}' não existe."}
        args = _converter(argumentos or {}, ferramenta.parametros)
        faltando = [n for n, p in ferramenta.parametros.items() if p.get("_obrigatorio") and args.get(n) in (None, "")]
        if faltando:
            return {"ok": False, "resumo": f"Faltou informar: {', '.join(faltando)}."}
        nivel = ferramenta.nivel_para(args)
        if nivel > LIVRE and not confirmado and not ctx.confiavel:
            return self._pedir_confirmacao(ferramenta, args, nivel, ctx)
        try:
            resultado = ferramenta.funcao(ctx, **args)
        except Exception as erro:  # noqa: BLE001 - o erro vira resposta para a IA
            log.exception("Erro na ferramenta %s", nome)
            resultado = {"ok": False, "resumo": f"Erro ao executar {nome}: {erro}"}
        if isinstance(resultado, str):
            resultado = {"ok": True, "resumo": resultado}
        elif not isinstance(resultado, dict):
            resultado = {"ok": True, "resumo": json.dumps(resultado, ensure_ascii=False, default=str)}
        resultado.setdefault("ok", True)
        resultado.setdefault("resumo", "Feito.")
        resultado.setdefault("_direta", ferramenta.direta and bool(resultado["ok"]))
        if resultado.get("pendente"):  # a própria ferramenta pediu confirmação (ex.: comando fora da lista)
            resultado["_direta"] = True
        ctx.resultados.append({"ferramenta": nome, **resultado})
        self._anotar({"ferramenta": nome, "argumentos": args, "nivel": nivel, "canal": ctx.canal,
                      "situacao": "ok" if resultado["ok"] else "falhou", "resumo": resultado["resumo"]})
        return resultado

    def _pedir_confirmacao(self, ferramenta: Ferramenta, args: dict[str, Any], nivel: int, ctx: Contexto
                           ) -> dict[str, Any]:
        descricao = ferramenta.descrever(args) if ferramenta.descrever else ferramenta.nome.replace("_", " ")
        with self._lock:
            self._pendente = Pendente(ferramenta.nome, args, nivel, descricao, ctx.canal)
        pergunta = f"Confirma: {descricao}?"
        if nivel >= ROSTO:
            pergunta += " Vou conferir seu rosto." if ctx.canal == "voz" else " Essa exige confirmação reforçada."
        resultado = {"ok": False, "pendente": True, "resumo": pergunta, "_direta": True,
                     "observacao": "A ação só acontece se o usuário disser sim. Não chame a ferramenta de novo."}
        ctx.resultados.append({"ferramenta": ferramenta.nome, **resultado})
        self._anotar({"ferramenta": ferramenta.nome, "argumentos": args, "nivel": nivel, "canal": ctx.canal,
                      "situacao": "aguardando", "resumo": pergunta})
        return resultado

    def _anotar(self, registro: dict[str, Any]) -> None:
        if self.ao_executar is None:
            return
        try:
            self.ao_executar(registro)
        except Exception:  # noqa: BLE001 - o registro de atividades nunca pode quebrar uma ação
            log.exception("Erro no registro de atividades")


def _converter(argumentos: dict[str, Any], parametros: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Aceita só parâmetros conhecidos e corrige tipos simples (ex.: "5" -> 5)."""
    saida: dict[str, Any] = {}
    for nome, valor in argumentos.items():
        p = parametros.get(nome)
        if p is None or valor is None:
            continue
        tipo = p.get("type")
        try:
            if tipo == "integer" and not isinstance(valor, bool):
                valor = int(float(str(valor).replace(",", ".")))
            elif tipo == "number":
                valor = float(str(valor).replace(",", "."))
            elif tipo == "boolean" and isinstance(valor, str):
                valor = valor.strip().lower() in {"true", "sim", "1", "yes", "verdadeiro"}
            elif tipo == "string" and not isinstance(valor, str):
                valor = str(valor)
            elif tipo == "array" and isinstance(valor, str):
                try:
                    valor = json.loads(valor)
                except json.JSONDecodeError:
                    valor = [v.strip() for v in valor.split(",") if v.strip()]
        except (TypeError, ValueError):
            continue
        if "enum" in p and isinstance(valor, str):
            valor = _casar_enum(valor, p["enum"])
            if valor is None:
                continue
        saida[nome] = valor
    return saida


def _casar_enum(valor: str, opcoes: list[str]) -> str | None:
    from ..util.texto import normalizar

    alvo = normalizar(valor).replace(" ", "_")
    for opcao in opcoes:
        if normalizar(opcao).replace(" ", "_") == alvo:
            return opcao
    for opcao in opcoes:
        if alvo and (alvo in opcao or opcao in alvo):
            return opcao
    return None
