"""Visão: "Sexta, analisa a tela" e "o que é isso?" (câmera).

Captura a tela (o monitor onde você está trabalhando) ou um quadro da webcam, reduz
a imagem e manda para um modelo com visão no Ollama.
"""

from __future__ import annotations

import base64
import io
import logging
import time

from . import windows

log = logging.getLogger(__name__)

LADO_MAXIMO = 1568  # px: bom equilíbrio entre detalhe e velocidade nos modelos de visão


class ErroVisao(Exception):
    pass


def capturar_tela(tudo: bool = False):
    """Imagem PIL do monitor da janela em foco (ignora o próprio HUD)."""
    from PIL import ImageGrab

    if tudo or not windows.WINDOWS:
        return ImageGrab.grab(all_screens=True)
    try:
        from . import janelas
        from ..util.texto import normalizar

        lista = janelas.monitores()
        alvo = next((j for j in janelas.listar()
                     if not j.minimizada and not normalizar(j.titulo).startswith("sexta feira")), None)
        if alvo is not None and len(lista) > 1:
            esquerda, topo, direita, base = lista[janelas.monitor_da_janela(alvo, lista)]["tela"]
            return ImageGrab.grab(bbox=(esquerda, topo, direita, base), all_screens=True)
    except Exception as erro:  # noqa: BLE001 - na dúvida, captura tudo
        log.debug("Captura do monitor ativo falhou: %s", erro)
    return ImageGrab.grab(all_screens=True)


def capturar_camera(app, timeout: float = 4.0):
    """Quadro da webcam como imagem PIL (espera a câmera ajustar a exposição)."""
    from PIL import Image

    camera = app.camera
    camera.adquirir("scanner")
    try:
        seq, quadro, inicio = 0, None, time.monotonic()
        while time.monotonic() - inicio < timeout:
            novo, seq = camera.esperar_quadro(seq, timeout=1.0)
            if novo is not None:
                quadro = novo
                if time.monotonic() - inicio > 0.8:  # os primeiros quadros saem escuros
                    break
        if quadro is None:
            raise ErroVisao(camera.erro or "A câmera não mandou imagem.")
        return Image.fromarray(quadro[:, :, ::-1].copy())  # BGR -> RGB
    finally:
        camera.liberar("scanner")


def para_base64(imagem, lado_maximo: int = LADO_MAXIMO) -> str:
    imagem = imagem.convert("RGB")
    escala = lado_maximo / max(imagem.size)
    if escala < 1:
        imagem = imagem.resize((round(imagem.width * escala), round(imagem.height * escala)))
    buffer = io.BytesIO()
    imagem.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def instrucao(fonte: str, canal: str) -> str:
    estilo = ("Responda em no máximo 3 frases curtas, para ser falado em voz alta, sem markdown."
              if canal == "voz" else "Responda de forma objetiva, em até 6 frases.")
    if fonte == "camera":
        contexto = ("A imagem é da webcam do usuário: ele está mostrando um objeto ou documento. "
                    "Se for um texto, leia o essencial.")
    else:
        contexto = ("A imagem é a tela do computador do usuário. Se houver uma mensagem de erro, explique a causa "
                    "provável e como resolver. Se for uma planilha, site ou documento, responda ao que ele perguntou.")
    return f"Você é a Sexta-Feira, assistente do usuário. Fale em português do Brasil. {contexto} {estilo}"
