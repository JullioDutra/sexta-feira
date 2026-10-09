"""Detecção da palavra de ativação ("Sexta-Feira").

Padrão: **Vosk** offline com gramática restrita — não precisa de conta nem chave.
Como "sexta-feira" também é um dia da semana, ela só ativa quando o nome é a
*primeira coisa* dita depois de uma pausa ("Sexta-Feira, que horas são?"), e não
no meio de uma frase ("na sexta-feira passada...").

Opcional: **Porcupine** (Picovoice) com uma palavra treinada no console deles —
mais preciso, mas exige chave gratuita. Ver README.
"""

from __future__ import annotations

import json
import logging
import struct
from pathlib import Path

from ..util.texto import normalizar

log = logging.getLogger(__name__)

PREFIXOS = ["", "ei ", "oi ", "ok "]


class DetectorVosk:
    def __init__(self, caminho_modelo: Path, frases: list[str]) -> None:
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        if not caminho_modelo.exists():
            raise FileNotFoundError(
                f"Modelo de voz do Vosk não encontrado em {caminho_modelo}. Rode: python -m sexta baixar")
        self.modelo = Model(str(caminho_modelo))
        base = [normalizar(f) for f in frases if normalizar(f)]
        self.frases = sorted({p + f for f in base for p in PREFIXOS}, key=len, reverse=True)
        gramatica = json.dumps(self.frases + ["[unk]"], ensure_ascii=False)
        self._rec = KaldiRecognizer(self.modelo, 16000, gramatica)
        log.info("Ativação por voz (Vosk): %s", ", ".join(base))

    def processar(self, bloco: bytes) -> bool:
        if self._rec.AcceptWaveform(bloco):
            texto = json.loads(self._rec.Result()).get("text", "")
        else:
            texto = json.loads(self._rec.PartialResult()).get("partial", "")
        texto = texto.strip()
        if texto and any(texto.startswith(f) for f in self.frases):
            self._rec.Reset()
            return True
        return False

    def reiniciar(self) -> None:
        self._rec.Reset()


class DetectorPorcupine:
    def __init__(self, chave: str, arquivo_ppn: str, modelo_pv: str = "", sensibilidade: float = 0.6) -> None:
        import pvporcupine

        argumentos = {"access_key": chave, "keyword_paths": [arquivo_ppn], "sensitivities": [sensibilidade]}
        if modelo_pv:
            argumentos["model_path"] = modelo_pv
        self._porcupine = pvporcupine.create(**argumentos)
        self._quadro = self._porcupine.frame_length
        self._buffer = b""
        log.info("Ativação por voz (Porcupine): %s", Path(arquivo_ppn).name)

    def processar(self, bloco: bytes) -> bool:
        self._buffer += bloco
        tamanho = self._quadro * 2
        while len(self._buffer) >= tamanho:
            quadro = struct.unpack_from(f"{self._quadro}h", self._buffer[:tamanho])
            self._buffer = self._buffer[tamanho:]
            if self._porcupine.process(quadro) >= 0:
                self._buffer = b""
                return True
        return False

    def reiniciar(self) -> None:
        self._buffer = b""


def criar_detector(cfg):
    """Cria o detector configurado; ``None`` se a ativação por voz estiver desligada."""
    motor = cfg.ativacao_motor
    if motor in {"nenhum", "desligado", "off"}:
        return None
    if motor == "porcupine":
        if not (cfg.porcupine_chave and cfg.porcupine_arquivo):
            raise ValueError("Para usar o Porcupine, preencha PORCUPINE_CHAVE e PORCUPINE_ARQUIVO no .env")
        return DetectorPorcupine(cfg.porcupine_chave, cfg.porcupine_arquivo, cfg.porcupine_modelo)
    return DetectorVosk(cfg.modelos / "vosk-model-small-pt-0.3", cfg.ativacao_frases)
