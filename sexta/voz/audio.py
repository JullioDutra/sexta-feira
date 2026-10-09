"""Entrada e saída de áudio (sounddevice) e decodificação (PyAV)."""

from __future__ import annotations

import io
import logging
import queue
import threading
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

TAXA_MIC = 16000
AMOSTRAS_BLOCO = 512  # 32 ms a 16 kHz (também é o quadro do Porcupine)


def _sd():
    import sounddevice as sd  # importado sob demanda (precisa de PortAudio)

    return sd


def resolver_dispositivo(valor: str, entrada: bool) -> int | None:
    """Aceita índice ("3") ou parte do nome ("Headset"). Vazio = padrão do Windows."""
    if not valor:
        return None
    if valor.strip().isdigit():
        return int(valor)
    sd = _sd()
    alvo = valor.lower()
    for i, disp in enumerate(sd.query_devices()):
        canais = disp["max_input_channels"] if entrada else disp["max_output_channels"]
        if canais > 0 and alvo in disp["name"].lower():
            return i
    log.warning("Dispositivo de áudio '%s' não encontrado; usando o padrão", valor)
    return None


def listar_dispositivos() -> list[dict]:
    sd = _sd()
    saida = []
    for i, disp in enumerate(sd.query_devices()):
        saida.append({"indice": i, "nome": disp["name"], "entradas": disp["max_input_channels"],
                      "saidas": disp["max_output_channels"]})
    return saida


def rms(bloco: bytes | np.ndarray) -> float:
    """Volume (RMS) na escala int16."""
    amostras = np.frombuffer(bloco, dtype=np.int16) if isinstance(bloco, (bytes, bytearray)) else bloco
    if amostras.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(amostras.astype(np.float32) ** 2)))


