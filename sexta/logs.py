"""Configuração de logs (console + arquivo com rotação)."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMATO = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configurar_logs(pasta: Path, nivel: str = "INFO") -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    raiz = logging.getLogger()
    raiz.setLevel(getattr(logging, nivel.upper(), logging.INFO))
    for handler in list(raiz.handlers):
        raiz.removeHandler(handler)

    arquivo = RotatingFileHandler(pasta / "sexta.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    arquivo.setFormatter(logging.Formatter(FORMATO, "%Y-%m-%d %H:%M:%S"))
    raiz.addHandler(arquivo)

    # pythonw (sem console) não tem stdout
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        raiz.addHandler(console)

    for barulhento in ("httpx", "httpcore", "uvicorn.access", "comtypes", "faster_whisper", "asyncio"):
        logging.getLogger(barulhento).setLevel(logging.WARNING)
