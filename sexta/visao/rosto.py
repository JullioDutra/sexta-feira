"""Reconhecimento facial local (OpenCV YuNet + SFace) com teste de piscada.

- Cadastro: ~20 amostras em poses diferentes, guardadas só como vetores numéricos
  (``dados/rosto/assinaturas.npy``) — nenhuma foto é salva.
- Verificação: compara o rosto da câmera com as amostras (similaridade de cosseno).
- Vivacidade: para desbloquear, exige uma piscada (MediaPipe Face Landmarker),
  o que impede que uma foto impressa ou no celular engane a câmera.

Isto protege a *Sexta-Feira*. Para a tela de bloqueio do Windows use o
Windows Hello (ver README).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

MODELO_DETECTOR = "face_detection_yunet_2023mar.onnx"
MODELO_RECONHECEDOR = "face_recognition_sface_2021dec.onnx"
MODELO_MARCOS = "face_landmarker.task"


class ErroModelos(RuntimeError):
    """Os modelos de rosto existem mas não puderam ser carregados."""


@dataclass
class Resultado:
    ok: bool
    motivo: str = ""          # "ok", "sem_rosto", "desconhecido", "sem_piscada", "sem_cadastro", "erro"
    similaridade: float = 0.0


@dataclass
class Fase:
    instrucao: str
    amostras: int
    condicao: str  # "frente", "lado1", "lado2", "vert1", "vert2"


PLANO_CADASTRO = [
    Fase("Olhe direto para a câmera", 6, "frente"),
    Fase("Vire o rosto devagar para um lado", 4, "lado1"),
    Fase("Agora vire para o outro lado", 4, "lado2"),
    Fase("Incline a cabeça um pouco para cima", 3, "vert1"),
    Fase("Agora um pouco para baixo", 3, "vert2"),
]


class Rosto:
    LIMIAR_DUPLICADA = 0.985  # amostras quase idênticas não acrescentam nada ao cadastro

    def __init__(self, app) -> None:
        self.app = app
        self.pasta = app.cfg.dados / "rosto"
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo = self.pasta / "assinaturas.npy"
        self.arquivo_meta = self.pasta / "cadastro.json"
        self._det = None
        self._rec = None
        self._marcos = None
        self._marcos_indisponivel = False
        self._lock = threading.Lock()
        self._carga = threading.Lock()
        self._assinaturas: np.ndarray | None = None
        self.ultima_deteccao: dict = {}
        self._ocupado = threading.Lock()
        self.cancelar_evento = threading.Event()
        if self.arquivo.exists():
            try:
                self._assinaturas = np.load(self.arquivo)
            except (OSError, ValueError):
                self._assinaturas = None

    # -- estado ------------------------------------------------------------
    def modelos_presentes(self) -> bool:
        return all((self.app.cfg.modelos / m).exists() for m in (MODELO_DETECTOR, MODELO_RECONHECEDOR))

    def cadastrado(self) -> bool:
        return self._assinaturas is not None and len(self._assinaturas) >= 5

    def info(self) -> dict:
        meta = {}
        if self.arquivo_meta.exists():
            try:
                meta = json.loads(self.arquivo_meta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        return {"cadastrado": self.cadastrado(), "modelos": self.modelos_presentes(),
                "piscada_disponivel": (self.app.cfg.modelos / MODELO_MARCOS).exists(), **meta}

    def apagar(self) -> None:
        with self._lock:
            self._assinaturas = None
            for arquivo in (self.arquivo, self.arquivo_meta):
                arquivo.unlink(missing_ok=True)
        log.info("Cadastro facial apagado")

    # -- modelos -----------------------------------------------------------
    def _carregar(self) -> None:
        if self._det is not None:
            return
        import cv2

        try:
            cv2.setLogLevel(2)  # só erros
        except AttributeError:
            pass
        modelos = self.app.cfg.modelos
        if not self.modelos_presentes():
            raise FileNotFoundError("Modelos de rosto não encontrados. Rode: python -m sexta baixar")
        with self._carga:
            if self._det is not None:
                return
            # O Python lê o arquivo e o OpenCV recebe os bytes: no Windows a leitura pelo caminho
            # às vezes falha ("Can't read ONNX file") quando outro programa (antivírus, indexador)
            # está com o arquivo aberto. Tenta algumas vezes antes de desistir.
            vazio = np.array([], dtype=np.uint8)
            ultimo_erro: Exception | None = None
            for tentativa in range(4):
                try:
                    det_bytes = np.frombuffer((modelos / MODELO_DETECTOR).read_bytes(), dtype=np.uint8)
                    rec_bytes = np.frombuffer((modelos / MODELO_RECONHECEDOR).read_bytes(), dtype=np.uint8)
                    det = cv2.FaceDetectorYN.create("onnx", det_bytes, vazio, (320, 320), 0.85, 0.3, 5000)
                    rec = cv2.FaceRecognizerSF.create("onnx", rec_bytes, vazio)
                    self._det, self._rec = det, rec
                    return
                except Exception as erro:  # noqa: BLE001
                    ultimo_erro = erro
                    time.sleep(0.5 * (tentativa + 1))
            raise ErroModelos(
                f"Não consegui abrir os modelos de rosto ({str(ultimo_erro).strip()[:160]}). "
                "Apague os arquivos .onnx em dados/modelos e rode: iniciar.bat baixar") from ultimo_erro

    def _carregar_marcos(self):
        if self._marcos is not None or self._marcos_indisponivel:
            return self._marcos
        caminho = self.app.cfg.modelos / MODELO_MARCOS
        if not caminho.exists():
            self._marcos_indisponivel = True
            log.warning("Modelo de piscada (%s) ausente: verificação sem teste de vivacidade", MODELO_MARCOS)
            return None
        try:
            from mediapipe.tasks import python as mpt
            from mediapipe.tasks.python import vision

            opcoes = vision.FaceLandmarkerOptions(
                base_options=mpt.BaseOptions(model_asset_path=str(caminho)),
                running_mode=vision.RunningMode.IMAGE, num_faces=1, output_face_blendshapes=True)
            self._marcos = vision.FaceLandmarker.create_from_options(opcoes)
        except Exception as erro:  # noqa: BLE001
            log.warning("Face Landmarker indisponível (%s)", erro)
            self._marcos_indisponivel = True
        return self._marcos

    # -- análise -------------------------------------------------------------
    def detectar(self, quadro: np.ndarray) -> list[np.ndarray]:
        self._carregar()
        h, w = quadro.shape[:2]
        with self._lock:
            self._det.setInputSize((w, h))
            _, rostos = self._det.detect(quadro)
        if rostos is None:
            return []
        return sorted(list(rostos), key=lambda r: r[2] * r[3], reverse=True)

    def assinatura(self, quadro: np.ndarray, rosto: np.ndarray) -> np.ndarray:
        with self._lock:
            alinhado = self._rec.alignCrop(quadro, rosto)
            vetor = self._rec.feature(alinhado).flatten().astype(np.float32)
        return vetor / (np.linalg.norm(vetor) + 1e-9)

    def similaridade(self, vetor: np.ndarray) -> float:
        if self._assinaturas is None or not len(self._assinaturas):
            return 0.0
        sims = self._assinaturas @ vetor
        melhores = np.sort(sims)[-3:]
        return float(np.mean(melhores))

    @staticmethod
    def pose(rosto: np.ndarray) -> tuple[float, float]:
        """(yaw, razão vertical) aproximados a partir dos 5 pontos do YuNet."""
        olho_d, olho_e = np.array(rosto[4:6]), np.array(rosto[6:8])
        nariz = np.array(rosto[8:10])
        boca = (np.array(rosto[10:12]) + np.array(rosto[12:14])) / 2
        meio_olhos = (olho_d + olho_e) / 2
        distancia_olhos = np.linalg.norm(olho_e - olho_d) + 1e-6
        yaw = float((nariz[0] - meio_olhos[0]) / distancia_olhos)
        vertical = float((nariz[1] - meio_olhos[1]) / (boca[1] - meio_olhos[1] + 1e-6))
        return yaw, vertical

    def _registrar_deteccao(self, quadro, rosto, nome: str, sim: float) -> None:
        h, w = quadro.shape[:2]
        if rosto is None:
            self.ultima_deteccao = {"ts": time.time(), "rostos": []}
            return
        x, y, rw, rh = (float(v) for v in rosto[:4])
        self.ultima_deteccao = {"ts": time.time(), "w": w, "h": h, "rostos": [
            {"x": x / w, "y": y / h, "w": rw / w, "h": rh / h, "nome": nome, "sim": round(sim, 3)}]}

    # -- verificação -----------------------------------------------------------
    def verificar(self, timeout: float = 6.0, exigir_piscada: bool = False,
                  progresso: Callable[[str, float], None] | None = None) -> Resultado:
        if not self.cadastrado():
            return Resultado(False, "sem_cadastro")
        try:
            self._carregar()
        except Exception as erro:  # noqa: BLE001
            log.error("%s", erro)
            self.app.estado.aviso("rosto", str(erro))
            return Resultado(False, "erro")
        self.app.estado.aviso("rosto", None)
        limiar = float(self.app.prefs.get("limiar_rosto") or 0.42)
        marcos = self._carregar_marcos() if exigir_piscada else None
        precisa_piscar = exigir_piscada and marcos is not None
        progresso = progresso or (lambda fase, sim: None)
        camera = self.app.camera
        nome_uso = f"verificacao-{threading.get_ident()}"
        self.cancelar_evento.clear()
        camera.adquirir(nome_uso)
        seq, seguidos, melhor = 0, 0, 0.0
        olho_fechado, piscou, identidade_antes = False, False, False
        identificado_em, fechou_em = 0.0, 0.0
        fim = time.monotonic() + timeout
        ultima_fase = ""
        try:
            while time.monotonic() < fim and not self.cancelar_evento.is_set():
                quadro, seq = camera.esperar_quadro(seq, 1.5)
                if quadro is None:
                    if camera.erro:
                        return Resultado(False, "erro")
                    continue
                rostos = self.detectar(quadro)
                if not rostos:
                    seguidos = 0
                    self._registrar_deteccao(quadro, None, "", 0)
                    fase = "procurando"
                else:
                    rosto = rostos[0]
                    sim = self.similaridade(self.assinatura(quadro, rosto))
                    melhor = max(melhor, sim)
                    reconhecido = sim >= limiar
                    seguidos = seguidos + 1 if reconhecido else 0
                    self._registrar_deteccao(quadro, rosto, "voce" if reconhecido else "?", sim)
                    if seguidos >= 3:
                        identificado_em = time.monotonic()
                    fase = "analisando" if not reconhecido else "reconhecido"
                    if precisa_piscar and marcos is not None:
                        # A piscada só vale se o rosto reconhecido estava ali logo antes de fechar
                        # os olhos e reabriu rápido (foto não pisca; outra pessoa não é reconhecida).
                        fechado = self._olhos_fechados(marcos, quadro)
                        agora = time.monotonic()
                        if fechado is True and not olho_fechado:
                            olho_fechado = True
                            fechou_em = agora
                            identidade_antes = seguidos >= 2 or agora - identificado_em < 0.4
                        elif fechado is False and olho_fechado:
                            if identidade_antes and agora - fechou_em < 1.0:
                                piscou = True
                            olho_fechado = False
                    if seguidos >= 3 and (not precisa_piscar or piscou):
                        progresso("ok", sim)
                        return Resultado(True, "ok", sim)
                    if seguidos >= 3 and precisa_piscar:
                        fase = "pisque"
                    elif rostos and not reconhecido and sim < limiar * 0.8:
                        fase = "desconhecido"
                if fase != ultima_fase:
                    progresso(fase, melhor)
                    ultima_fase = fase
            if self.cancelar_evento.is_set():
                return Resultado(False, "cancelado", melhor)
            if seguidos >= 3 or melhor >= limiar:
                return Resultado(False, "sem_piscada" if precisa_piscar else "desconhecido", melhor)
            return Resultado(False, "desconhecido" if melhor > 0 else "sem_rosto", melhor)
        finally:
            camera.liberar(nome_uso)
            self.ultima_deteccao = {}

    def _olhos_fechados(self, marcos, quadro: np.ndarray) -> bool | None:
        import cv2
        import mediapipe as mp

        rgb = cv2.cvtColor(quadro, cv2.COLOR_BGR2RGB)
        try:
            resultado = marcos.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        except Exception:  # noqa: BLE001
            return None
        if not resultado.face_blendshapes:
            return None
        valores = {c.category_name: c.score for c in resultado.face_blendshapes[0]}
        piscada = (valores.get("eyeBlinkLeft", 0) + valores.get("eyeBlinkRight", 0)) / 2
        if piscada > 0.5:
            return True
        if piscada < 0.25:
            return False
        return None

    # -- cadastro --------------------------------------------------------------
    def cadastrar(self, progresso: Callable[[dict], None], timeout: float = 90.0,
                  plano: list[Fase] | None = None) -> bool:
        if not self._ocupado.acquire(blocking=False):
            return False
        plano = plano or PLANO_CADASTRO
        total = sum(f.amostras for f in plano)
        camera = self.app.camera
        self.cancelar_evento.clear()
        try:
            self._carregar()
            camera.adquirir("cadastro")
            amostras: list[np.ndarray] = []
            base_yaw, base_vert = 0.0, 0.0
            lado = 0.0
            vertical = 0.0
            seq = 0
            fim = time.monotonic() + timeout
            for indice, fase in enumerate(plano):
                coletadas = 0
                ultima = 0.0
                valores_base: list[tuple[float, float]] = []
                progresso({"fase": "cadastro", "instrucao": fase.instrucao, "etapa": indice + 1,
                           "etapas": len(plano), "progresso": len(amostras) / total})
                while coletadas < fase.amostras:
                    if self.cancelar_evento.is_set() or time.monotonic() > fim:
                        progresso({"fase": "cancelado" if self.cancelar_evento.is_set() else "tempo_esgotado"})
                        return False
                    quadro, seq = camera.esperar_quadro(seq, 1.5)
                    if quadro is None:
                        continue
                    rostos = self.detectar(quadro)
                    if len(rostos) != 1:
                        self._registrar_deteccao(quadro, rostos[0] if rostos else None, "", 0)
                        continue
                    rosto = rostos[0]
                    self._registrar_deteccao(quadro, rosto, "cadastro", 0)
                    if rosto[-1] < 0.9 or rosto[2] < quadro.shape[1] * 0.16:
                        continue  # rosto pequeno/borrado: chegue mais perto
                    if time.monotonic() - ultima < 0.25:
                        continue
                    yaw, vert = self.pose(rosto)
                    dy, dv = yaw - base_yaw, vert - base_vert
                    aceito = False
                    if fase.condicao == "frente":
                        aceito = True
                        valores_base.append((yaw, vert))
                    elif fase.condicao == "lado1" and abs(dy) > 0.16:
                        lado, aceito = float(np.sign(dy)), True
                    elif fase.condicao == "lado2" and abs(dy) > 0.16 and np.sign(dy) == -lado:
                        aceito = True
                    elif fase.condicao == "vert1" and abs(dv) > 0.07:
                        vertical, aceito = float(np.sign(dv)), True
                    elif fase.condicao == "vert2" and abs(dv) > 0.07 and np.sign(dv) == -vertical:
                        aceito = True
                    if not aceito:
                        continue
                    vetor = self.assinatura(quadro, rosto)
                    if any(float(a @ vetor) > self.LIMIAR_DUPLICADA for a in amostras):
                        continue  # praticamente igual a uma amostra já coletada
                    amostras.append(vetor)
                    coletadas += 1
                    ultima = time.monotonic()
                    progresso({"fase": "cadastro", "instrucao": fase.instrucao, "etapa": indice + 1,
                               "etapas": len(plano), "progresso": len(amostras) / total})
                if fase.condicao == "frente" and valores_base:
                    base_yaw = float(np.median([v[0] for v in valores_base]))
                    base_vert = float(np.median([v[1] for v in valores_base]))
            matriz = np.stack(amostras).astype(np.float32)
            np.save(self.arquivo, matriz)
            self.arquivo_meta.write_text(json.dumps({"amostras": len(amostras), "data": time.strftime("%d/%m/%Y %H:%M")}),
                                         encoding="utf-8")
            with self._lock:
                self._assinaturas = matriz
            consistencia = float(np.mean(matriz @ matriz.T))
            log.info("Rosto cadastrado: %d amostras (consistência %.2f)", len(amostras), consistencia)
            progresso({"fase": "concluido", "progresso": 1.0})
            return True
        except Exception as erro:  # noqa: BLE001
            log.exception("Falha no cadastro facial")
            progresso({"fase": "erro", "mensagem": str(erro)})
            return False
        finally:
            camera.liberar("cadastro")
            self.ultima_deteccao = {}
            self._ocupado.release()