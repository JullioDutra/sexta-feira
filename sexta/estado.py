"""Estado visível da assistente (o HUD anima o núcleo de acordo com ele)."""

from __future__ import annotations

import threading

ESTADOS = {"iniciando", "inativa", "ouvindo", "pensando", "falando", "verificando"}


class Estado:
    def __init__(self, barramento) -> None:
        self.barramento = barramento
        self._lock = threading.Lock()
        self.atual = "iniciando"
        self.microfone_ligado = True
        self.maos_ligadas = False
        self.camera_em_uso = False
        self.avisos: dict[str, str] = {}

    def definir(self, novo: str) -> None:
        if novo not in ESTADOS:
            raise ValueError(novo)
        with self._lock:
            if novo == self.atual:
                return
            self.atual = novo
        self.barramento.publicar("estado", estado=novo)

    def definir_microfone(self, ligado: bool) -> None:
        self.microfone_ligado = ligado
        self.publicar_status()

    def definir_maos(self, ligadas: bool) -> None:
        self.maos_ligadas = ligadas
        self.publicar_status()

    def definir_camera(self, em_uso: bool) -> None:
        if self.camera_em_uso != em_uso:
            self.camera_em_uso = em_uso
            self.publicar_status()

    def aviso(self, chave: str, texto: str | None) -> None:
        """Avisos persistentes (ex.: "Ollama fora do ar") exibidos no HUD até sumirem."""
        with self._lock:
            if texto:
                self.avisos[chave] = texto
            else:
                self.avisos.pop(chave, None)
        self.publicar_status()

    def status(self) -> dict:
        return {
            "estado": self.atual,
            "microfone": self.microfone_ligado,
            "maos": self.maos_ligadas,
            "camera": self.camera_em_uso,
            "avisos": dict(self.avisos),
        }

    def publicar_status(self) -> None:
        self.barramento.publicar("status", **self.status())