class Microfone:
    def __init__(self, dispositivo: str = "") -> None:
        self.dispositivo = dispositivo
        self.fila: queue.Queue[bytes] = queue.Queue(maxsize=1000)
        self._stream = None

    def iniciar(self) -> None:
        sd = _sd()
        indice = resolver_dispositivo(self.dispositivo, entrada=True)
        self._stream = sd.RawInputStream(
            samplerate=TAXA_MIC, blocksize=AMOSTRAS_BLOCO, channels=1, dtype="int16",
            device=indice, callback=self._callback,
        )
        self._stream.start()
        nome = sd.query_devices(indice if indice is not None else sd.default.device[0])["name"]
        log.info("Microfone: %s", nome)

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        try:
            self.fila.put_nowait(bytes(indata))
        except queue.Full:
            pass

    def ler(self, timeout: float = 0.5) -> bytes | None:
        try:
            return self.fila.get(timeout=timeout)
        except queue.Empty:
            return None

    def esvaziar(self) -> None:
        while True:
            try:
                self.fila.get_nowait()
            except queue.Empty:
                return

    def parar(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None


class Reprodutor:
    """Toca áudio float32 mono, interrompível, informando o volume para o HUD."""

    def __init__(self, dispositivo: str = "", ao_nivel: Callable[[float], None] | None = None) -> None:
        self.dispositivo = dispositivo
        self.ao_nivel = ao_nivel
        self._parar = threading.Event()
        self._indice: int | None = None
        self._resolvido = False

    def parar(self) -> None:
        self._parar.set()

    def tocar(self, audio: np.ndarray, taxa: int) -> bool:
        """Bloqueia até terminar. Retorna False se foi interrompido."""
        sd = _sd()
        if not self._resolvido:
            self._indice = resolver_dispositivo(self.dispositivo, entrada=False)
            self._resolvido = True
        self._parar.clear()
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        for tentativa in range(3):
            try:
                return self._tocar(sd, audio, taxa, canais=1 if tentativa == 0 else 2)
            except sd.PortAudioError as erro:
                if tentativa == 1:  # tenta 48 kHz (alguns dispositivos só aceitam a taxa nativa)
                    audio, taxa = reamostrar(audio, taxa, 48000), 48000
                log.debug("Reprodução falhou (%s); tentando outro formato", erro)
        log.error("Não consegui tocar áudio no dispositivo de saída")
        return False

    def _tocar(self, sd, audio: np.ndarray, taxa: int, canais: int) -> bool:
        posicao = 0
        terminou = threading.Event()
        interrompido = False

        def callback(outdata, frames, time_info, status):  # noqa: ARG001
            nonlocal posicao, interrompido
            if self._parar.is_set():
                interrompido = True
                outdata.fill(0)
                raise sd.CallbackStop
            pedaco = audio[posicao:posicao + frames]
            n = len(pedaco)
            outdata[:n] = pedaco[:, None] if canais == 1 else np.repeat(pedaco[:, None], canais, axis=1)
            outdata[n:] = 0
            posicao += n
            if self.ao_nivel is not None and n:
                self.ao_nivel(float(np.sqrt(np.mean(pedaco ** 2))))
            if n < frames:
                raise sd.CallbackStop

        with sd.OutputStream(samplerate=taxa, channels=canais, dtype="float32", device=self._indice,
                             callback=callback, finished_callback=terminou.set, blocksize=1024):
            while not terminou.wait(0.05):
                if self._parar.is_set():
                    interrompido = True
                    break
        if self.ao_nivel is not None:
            self.ao_nivel(0.0)
        return not interrompido


def reamostrar(audio: np.ndarray, de: int, para: int) -> np.ndarray:
    if de == para or audio.size == 0:
        return audio
    duracao = audio.size / de
    novo = int(round(duracao * para))
    x_antigo = np.linspace(0.0, duracao, audio.size, endpoint=False)
    x_novo = np.linspace(0.0, duracao, novo, endpoint=False)
    return np.interp(x_novo, x_antigo, audio).astype(np.float32)


def decodificar(dados: bytes, taxa: int | None = None) -> tuple[np.ndarray, int]:
    """Decodifica MP3/WAV/WebM/OGG/etc. para float32 mono (usa o FFmpeg embutido no PyAV)."""
    import av

    pedacos: list[np.ndarray] = []
    with av.open(io.BytesIO(dados)) as container:
        stream = container.streams.audio[0]
        taxa_saida = taxa or stream.rate or 24000
        reamostrador = av.AudioResampler(format="flt", layout="mono", rate=taxa_saida)
        for quadro in container.decode(stream):
            for convertido in reamostrador.resample(quadro):
                pedacos.append(convertido.to_ndarray().reshape(-1))
        for convertido in reamostrador.resample(None):
            pedacos.append(convertido.to_ndarray().reshape(-1))
    if not pedacos:
        return np.zeros(0, dtype=np.float32), taxa_saida
    return np.concatenate(pedacos).astype(np.float32), taxa_saida


def tom(frequencias: list[tuple[float, float]], taxa: int = 24000, volume: float = 0.22) -> np.ndarray:
    """Gera uma sequência de bipes [(frequência Hz, duração s), ...] com envelope suave."""
    partes = []
    for freq, dur in frequencias:
        n = int(taxa * dur)
        t = np.arange(n) / taxa
        onda = np.sin(2 * np.pi * freq * t) * 0.8 + np.sin(2 * np.pi * freq * 2 * t) * 0.2
        envelope = np.minimum(1.0, np.minimum(t / 0.008, (dur - t) / 0.03))
        partes.append((onda * np.clip(envelope, 0, 1) * volume).astype(np.float32))
    return np.concatenate(partes) if partes else np.zeros(0, np.float32)


SOM_ATIVACAO = [(880, 0.06), (1318.5, 0.09)]
SOM_ERRO = [(523.3, 0.09), (392, 0.14)]
SOM_DESBLOQUEIO = [(659.3, 0.07), (987.8, 0.07), (1318.5, 0.12)]
SOM_ALARME = [(1046.5, 0.18), (0, 0.08), (1046.5, 0.18), (0, 0.08), (1318.5, 0.3), (0, 0.5)]
SOM_LEMBRETE = [(784, 0.1), (1046.5, 0.1), (1318.5, 0.16)]
