"""Extensões: os recursos das Fases 5 e 6 entram aqui, cada um no seu módulo, sem mexer no núcleo.

Cada módulo listado em ``MODULOS`` (``sexta/extensoes/<nome>.py``) pode definir — tudo é opcional:

Declarações (lidas uma vez, antes de a Sexta-Feira montar as peças):
- ``PREFERENCIAS: dict``                   novas preferências (padrão) editáveis pelo HUD;
- ``HOLOGRAMAS: dict[str, str]``           tipo de holograma -> título (um por vez, como os do núcleo);
- ``ACOES_PROTOCOLO: dict[str, dict]``     ações novas para protocolos/rotinas:
  ``{"acao": {"rotulo": "...", "entrada": "texto|numero|nenhum|bool|opcoes", "dica": "...",
  "opcoes": [...], "executar": funcao(app, valor, ctx, variaveis)}}``;
- ``EVENTOS_ALTA_FREQUENCIA: set[str]``    eventos do WebSocket que só guardam o último valor (ex.: espectro de áudio).

Ganchos (funções):
- ``instalar(app)``                         cria os serviços (``app.algo = ...``); roda no ``__init__`` da Sexta-Feira;
- ``registrar(app, registro)``              ferramentas para a IA (mesmo formato de ``habilidades``);
- ``atalho(t, ctx, rodar, original)``       comando sem IA: recebe o texto normalizado (``t``) e o original;
  devolve uma função sem argumentos que executa e retorna a resposta falada, ou ``None``.
  ``rodar(nome, args, padrao=None)`` monta essa função para uma ferramenta;
- ``rotas(api, app, autenticado, so_pc)``   rotas HTTP (FastAPI) extras;
- ``async mensagem_ws(app, cliente, registrado, mensagem, websocket) -> bool``  mensagem JSON do WebSocket;
  devolve True se tratou;
- ``dados_holograma(app, tipo) -> dict | None``  dados quando o HUD abre o holograma pela barra lateral;
- ``diagnostico(app) -> list[dict]``        itens extras do diagnóstico (``{"nome", "ok", "detalhe", "dica"}``);
- ``iniciar(app)``                          threads de fundo, depois que o servidor sobe;
- ``encerrar(app)``                         ao sair.

Um módulo com erro é registrado no log e ignorado: uma extensão nunca derruba a Sexta-Feira.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from types import ModuleType
from typing import Any, Callable

log = logging.getLogger(__name__)

MODULOS = ["traje", "oficina", "sentinela", "comunicacao", "maos_livres", "documentos"]

_carregados: list[ModuleType] | None = None
_preparado = False


def carregar() -> list[ModuleType]:
    global _carregados
    if _carregados is None:
        modulos = []
        for nome in MODULOS:
            try:
                modulos.append(importlib.import_module(f"{__name__}.{nome}"))
            except ModuleNotFoundError as erro:
                if erro.name == f"{__name__}.{nome}":
                    continue  # extensão ainda não existe
                log.exception("Extensão %s não carregou", nome)
            except Exception:  # noqa: BLE001
                log.exception("Extensão %s não carregou", nome)
        _carregados = modulos
    return _carregados


def _chamar(funcao: str, *args, **kwargs) -> list[Any]:
    resultados = []
    for modulo in carregar():
        alvo = getattr(modulo, funcao, None)
        if alvo is None:
            continue
        try:
            resultados.append(alvo(*args, **kwargs))
        except Exception:  # noqa: BLE001
            log.exception("Erro em %s.%s", modulo.__name__, funcao)
    return resultados


def preparar() -> None:
    """Junta as declarações das extensões às tabelas do núcleo (pode ser chamada várias vezes)."""
    global _preparado
    if _preparado:
        return
    from .. import config, eventos
    from ..habilidades import hologramas, rotinas

    for modulo in carregar():
        for chave, valor in getattr(modulo, "PREFERENCIAS", {}).items():
            config.PREFERENCIAS_PADRAO.setdefault(chave, valor)
            config.PREFERENCIAS_EDITAVEIS.add(chave)
        for tipo, titulo in getattr(modulo, "HOLOGRAMAS", {}).items():
            if tipo not in hologramas.TIPOS:
                hologramas.TIPOS.append(tipo)
            hologramas.TITULOS[tipo] = titulo
            hologramas.UNICOS.add(tipo)
        for acao, definicao in getattr(modulo, "ACOES_PROTOCOLO", {}).items():
            if acao not in rotinas.ACOES_SEGURAS:
                rotinas.ACOES_SEGURAS.append(acao)
            if acao not in rotinas.ACOES:
                rotinas.ACOES.append(acao)
            entrada = {k: v for k, v in definicao.items() if k != "executar"}
            if not any(a["tipo"] == acao for a in rotinas.CATALOGO["acoes"]):
                rotinas.CATALOGO["acoes"].append({"tipo": acao, **entrada})
            rotinas.ACOES_EXTRAS[acao] = definicao["executar"]
        eventos.TIPOS_ALTA_FREQUENCIA.update(getattr(modulo, "EVENTOS_ALTA_FREQUENCIA", set()))
    _preparado = True


def instalar(app) -> None:
    _chamar("instalar", app)


def registrar(app, registro) -> None:
    _chamar("registrar", app, registro)


def iniciar(app) -> None:
    _chamar("iniciar", app)


def encerrar(app) -> None:
    _chamar("encerrar", app)


def rotas(api, app, autenticado, so_pc) -> None:
    _chamar("rotas", api, app, autenticado, so_pc)


def atalho(t: str, ctx, rodar: Callable, original: str | None) -> Callable[[], str] | None:
    for modulo in carregar():
        funcao = getattr(modulo, "atalho", None)
        if funcao is None:
            continue
        try:
            plano = funcao(t, ctx, rodar, original)
        except Exception:  # noqa: BLE001
            log.exception("Erro no atalho de %s", modulo.__name__)
            continue
        if plano is not None:
            return plano
    return None


async def mensagem_ws(app, cliente, registrado, mensagem: dict, websocket) -> bool:
    for modulo in carregar():
        funcao = getattr(modulo, "mensagem_ws", None)
        if funcao is None:
            continue
        try:
            resultado = funcao(app, cliente, registrado, mensagem, websocket)
            if inspect.isawaitable(resultado):
                resultado = await resultado
        except Exception:  # noqa: BLE001
            log.exception("Erro no WebSocket de %s", modulo.__name__)
            continue
        if resultado:
            return True
    return False


def dados_holograma(app, tipo: str) -> dict | None:
    for dados in _chamar("dados_holograma", app, tipo):
        if dados is not None:
            return dados
    return None


def diagnostico(app) -> list[dict]:
    itens: list[dict] = []
    for lista in _chamar("diagnostico", app):
        itens.extend(lista or [])
    return itens
