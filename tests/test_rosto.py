"""Reconhecimento facial com imagens de teste (pulado se os modelos não estiverem disponíveis)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from sexta.visao.rosto import MODELO_DETECTOR, MODELO_RECONHECEDOR, Fase

PASTA_MODELOS = Path(os.environ.get("SEXTA_MODELOS_TESTE", ""))
PASTA_IMAGENS = Path(os.environ.get("SEXTA_IMAGENS_TESTE", ""))
pytestmark = pytest.mark.skipif(
    not (PASTA_MODELOS / MODELO_DETECTOR).exists() or not (PASTA_IMAGENS / "lena.jpg").exists(),
    reason="defina SEXTA_MODELOS_TESTE e SEXTA_IMAGENS_TESTE para rodar",
)


def fonte(imagem: np.ndarray):
    import cv2

    rng = np.random.default_rng(1)

    def proximo():
        dx, dy = rng.integers(-12, 12, 2)
        escala = rng.uniform(0.92, 1.08)
        h, w = imagem.shape[:2]
        m = cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-6, 6), escala)
        m[:, 2] += (dx, dy)
        quadro = cv2.warpAffine(imagem, m, (w, h), borderMode=cv2.BORDER_REFLECT)
        return cv2.convertScaleAbs(quadro, alpha=rng.uniform(0.85, 1.15), beta=rng.uniform(-15, 15))

    return proximo


@pytest.fixture
def app_com_rosto(app):
    import cv2

    for nome in (MODELO_DETECTOR, MODELO_RECONHECEDOR):
        shutil.copy(PASTA_MODELOS / nome, app.cfg.modelos / nome)
    app.rosto.LIMIAR_DUPLICADA = 0.999
    app.camera.fonte_teste = fonte(cv2.imread(str(PASTA_IMAGENS / "lena.jpg")))
    return app


def test_cadastro_e_verificacao(app_com_rosto):
    import cv2

    app = app_com_rosto
    eventos = []
    ok = app.rosto.cadastrar(eventos.append, timeout=30, plano=[Fase("Olhe para a câmera", 8, "frente")])
    assert ok, eventos[-1]
    assert eventos[-1]["fase"] == "concluido" and app.rosto.cadastrado()

    resultado = app.rosto.verificar(timeout=5)
    assert resultado.ok and resultado.similaridade > 0.6

    # outra pessoa não passa
    app.camera.fonte_teste = fonte(cv2.imread(str(PASTA_IMAGENS / "messi5.jpg")))
    resultado = app.rosto.verificar(timeout=2)
    assert not resultado.ok and resultado.motivo == "desconhecido"

    # bloqueio da própria Sexta
    app.camera.fonte_teste = fonte(cv2.imread(str(PASTA_IMAGENS / "lena.jpg")))
    app.prefs.atualizar({"exigir_piscada": False})
    app.sessao.bloquear("teste")
    assert app.sessao.bloqueada and app.sessao.precisa_verificar()
    assert app.desbloquear_por_rosto()
    assert not app.sessao.bloqueada and not app.sessao.precisa_verificar()


def test_sem_cadastro(app_com_rosto):
    assert app_com_rosto.rosto.verificar(timeout=1).motivo == "sem_cadastro"
    assert not app_com_rosto.sessao.protecao_ativa()
