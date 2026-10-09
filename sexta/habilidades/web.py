"""Pequenas ações na web: pesquisar e tocar o primeiro resultado do YouTube."""

from __future__ import annotations

import logging
import re
import webbrowser
from urllib.parse import quote_plus

import httpx

log = logging.getLogger(__name__)

BUSCAS = {
    "google": "https://www.google.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "maps": "https://www.google.com/maps/search/{}",
    "imagens": "https://www.google.com/search?tbm=isch&q={}",
}
_NAVEGADOR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/140.0 Safari/537.36", "Accept-Language": "pt-BR,pt;q=0.9"}


def pesquisar(termo: str, onde: str = "google") -> str:
    url = BUSCAS.get(onde, BUSCAS["google"]).format(quote_plus(termo))
    webbrowser.open(url)
    return url


def primeiro_video(busca: str) -> str | None:
    try:
        r = httpx.get("https://www.youtube.com/results", params={"search_query": busca}, headers=_NAVEGADOR,
                      timeout=8.0, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as erro:
        log.warning("Busca no YouTube falhou: %s", erro)
        return None
    m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})"', r.text) or re.search(r'"videoId":"([\w-]{11})"', r.text)
    return m.group(1) if m else None


def tocar_youtube(busca: str) -> tuple[bool, str]:
    video = primeiro_video(busca)
    if video:
        webbrowser.open(f"https://www.youtube.com/watch?v={video}")
        return True, f"Tocando {busca} no YouTube."
    pesquisar(busca, "youtube")
    return True, f"Abri a busca por {busca} no YouTube."
