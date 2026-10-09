"""Barramento de eventos: liga as threads da Sexta-Feira aos clientes WebSocket (HUD e celular).

Qualquer thread pode chamar :meth:`Barramento.publicar`; o envio acontece no loop
asyncio do servidor. Eventos de mãos (alta frequência) usam um "slot do último
valor" por cliente, para que um cliente lento nunca acumule atraso.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

_MARCADOR_MAOS = object()
_FIM = object()
TIPOS_ALTA_FREQUENCIA = {"maos", "fala.nivel", "mic.nivel"}


@dataclass
class ClienteWS:
    id: int
    tipo: str  # "pc" ou "celular"
    nome: str
    enviar: Callable[[dict], Any]  # coroutine function (ex.: websocket.send_json)
    quer_maos: bool = False
    fila: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=400))
    slots: dict[str, dict] = field(default_factory=dict)
    descartados: int = 0

    def colocar(self, evento: dict) -> None:
        tipo = evento.get("tipo", "")
        if tipo in TIPOS_ALTA_FREQUENCIA:
            ja_pendente = tipo in self.slots
            self.slots[tipo] = evento
            if ja_pendente:
                return
            item: Any = (_MARCADOR_MAOS, tipo)
        else:
            item = evento
        try:
            self.fila.put_nowait(item)
        except asyncio.QueueFull:
            self.descartados += 1
            if self.descartados in (1, 100, 1000):
                log.warning("Cliente %s lento: %d eventos descartados", self.nome, self.descartados)

    def encerrar(self) -> None:
        try:
            self.fila.put_nowait(_FIM)
        except asyncio.QueueFull:
            pass

    async def loop_envio(self) -> None:
        while True:
            item = await self.fila.get()
            if item is _FIM:
                return
            if isinstance(item, tuple) and item and item[0] is _MARCADOR_MAOS:
                evento = self.slots.pop(item[1], None)
                if evento is None:
                    continue
            else:
                evento = item
            await self.enviar(evento)


class Barramento:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clientes: dict[int, ClienteWS] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._ouvintes: list[Callable[[dict], None]] = []

    # -- configuração -------------------------------------------------------
    def anexar_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def ouvir(self, funcao: Callable[[dict], None]) -> None:
        """Registra um ouvinte local (chamado na thread de quem publicou)."""
        with self._lock:
            self._ouvintes.append(funcao)

    # -- clientes -----------------------------------------------------------
    def novo_cliente(self, tipo: str, nome: str, enviar: Callable[[dict], Any]) -> ClienteWS:
        cliente = ClienteWS(id=next(self._ids), tipo=tipo, nome=nome, enviar=enviar)
        with self._lock:
            self._clientes[cliente.id] = cliente
        return cliente

    def remover_cliente(self, cliente: ClienteWS) -> None:
        with self._lock:
            self._clientes.pop(cliente.id, None)
        cliente.encerrar()

    def clientes(self) -> list[ClienteWS]:
        with self._lock:
            return list(self._clientes.values())

    def alguem_quer_maos(self) -> bool:
        return any(c.quer_maos for c in self.clientes())

    def tem_hud_no_pc(self) -> bool:
        return any(c.tipo == "pc" for c in self.clientes())

    # -- publicação ----------------------------------------------------------
    def publicar(self, tipo: str, para: str | int | None = None, **dados: Any) -> None:
        """Publica um evento. ``para``: None (todos), "pc", "celular" ou id do cliente."""
        evento = {"tipo": tipo, "ts": round(time.time(), 3), **dados}
        if tipo not in TIPOS_ALTA_FREQUENCIA:
            with self._lock:
                ouvintes = list(self._ouvintes)
            for ouvinte in ouvintes:
                try:
                    ouvinte(evento)
                except Exception:  # noqa: BLE001
                    log.exception("Erro em ouvinte de eventos")
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._distribuir, evento, para)
        except RuntimeError:  # loop encerrado durante o desligamento
            pass

    def _distribuir(self, evento: dict, para: str | int | None) -> None:
        for cliente in self.clientes():
            if para is None or para == cliente.tipo or para == cliente.id:
                if evento["tipo"] == "maos" and not cliente.quer_maos:
                    continue
                cliente.colocar(evento)
