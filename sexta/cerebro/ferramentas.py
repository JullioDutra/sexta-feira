"""Registro de ferramentas que a IA pode chamar (formato de tools do Ollama)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


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


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    parametros: dict[str, dict[str, Any]]
    funcao: Callable[..., Any]

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


class Registro:
    def __init__(self) -> None:
        self._ferramentas: dict[str, Ferramenta] = {}

    def ferramenta(self, nome_ferramenta: str, descricao: str, /, **parametros: dict[str, Any]):
        """Decorador. Os parâmetros da ferramenta vão como kwargs (podem se chamar "nome", "acao"...)."""
        def decorador(funcao: Callable[..., Any]):
            self._ferramentas[nome_ferramenta] = Ferramenta(nome_ferramenta, descricao, parametros, funcao)
            return funcao
        return decorador

    def nomes(self) -> list[str]:
        return list(self._ferramentas)

    def esquemas(self) -> list[dict[str, Any]]:
        return [f.esquema() for f in self._ferramentas.values()]

    def executar(self, nome: str, argumentos: dict[str, Any], ctx: Contexto) -> dict[str, Any]:
        """Executa e devolve sempre um dict com ao menos ``ok`` e ``resumo``."""
        ferramenta = self._ferramentas.get(nome)
        if ferramenta is None:
            return {"ok": False, "resumo": f"Ferramenta '{nome}' não existe."}
        args = _converter(argumentos or {}, ferramenta.parametros)
        faltando = [n for n, p in ferramenta.parametros.items() if p.get("_obrigatorio") and args.get(n) in (None, "")]
        if faltando:
            return {"ok": False, "resumo": f"Faltou informar: {', '.join(faltando)}."}
        try:
            resultado = ferramenta.funcao(ctx, **args)
        except Exception as erro:  # noqa: BLE001 - o erro vira resposta para a IA
            log.exception("Erro na ferramenta %s", nome)
            return {"ok": False, "resumo": f"Erro ao executar {nome}: {erro}"}
        if isinstance(resultado, str):
            resultado = {"ok": True, "resumo": resultado}
        elif not isinstance(resultado, dict):
            resultado = {"ok": True, "resumo": json.dumps(resultado, ensure_ascii=False, default=str)}
        resultado.setdefault("ok", True)
        resultado.setdefault("resumo", "Feito.")
        ctx.resultados.append({"ferramenta": nome, **resultado})
        return resultado


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
