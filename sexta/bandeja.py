"""Ícone na bandeja do Windows (perto do relógio): abrir HUD, microfone, sair."""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


def _imagem():
    from PIL import Image, ImageDraw

    tamanho = 64
    img = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), outline=(255, 181, 71, 255), width=5)
    d.ellipse((20, 20, 44, 44), fill=(255, 181, 71, 255))
    return img


def iniciar_bandeja(app) -> None:
    try:
        import pystray
    except ImportError:
        log.info("pystray não instalado: sem ícone na bandeja")
        return

    def alternar_microfone(icone, _item):
        app.estado.definir_microfone(not app.estado.microfone_ligado)
        icone.update_menu()

    def sair(icone, _item):
        icone.stop()
        app.sair()

    menu = pystray.Menu(
        pystray.MenuItem("Abrir HUD", lambda *_: app.abrir_hud(), default=True),
        pystray.MenuItem("Microfone ligado", alternar_microfone, checked=lambda _i: app.estado.microfone_ligado),
        pystray.MenuItem("Sair", sair),
    )
    icone = pystray.Icon("sexta-feira", _imagem(), "Sexta-Feira", menu)
    threading.Thread(target=icone.run, name="bandeja", daemon=True).start()
