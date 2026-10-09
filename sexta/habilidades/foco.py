"""Modo foco: Pomodoro em holograma.

Ao começar: liga o "não perturbe" do Windows e fecha as distrações (lista em Ajustes).
Durante o foco só a Sexta-Feira interrompe: os alertas de notícias e as notificações dos
protocolos esperam até a pausa. Lembretes e alarmes continuam tocando.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

DISTRACOES_PADRAO = ["Discord", "WhatsApp", "Telegram", "Steam"]


class ModoFoco:
    def __init__(self, app) -> None:
        self.app = app
        self._lock = threading.Lock()
        self._estado: dict[str, Any] | None = None
        self._pausado_restante: float | None = None
        self._segurados: list[Callable[[], None]] = []
        self._thread: threading.Thread | None = None
        self._parar = threading.Event()

    # -- consulta --------------------------------------------------------------------------
    def ativo(self) -> bool:
        with self._lock:
            return self._estado is not None and self._estado["fase"] == "foco"

    def estado(self) -> dict[str, Any] | None:
        with self._lock:
            if self._estado is None:
                return None
            e = dict(self._estado)
        e["pausado"] = self._pausado_restante is not None
        e["restante"] = round(self._pausado_restante if e["pausado"] else max(0.0, e["termina"] - time.time()))
        return e

    def segurar(self, acao: Callable[[], None]) -> bool:
        """Guarda um aviso para depois do foco. Devolve False se não há foco (rode na hora)."""
        if not self.ativo():
            return False
        with self._lock:
            self._segurados.append(acao)
        return True

    # -- controle --------------------------------------------------------------------------
    def iniciar(self, minutos: int | None = None, pausa: int | None = None, ciclos: int | None = None,
                tarefa: str | None = None) -> dict[str, Any]:
        prefs = self.app.prefs
        minutos = max(1, min(240, int(minutos or prefs.get("foco_minutos") or 25)))
        pausa = max(1, min(60, int(pausa or prefs.get("foco_pausa") or 5)))
        ciclos = max(1, min(12, int(ciclos or 4)))
        self.encerrar(silencioso=True)
        self._parar.clear()
        with self._lock:
            self._estado = {"fase": "foco", "ciclo": 1, "ciclos": ciclos, "minutos": minutos, "pausa": pausa,
                            "tarefa": tarefa or "", "termina": time.time() + minutos * 60, "duracao": minutos * 60}
            self._pausado_restante = None
        self._preparar_ambiente(True)
        self._publicar()
        self._thread = threading.Thread(target=self._laco, name="foco", daemon=True)
        self._thread.start()
        return self.estado()  # type: ignore[return-value]

    def pausar(self) -> bool:
        with self._lock:
            if self._estado is None or self._pausado_restante is not None:
                return False
            self._pausado_restante = max(0.0, self._estado["termina"] - time.time())
        self._publicar()
        return True

    def retomar(self) -> bool:
        with self._lock:
            if self._estado is None or self._pausado_restante is None:
                return False
            self._estado["termina"] = time.time() + self._pausado_restante
            self._pausado_restante = None
        self._publicar()
        return True

    def encerrar(self, silencioso: bool = False) -> dict[str, Any] | None:
        with self._lock:
            estado, self._estado = self._estado, None
            self._pausado_restante = None
        self._parar.set()
        if estado is None:
            return None
        self._preparar_ambiente(False)
        self._liberar_segurados()
        if not silencioso:
            self.app.hologramas.fechar(tipo="foco")
        self.app.barramento.publicar("foco", ativo=False)
        return estado

    # -- interno ---------------------------------------------------------------------------
    def _contexto(self):
        from ..cerebro.ferramentas import Contexto

        return Contexto(self.app, canal="voz", confiavel=True)

    def _preparar_ambiente(self, ligar: bool) -> None:
        ctx = self._contexto()
        executar = self.app.registro.executar
        executar("configuracao", {"item": "nao_perturbe", "valor": "ligar" if ligar else "desligar"}, ctx)
        if ligar:
            for nome in self.app.prefs.get("foco_distracoes") or DISTRACOES_PADRAO:
                if self.app.apps.conhece_processo(nome):
                    executar("fechar_programa", {"nome": nome}, ctx)

    def _liberar_segurados(self) -> None:
        with self._lock:
            segurados, self._segurados = self._segurados, []
        for acao in segurados:
            try:
                acao()
            except Exception:  # noqa: BLE001
                log.exception("Erro num aviso segurado durante o foco")

    def _publicar(self) -> None:
        estado = self.estado()
        if estado is None:
            return
        dados = {**estado, "agora": time.time()}
        if self.app.hologramas.aberto("foco"):
            self.app.hologramas.atualizar_tipo("foco", dados)
        else:
            self.app.hologramas.mostrar("foco", dados, titulo="Modo foco")
        self.app.barramento.publicar("foco", ativo=True, **{k: v for k, v in dados.items() if k != "agora"})

    def _laco(self) -> None:
        while not self._parar.wait(1.0):
            with self._lock:
                estado = self._estado
                pausado = self._pausado_restante is not None
            if estado is None:
                return
            if pausado or time.time() < estado["termina"]:
                continue
            self._proxima_fase()

    def _proxima_fase(self) -> None:
        fala = self.app.fala
        with self._lock:
            e = self._estado
            if e is None:
                return
            if e["fase"] == "foco":
                if e["ciclo"] >= e["ciclos"]:
                    fim = True
                else:
                    fim = False
                    e.update(fase="pausa", termina=time.time() + e["pausa"] * 60, duracao=e["pausa"] * 60)
            else:
                fim = False
                e.update(fase="foco", ciclo=e["ciclo"] + 1, termina=time.time() + e["minutos"] * 60, duracao=e["minutos"] * 60)
            fase, ciclo, ciclos, pausa = e["fase"], e["ciclo"], e["ciclos"], e["pausa"]
        if fim:
            self.encerrar()
            fala.falar(f"Foco concluído: {ciclos} ciclo{'s' if ciclos > 1 else ''}. Bom trabalho.")
            return
        if fase == "pausa":
            self._liberar_segurados()
            fala.falar(f"Hora da pausa: {pausa} minutos. Levanta, bebe uma água.")
        else:
            fala.falar(f"De volta ao foco. Ciclo {ciclo} de {ciclos}.")
        self._publicar()
