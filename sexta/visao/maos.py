"""Rastreamento das mãos (MediaPipe Hand Landmarker) para mexer nos hologramas.

Envia os 21 pontos de cada mão para o HUD ~30 vezes por segundo; os gestos
(pinça = pegar, mão aberta, punho, apontar) são interpretados no próprio HUD.
A imagem é espelhada antes da análise, então "esquerda" é a sua esquerda.
"""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

MODELO_MAOS = "hand_landmarker.task"


class Maos:
    def __init__(self, app) -> None:
        self.app = app
        self._thread: threading.Thread | None = None
        self._ligado = threading.Event()
        self.ultimas: list[dict] = []
        self.fps = 0.0

    def disponivel(self) -> bool:
        return (self.app.cfg.modelos / MODELO_MAOS).exists()

    def ligado(self) -> bool:
        return self._ligado.is_set()

    def ligar(self) -> bool:
        if not self.disponivel():
            self.app.estado.aviso("maos", "Modelo de mãos não encontrado. Rode: python -m sexta baixar")
            return False
        if self._ligado.is_set():
            return True
        self._ligado.set()
        self._thread = threading.Thread(target=self._laco, name="maos", daemon=True)
        self._thread.start()
        self.app.estado.definir_maos(True)
        return True

    def desligar(self) -> None:
        if not self._ligado.is_set():
            return
        self._ligado.clear()
        self.app.estado.definir_maos(False)

    def _laco(self) -> None:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision

        camera = self.app.camera
        try:
            opcoes = vision.HandLandmarkerOptions(
                base_options=mpt.BaseOptions(model_asset_path=str(self.app.cfg.modelos / MODELO_MAOS)),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=2,
                min_hand_detection_confidence=0.6,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            detector = vision.HandLandmarker.create_from_options(opcoes)
        except Exception as erro:  # noqa: BLE001
            log.error("Não consegui iniciar o rastreamento de mãos: %s", erro)
            self.app.estado.aviso("maos", f"Rastreamento de mãos indisponível: {erro}")
            self._ligado.clear()
            self.app.estado.definir_maos(False)
            return

        camera.adquirir("maos")
        self.app.estado.aviso("maos", None)
        log.info("Rastreamento de mãos ligado")
        seq, ultimo_ts, contador, inicio_fps = 0, 0, 0, time.monotonic()
        vazio_enviado = False
        try:
            while self._ligado.is_set():
                quadro, seq = camera.esperar_quadro(seq, 1.0)
                if quadro is None:
                    continue
                rgb = cv2.cvtColor(cv2.flip(quadro, 1), cv2.COLOR_BGR2RGB)
                ts = max(int(time.monotonic() * 1000), ultimo_ts + 1)
                ultimo_ts = ts
                resultado = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
                maos = []
                for i, pontos in enumerate(resultado.hand_landmarks or []):
                    lado, confianca = "?", 0.0
                    if resultado.handedness and i < len(resultado.handedness) and resultado.handedness[i]:
                        categoria = resultado.handedness[i][0]
                        lado, confianca = categoria.category_name or "?", float(categoria.score or 0)
                    maos.append({
                        "lado": "esquerda" if lado == "Left" else "direita" if lado == "Right" else "?",
                        "conf": round(confianca, 2),
                        "p": [[round(p.x, 4), round(p.y, 4), round(p.z, 4)] for p in pontos],
                    })
                self.ultimas = maos
                if maos or not vazio_enviado:
                    self.app.barramento.publicar("maos", maos=maos)
                    vazio_enviado = not maos
                contador += 1
                if time.monotonic() - inicio_fps >= 2:
                    self.fps = contador / (time.monotonic() - inicio_fps)
                    contador, inicio_fps = 0, time.monotonic()
        except Exception:  # noqa: BLE001
            log.exception("Erro no rastreamento de mãos")
        finally:
            detector.close()
            camera.liberar("maos")
            self.ultimas = []
            self.app.barramento.publicar("maos", maos=[])
            log.info("Rastreamento de mãos desligado")
