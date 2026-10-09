"""Transcrição de fala em português com faster-whisper (roda no próprio PC)."""

from __future__ import annotations

import logging
import threading

import numpy as np

log = logging.getLogger(__name__)

# Frases que o Whisper costuma "alucinar" em silêncio ou ruído
ALUCINACOES = (
    "legendas pela comunidade", "amara.org", "obrigado por assistir", "inscreva-se no canal",
    "legendado por", "transcrição por", "tradução e legendas", "e aí, pessoal", "sous-titres",
)


class Transcritor:
    def __init__(self, modelo: str = "small", dispositivo: str = "auto", pasta_modelos=None) -> None:
        self.nome_modelo = modelo
        self.dispositivo_pedido = dispositivo
        self.pasta_modelos = pasta_modelos
        self._modelo = None
        self._lock = threading.Lock()
        self.dispositivo = "cpu"

    def carregar(self) -> None:
        with self._lock:
            if self._modelo is not None:
                return
            from faster_whisper import WhisperModel

            raiz = str(self.pasta_modelos) if self.pasta_modelos else None
            tentativas = []
            if self.dispositivo_pedido in ("auto", "cuda") and _tem_cuda():
                tentativas.append(("cuda", "float16"))
            if self.dispositivo_pedido != "cuda" or not tentativas:
                tentativas.append(("cpu", "int8"))
            ultimo_erro = None
            for dispositivo, tipo in tentativas:
                try:
                    modelo = WhisperModel(self.nome_modelo, device=dispositivo, compute_type=tipo, download_root=raiz)
                    # aquecimento: valida se as bibliotecas de GPU funcionam de verdade
                    list(modelo.transcribe(np.zeros(16000, dtype=np.float32), language="pt", beam_size=1)[0])
                    self._modelo, self.dispositivo = modelo, dispositivo
                    log.info("Whisper '%s' carregado em %s (%s)", self.nome_modelo, dispositivo, tipo)
                    return
                except Exception as erro:  # noqa: BLE001 - cai para a CPU se a GPU falhar
                    ultimo_erro = erro
                    log.warning("Whisper em %s falhou (%s); tentando alternativa", dispositivo, erro)
            raise RuntimeError(f"Não foi possível carregar o Whisper: {ultimo_erro}")

    def transcrever(self, audio: np.ndarray, dica: str = "") -> str:
        """``audio``: float32 mono 16 kHz."""
        if audio.size < 16000 * 0.25:
            return ""
        self.carregar()
        with self._lock:
            segmentos, _info = self._modelo.transcribe(
                audio,
                language="pt",
                beam_size=5 if self.dispositivo == "cuda" else 2,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
                condition_on_previous_text=False,
                initial_prompt=dica or "Conversa em português do Brasil com a assistente Sexta-Feira.",
                no_speech_threshold=0.6,
            )
            textos = []
            for seg in segmentos:
                if seg.no_speech_prob > 0.75 and seg.avg_logprob < -0.8:
                    continue
                textos.append(seg.text.strip())
        texto = " ".join(t for t in textos if t).strip()
        if any(a in texto.lower() for a in ALUCINACOES):
            log.debug("Transcrição descartada (alucinação): %s", texto)
            return ""
        return texto


def _tem_cuda() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False
