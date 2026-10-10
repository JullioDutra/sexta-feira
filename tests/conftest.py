"""Fixtures dos testes: uma Sexta-Feira completa, mas sem áudio, câmera real nem rede."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


class FalaFalsa:
    """Substitui a voz: só guarda o que seria falado."""

    def __init__(self) -> None:
        self.falas: list[str] = []
        self.sons = 0
        self._lock = threading.Lock()

    def falar(self, texto: str) -> None:
        if texto and texto.strip():
            with self._lock:
                self.falas.append(texto.strip())

    def falar_e_esperar(self, texto: str, timeout: float = 0) -> None:
        self.falar(texto)

    def tocar_som(self, *_a, **_k) -> None:
        self.sons += 1

    def parar(self) -> None:
        pass

    def falando(self) -> bool:
        return False

    def falando_ou_na_fila(self) -> bool:
        return False

    def aguardar(self, timeout: float = 0) -> bool:
        return True

    def gerar_audio(self, texto: str):
        return (b"ID3falso", "audio/mpeg")

    def encerrar(self) -> None:
        pass

    def tudo(self) -> str:
        return " ".join(self.falas)


@pytest.fixture
def cfg(tmp_path):
    from sexta.config import Config

    c = Config()
    c.dados = tmp_path / "dados"
    c.abrir_hud = False
    c.liberar_rede = False
    c.cerebro = "ollama"  # os testes usam um Ollama simulado; o Claude tem testes próprios
    c.garantir_pastas()
    return c


@pytest.fixture
def app(cfg, tmp_path, monkeypatch):
    from sexta.app import SextaFeira

    # rotinas de exemplo do projeto + arquivo de rotinas criadas isolado
    monkeypatch.setattr("sexta.config.Config.pasta_config", property(lambda self: tmp_path / "config"))
    pasta = tmp_path / "config"
    pasta.mkdir()
    for nome in ("rotinas.yaml", "layouts.yaml", "terminal.yaml", "noticias.yaml"):
        (pasta / nome).write_text((RAIZ / "config" / nome).read_text(encoding="utf-8"), encoding="utf-8")
    (pasta / "apps.yaml").write_text("apps:\n  meu site: https://exemplo.com\nsites:\n", encoding="utf-8")
    sexta = SextaFeira(cfg, com_voz=False)
    sexta.fala.encerrar()
    sexta.fala = FalaFalsa()
    yield sexta
    sexta.hologramas._rodando = False
