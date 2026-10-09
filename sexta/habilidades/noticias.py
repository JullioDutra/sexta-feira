"""Manchetes do Google Notícias (RSS em português, sem chave de API)."""

from __future__ import annotations

import logging
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import httpx

log = logging.getLogger(__name__)

BASE = "https://news.google.com/rss"
PARAMS = "hl=pt-BR&gl=BR&ceid=BR:pt-419"
TOPICOS = {
    "brasil": "NATION", "mundo": "WORLD", "tecnologia": "TECHNOLOGY", "economia": "BUSINESS",
    "esportes": "SPORTS", "entretenimento": "ENTERTAINMENT", "ciencia": "SCIENCE", "saude": "HEALTH",
}
CATEGORIAS = ["geral", *TOPICOS]


class ErroNoticias(Exception):
    pass


def ha_quanto(publicado: datetime | None, agora: datetime | None = None) -> str:
    if publicado is None:
        return ""
    agora = agora or datetime.now(timezone.utc)
    minutos = int((agora - publicado).total_seconds() // 60)
    if minutos < 1:
        return "agora"
    if minutos < 60:
        return f"há {minutos} min"
    horas = minutos // 60
    if horas < 24:
        return f"há {horas} h"
    dias = horas // 24
    return "ontem" if dias == 1 else f"há {dias} dias"


def interpretar_rss(xml: str | bytes, limite: int = 8) -> list[dict]:
    raiz = ET.fromstring(xml)
    itens = []
    for item in raiz.iter("item"):
        titulo = (item.findtext("title") or "").strip()
        fonte_el = item.find("source")
        fonte = (fonte_el.text or "").strip() if fonte_el is not None else ""
        if fonte and titulo.endswith(f" - {fonte}"):
            titulo = titulo[: -len(fonte) - 3].strip()
        elif not fonte and " - " in titulo:
            titulo, fonte = (p.strip() for p in titulo.rsplit(" - ", 1))
        publicado = None
        data = item.findtext("pubDate")
        if data:
            try:
                publicado = parsedate_to_datetime(data)
            except (TypeError, ValueError):
                publicado = None
        if not titulo:
            continue
        itens.append({
            "titulo": titulo,
            "fonte": fonte,
            "link": (item.findtext("link") or "").strip(),
            "publicado": publicado.isoformat() if publicado else None,
            "quando": ha_quanto(publicado),
        })
        if len(itens) >= limite:
            break
    return itens


class ServicoNoticias:
    def __init__(self, http: httpx.Client | None = None) -> None:
        self.http = http or httpx.Client(timeout=10.0, follow_redirects=True,
                                         headers={"User-Agent": "Mozilla/5.0 Sexta-Feira/1.0"})
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def url(assunto: str | None = None, categoria: str | None = None) -> str:
        if assunto:
            return f"{BASE}/search?q={quote_plus(assunto + ' when:3d')}&{PARAMS}"
        if categoria and categoria in TOPICOS:
            return f"{BASE}/headlines/section/topic/{TOPICOS[categoria]}?{PARAMS}"
        return f"{BASE}?{PARAMS}"

    def buscar(self, assunto: str | None = None, categoria: str | None = None, quantidade: int = 5) -> list[dict]:
        endereco = self.url(assunto, categoria)
        with self._lock:
            em_cache = self._cache.get(endereco)
            if em_cache and time.time() - em_cache[0] < 300:
                return em_cache[1][:quantidade]
        try:
            r = self.http.get(endereco)
            r.raise_for_status()
            itens = interpretar_rss(r.content, limite=12)
        except (httpx.HTTPError, ET.ParseError) as erro:
            raise ErroNoticias("Não consegui buscar as notícias agora.") from erro
        with self._lock:
            self._cache[endereco] = (time.time(), itens)
        return itens[:quantidade]
