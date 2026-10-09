"""Voz da Sexta-Feira.

- Voz neural da Microsoft via ``edge-tts`` (precisa de internet, gratuita).
- Sem internet, cai automaticamente para as vozes do Windows (``pyttsx3``/SAPI).
- Fala em pipeline: enquanto uma frase toca, a próxima já está sendo sintetizada.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np

from ..util.texto import limpar_para_fala
from .audio import Reprodutor, decodificar, tom

log = logging.getLogger(__name__)


class Fala:
    def __init__(self, app) -> None:
        self.app = app
        cfg = app.cfg
        self._ultimo_nivel = 0.0
        self.reprodutor = Reprodutor(cfg.alto_falante, ao_nivel=self._nivel)
        self._textos: queue.Queue = queue.Queue()
        self._audios: queue.Queue = queue.Queue(maxsize=3)
        self._geracao = 0
        self._tocando = False
        self._pendentes = 0  # itens ainda não tocados (na fila, sintetizando ou tocando)
        self._lock = threading.Lock()
        self._ocioso = threading.Event()
        self._ocioso.set()
        self._cache: OrderedDict[tuple, tuple[np.ndarray, int]] = OrderedDict()
        self._edge_falhas = 0
        self._edge_pausado_ate = 0.0
        self._loop = asyncio.new_event_loop()
        self._pyttsx3 = None
        self._rodando = True
        threading.Thread(target=self._loop_sintese, name="sintese", daemon=True).start()
        threading.Thread(target=self._loop_reproducao, name="reproducao", daemon=True).start()

    # -- API ------------------------------------------------------------
    @property
    def voz(self) -> str:
        return self.app.prefs.get("voz") or self.app.cfg.voz

    def falar(self, texto: str) -> None:
        texto = limpar_para_fala(texto or "")
        if texto:
            self._enfileirar(texto)

    def _enfileirar(self, item) -> None:
        with self._lock:
            self._pendentes += 1
            self._ocioso.clear()
            geracao = self._geracao
        self._textos.put((geracao, item))

    def _concluir(self, quantidade: int = 1) -> None:
        with self._lock:
            self._pendentes = max(0, self._pendentes - quantidade)
            terminou = self._pendentes == 0
            if terminou:
                self._ocioso.set()
        if terminou and self.app.estado.atual == "falando":
            agente = getattr(self.app, "agente", None)
            self.app.estado.definir("pensando" if agente and agente.ocupado() else "inativa")

    def falar_e_esperar(self, texto: str, timeout: float = 60.0) -> None:
        self.falar(texto)
        self.aguardar(timeout)

    def tocar_som(self, notas, esperar: bool = False) -> None:
        """Toca um efeito sonoro curto (bipes) pela mesma fila da voz."""
        self._enfileirar(("__som__", tom(notas), 24000))
        if esperar:
            self.aguardar(5)

    def parar(self) -> None:
        with self._lock:
            self._geracao += 1
        descartados = 0
        for fila in (self._textos, self._audios):
            while True:
                try:
                    fila.get_nowait()
                    descartados += 1
                except queue.Empty:
                    break
        if descartados:
            self._concluir(descartados)
        self.reprodutor.parar()

    def falando(self) -> bool:
        return self._tocando

    def falando_ou_na_fila(self) -> bool:
        return not self._ocioso.is_set()

    def aguardar(self, timeout: float = 60.0) -> bool:
        return self._ocioso.wait(timeout)

    def gerar_audio(self, texto: str) -> tuple[bytes, str] | None:
        """Sintetiza um MP3 para tocar em outro aparelho (celular). ``None`` se a voz online falhar.

        Roda num loop asyncio próprio, então pode ser chamada de qualquer thread.
        """
        texto = limpar_para_fala(texto)
        if not texto or self.app.cfg.voz_motor == "windows":
            return None
        try:
            return asyncio.run(asyncio.wait_for(self._edge_bytes(texto), timeout=20)), "audio/mpeg"
        except Exception as erro:  # noqa: BLE001
            log.warning("Não consegui gerar o áudio para o celular: %s", erro)
            return None

    def encerrar(self) -> None:
        self._rodando = False
        self.parar()

    # -- internos ---------------------------------------------------------
    def _nivel(self, valor: float) -> None:
        agora = time.monotonic()
        if agora - self._ultimo_nivel >= 0.033 or valor == 0.0:
            self._ultimo_nivel = agora
            self.app.barramento.publicar("fala.nivel", nivel=round(min(1.0, valor * 4.0), 3))

    def _executar(self, coro):
        return self._loop.run_until_complete(asyncio.wait_for(coro, timeout=20))

    async def _edge_bytes(self, texto: str) -> bytes:
        import edge_tts

        comunicacao = edge_tts.Communicate(texto, self.voz, rate=self.app.cfg.voz_velocidade, pitch=self.app.cfg.voz_tom,
                                           connect_timeout=4, receive_timeout=15)
        dados = bytearray()
        async for pedaco in comunicacao.stream():
            if pedaco.get("type") == "audio":
                dados += pedaco["data"]
        if not dados:
            raise RuntimeError("edge-tts não devolveu áudio")
        return bytes(dados)

    def _sintetizar(self, texto: str) -> tuple[np.ndarray, int]:
        chave = (self.voz, texto)
        if chave in self._cache:
            self._cache.move_to_end(chave)
            return self._cache[chave]
        resultado = None
        if self.app.cfg.voz_motor != "windows" and time.time() >= self._edge_pausado_ate:
            try:
                resultado = decodificar(self._executar(self._edge_bytes(texto)))
                self._edge_falhas = 0
            except Exception as erro:  # noqa: BLE001
                self._edge_falhas += 1
                log.warning("Voz online indisponível (%s); usando voz do Windows", erro)
                if self._edge_falhas >= 2:
                    self._edge_pausado_ate = time.time() + 300
        if resultado is None:
            resultado = self._sintetizar_windows(texto)
        if len(texto) <= 80:
            self._cache[chave] = resultado
            while len(self._cache) > 60:
                self._cache.popitem(last=False)
        return resultado

    def _sintetizar_windows(self, texto: str) -> tuple[np.ndarray, int]:
        import pyttsx3

        if self._pyttsx3 is None:
            try:  # o SAPI do Windows usa COM: inicializa nesta thread
                import comtypes

                comtypes.CoInitialize()
            except Exception:  # noqa: BLE001
                pass
            motor = pyttsx3.init()
            for voz in motor.getProperty("voices"):
                descricao = f"{voz.name} {voz.id} {getattr(voz, 'languages', '')}".lower()
                if "portugu" in descricao or "pt-br" in descricao or "pt_br" in descricao or "maria" in descricao:
                    motor.setProperty("voice", voz.id)
                    break
            motor.setProperty("rate", 185)
            self._pyttsx3 = motor
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "fala.wav"
            self._pyttsx3.save_to_file(texto, str(arquivo))
            self._pyttsx3.runAndWait()
            return decodificar(arquivo.read_bytes())

    def _loop_sintese(self) -> None:
        asyncio.set_event_loop(self._loop)
        while self._rodando:
            try:
                geracao, item = self._textos.get(timeout=0.5)
            except queue.Empty:
                continue
            if geracao != self._geracao:
                self._concluir()
                continue
            try:
                if isinstance(item, tuple) and item[0] == "__som__":
                    audio, taxa, texto = item[1], item[2], ""
                else:
                    texto = item
                    audio, taxa = self._sintetizar(texto)
            except Exception:  # noqa: BLE001
                log.exception("Falha ao sintetizar fala")
                self._concluir()
                continue
            if geracao != self._geracao:
                self._concluir()
                continue
            self._audios.put((geracao, audio, taxa, texto))

    def _loop_reproducao(self) -> None:
        while self._rodando:
            try:
                geracao, audio, taxa, texto = self._audios.get(timeout=0.5)
            except queue.Empty:
                continue
            if geracao != self._geracao:
                self._concluir()
                continue
            self._tocando = True
            if texto:
                self.app.estado.definir("falando")
                self.app.barramento.publicar("fala.inicio", texto=texto)
            try:
                self.reprodutor.tocar(audio, taxa)
            except Exception:  # noqa: BLE001
                log.exception("Falha ao tocar áudio")
            finally:
                self._tocando = False
                if texto:
                    self.app.barramento.publicar("fala.fim", texto=texto)
                self._concluir()

