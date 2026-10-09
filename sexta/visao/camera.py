"""Webcam compartilhada: um único dono da câmera, vários usuários (rosto, mãos, prévia).

A câmera liga sob demanda e desliga sozinha alguns segundos depois que ninguém
mais está usando (a luz da webcam não fica acesa à toa).
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

BACKENDS = {"dshow": 700, "msmf": 1400, "v4l2": 200, "auto": 0}  # valores de cv2.CAP_*
OCIOSA_DESLIGA_S = 6.0


class Camera:
    def __init__(self, app) -> None:
        self.app = app
        self._usuarios: set[str] = set()
        self._lock = threading.Lock()
        self._cond = threading.Condition()
        self._quadro: np.ndarray | None = None
        self._seq = 0
        self._thread: threading.Thread | None = None
        self.erro: str | None = None
        self.fonte_teste = None  # callable -> quadro (usado nos testes)

    # -- uso -------------------------------------------------------------
    def adquirir(self, nome: str) -> None:
        with self._lock:
            self._usuarios.add(nome)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._laco, name="camera", daemon=True)
                self._thread.start()

    def liberar(self, nome: str) -> None:
        with self._lock:
            self._usuarios.discard(nome)

    def em_uso(self) -> bool:
        with self._lock:
            return bool(self._usuarios)

    def esperar_quadro(self, seq_anterior: int, timeout: float = 1.0) -> tuple[np.ndarray | None, int]:
        """Espera um quadro mais novo que ``seq_anterior``."""
        limite = time.monotonic() + timeout
        with self._cond:
            while self._seq <= seq_anterior:
                restante = limite - time.monotonic()
                if restante <= 0:
                    return None, seq_anterior
                self._cond.wait(restante)
            return self._quadro, self._seq

    # -- captura -----------------------------------------------------------
    def _abrir(self):
        import cv2

        cfg = self.app.cfg
        backend = BACKENDS.get(cfg.camera_backend, 0)
        cap = cv2.VideoCapture(cfg.camera_indice, backend)
        if not cap.isOpened() and backend:
            cap = cv2.VideoCapture(cfg.camera_indice)
        if not cap.isOpened():
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.camera_largura)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.camera_altura)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _laco(self) -> None:
        cap = None
        ociosa_desde = None
        falhas = 0
        try:
            if self.fonte_teste is None:
                cap = self._abrir()
                if cap is None:
                    self.erro = f"Não consegui abrir a câmera {self.app.cfg.camera_indice}. Ela está em uso por outro programa?"
                    log.error(self.erro)
                    self.app.estado.aviso("camera", self.erro)
                    with self._lock:
                        self._usuarios.clear()
                    return
                log.info("Câmera ligada")
            self.erro = None
            self.app.estado.aviso("camera", None)
            self.app.estado.definir_camera(True)
            while True:
                if not self.em_uso():
                    ociosa_desde = ociosa_desde or time.monotonic()
                    if time.monotonic() - ociosa_desde > OCIOSA_DESLIGA_S:
                        break
                else:
                    ociosa_desde = None
                if self.fonte_teste is not None:
                    quadro = self.fonte_teste()
                    ok = quadro is not None
                    time.sleep(1 / 30)
                else:
                    ok, quadro = cap.read()
                if not ok:
                    falhas += 1
                    if falhas > 30:
                        log.warning("Câmera parou de enviar imagens; reabrindo")
                        cap.release()
                        time.sleep(1)
                        cap = self._abrir()
                        falhas = 0
                        if cap is None:
                            break
                    time.sleep(0.03)
                    continue
                falhas = 0
                with self._cond:
                    self._quadro = quadro
                    self._seq += 1
                    self._cond.notify_all()
        except Exception:  # noqa: BLE001
            log.exception("Erro na câmera")
        finally:
            if cap is not None:
                cap.release()
            with self._lock:
                self._thread = None
                reiniciar = bool(self._usuarios)
            self.app.estado.definir_camera(False)
            log.info("Câmera desligada")
            if reiniciar and self.erro is None:  # alguém pediu a câmera enquanto ela desligava
                self.adquirir(next(iter(self._usuarios), "retomada"))
