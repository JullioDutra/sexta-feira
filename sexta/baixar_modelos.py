"""Baixa os modelos usados pela Sexta-Feira (uma vez só, ~600 MB no total).

- Vosk pt (ativação por voz, 31 MB)
- YuNet + SFace (rosto, 39 MB)
- MediaPipe Hand Landmarker (mãos, 8 MB) e Face Landmarker (piscada, 4 MB)
- Whisper (transcrição; "small" ≈ 480 MB)
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import httpx

MODELOS = [
    {
        "nome": "Rosto: detector YuNet",
        "arquivo": "face_detection_yunet_2023mar.onnx",
        "urls": ["https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
                 "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"],
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    },
    {
        "nome": "Rosto: reconhecedor SFace",
        "arquivo": "face_recognition_sface_2021dec.onnx",
        "urls": ["https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
                 "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"],
        "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    },
    {
        "nome": "Mãos: MediaPipe Hand Landmarker",
        "arquivo": "hand_landmarker.task",
        "urls": ["https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"],
    },
    {
        "nome": "Piscada: MediaPipe Face Landmarker",
        "arquivo": "face_landmarker.task",
        "urls": ["https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"],
    },
    {
        "nome": "Ativação por voz: Vosk português",
        "arquivo": "vosk-model-small-pt-0.3",
        "urls": ["https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip"],
        "zip": True,
    },
]


def _baixar(url: str, destino: Path) -> None:
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0)) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        feito = 0
        with open(destino, "wb") as f:
            for pedaco in r.iter_bytes(1 << 16):
                f.write(pedaco)
                feito += len(pedaco)
                if total:
                    pct = feito * 100 // total
                    sys.stdout.write(f"\r    {pct:3d}%  {feito / 2**20:6.1f} de {total / 2**20:.1f} MB")
                    sys.stdout.flush()
    sys.stdout.write("\n")


def _sha256(arquivo: Path) -> str:
    h = hashlib.sha256()
    with open(arquivo, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def baixar_tudo(pasta: Path, whisper: str | None = "small") -> bool:
    pasta.mkdir(parents=True, exist_ok=True)
    tudo_ok = True
    for modelo in MODELOS:
        destino = pasta / modelo["arquivo"]
        if destino.exists():
            print(f"[ok] {modelo['nome']} (já baixado)")
            continue
        print(f"[..] {modelo['nome']}")
        sucesso = False
        for url in modelo["urls"]:
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    temporario = Path(tmp) / "download"
                    _baixar(url, temporario)
                    if modelo.get("sha256") and _sha256(temporario) != modelo["sha256"]:
                        raise ValueError("arquivo corrompido (hash não confere)")
                    if modelo.get("zip"):
                        with zipfile.ZipFile(temporario) as z:
                            z.extractall(pasta)
                    else:
                        shutil.move(str(temporario), destino)
                sucesso = True
                print(f"[ok] {modelo['nome']}")
                break
            except Exception as erro:  # noqa: BLE001
                print(f"     falhou em {url.split('/')[2]}: {erro}")
        tudo_ok &= sucesso
        if not sucesso:
            print(f"[!!] Não consegui baixar {modelo['nome']}. Baixe manualmente e coloque em {pasta}")

    if whisper:
        print(f"[..] Transcrição: Whisper '{whisper}' (pode demorar na primeira vez)")
        try:
            from faster_whisper import WhisperModel

            WhisperModel(whisper, device="cpu", compute_type="int8", download_root=str(pasta / "whisper"))
            print(f"[ok] Whisper '{whisper}'")
        except Exception as erro:  # noqa: BLE001
            tudo_ok = False
            print(f"[!!] Whisper falhou: {erro}")
    return tudo_ok
