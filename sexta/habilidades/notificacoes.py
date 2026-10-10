"""Notificações no celular.

1. Sempre: o aviso vai para os celulares pareados com o HUD aberto (vibra e mostra
   a notificação do navegador, se você permitiu).
2. Opcional: push de verdade, mesmo com o celular bloqueado, pelo app gratuito ntfy
   (https://ntfy.sh). Defina ``NTFY_TOPICO`` no .env com um nome difícil de adivinhar
   e assine o mesmo tópico no app. Dá para usar um servidor ntfy próprio em ``NTFY_SERVIDOR``.
"""

from __future__ import annotations

import logging
import threading

import httpx

log = logging.getLogger(__name__)


def notificar(app, texto: str, titulo: str = "Sexta-Feira", prioridade: str = "default") -> None:
    texto = (texto or "").strip()
    if not texto:
        return
    app.barramento.publicar("notificacao", para="celular", titulo=titulo, texto=texto)
    app.barramento.publicar("aviso", para="pc", nivel="info", texto=f"Enviado ao celular: {texto}")
    topico = getattr(app.cfg, "ntfy_topico", "")
    if topico:
        threading.Thread(target=_ntfy, args=(app.cfg.ntfy_servidor, topico, titulo, texto, prioridade),
                         name="ntfy", daemon=True).start()


def _ntfy(servidor: str, topico: str, titulo: str, texto: str, prioridade: str) -> None:
    try:
        r = httpx.post(f"{servidor.rstrip('/')}/{topico}", content=texto.encode("utf-8"), timeout=10,
                       headers={"Title": titulo.encode("utf-8").decode("latin-1", "replace"),
                                "Priority": prioridade, "Tags": "robot"})
        r.raise_for_status()
    except httpx.HTTPError as erro:
        log.warning("Não consegui mandar a notificação pelo ntfy: %s", erro)
