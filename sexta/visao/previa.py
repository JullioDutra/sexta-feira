"""Prévia da câmera em MJPEG (para a tela de bloqueio, o cadastro facial e o holograma da câmera)."""

from __future__ import annotations

import time

import numpy as np

COR = (71, 181, 255)       # âmbar (BGR)
COR_OK = (140, 230, 120)
COR_ALERTA = (80, 80, 255)
CONEXOES_MAO = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
                (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]


def quadro_jpeg(app, quadro: np.ndarray, sobrepor: bool = True, largura: int = 480) -> bytes:
    import cv2

    img = cv2.flip(quadro, 1)  # espelhado, como um espelho
    h, w = img.shape[:2]
    if sobrepor:
        det = app.rosto.ultima_deteccao
        if det and time.time() - det.get("ts", 0) < 1.0:
            for r in det.get("rostos", []):
                x = int((1 - r["x"] - r["w"]) * w)
                y, rw, rh = int(r["y"] * h), int(r["w"] * w), int(r["h"] * h)
                cor = COR_OK if r.get("nome") in ("voce", "cadastro") else COR_ALERTA if r.get("nome") == "?" else COR
                _cantos(img, x, y, rw, rh, cor)
        for mao in app.maos.ultimas:
            pontos = [(int(p[0] * w), int(p[1] * h)) for p in mao["p"]]
            for a, b in CONEXOES_MAO:
                cv2.line(img, pontos[a], pontos[b], COR, 2, cv2.LINE_AA)
            for p in pontos:
                cv2.circle(img, p, 3, (255, 255, 255), -1, cv2.LINE_AA)
    if w > largura:
        img = cv2.resize(img, (largura, int(h * largura / w)), interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 72])
    return jpg.tobytes() if ok else b""


def _cantos(img, x: int, y: int, w: int, h: int, cor) -> None:
    import cv2

    t = max(12, int(min(w, h) * 0.22))
    for (px, py), (dx, dy) in (((x, y), (1, 1)), ((x + w, y), (-1, 1)), ((x, y + h), (1, -1)), ((x + w, y + h), (-1, -1))):
        cv2.line(img, (px, py), (px + dx * t, py), cor, 2, cv2.LINE_AA)
        cv2.line(img, (px, py), (px, py + dy * t), cor, 2, cv2.LINE_AA)
