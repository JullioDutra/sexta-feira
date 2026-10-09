"""Gerenciador de hologramas: quais painéis estão abertos e com quais dados.

A posição/rotação de cada holograma é decidida e guardada no próprio HUD
(cada tela arruma do seu jeito); aqui fica só o conteúdo.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time

from . import sistema_info

log = logging.getLogger(__name__)

TIPOS = ["clima", "noticias", "sistema", "relogio", "globo", "lembretes", "rotinas", "camera", "atividades", "texto",
         "imagem", "protocolo"]
TITULOS = {
    "clima": "Clima", "noticias": "Notícias", "sistema": "Sistema", "relogio": "Relógio", "globo": "Globo",
    "lembretes": "Lembretes", "rotinas": "Protocolos", "camera": "Câmera", "atividades": "Registro de atividades",
    "texto": "Nota", "imagem": "Imagem", "protocolo": "Novo protocolo",
}
UNICOS = {"clima", "noticias", "sistema", "relogio", "globo", "lembretes", "rotinas", "camera", "atividades", "protocolo"}


class Hologramas:
    def __init__(self, app) -> None:
        self.app = app
        self._abertos: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._rodando = True
        threading.Thread(target=self._atualizar_vivos, name="hologramas", daemon=True).start()

    def lista(self) -> list[dict]:
        with self._lock:
            return list(self._abertos.values())

    def mostrar(self, tipo: str, dados: dict | None = None, titulo: str | None = None) -> str:
        if tipo not in TIPOS:
            raise ValueError(f"Tipo de holograma desconhecido: {tipo}")
        dados = dados if dados is not None else self._dados_iniciais(tipo)
        with self._lock:
            existente = next((h for h in self._abertos.values() if h["tipo"] == tipo), None) if tipo in UNICOS else None
            if existente:
                existente.update({"dados": dados, "titulo": titulo or existente["titulo"], "atualizado": time.time()})
                holograma = dict(existente)
                evento = "holograma.atualizar"
            else:
                holograma = {"id": f"h{next(self._ids)}", "tipo": tipo, "titulo": titulo or TITULOS[tipo],
                             "dados": dados, "criado": time.time(), "atualizado": time.time()}
                self._abertos[holograma["id"]] = holograma
                evento = "holograma.abrir"
        self.app.barramento.publicar(evento, holograma=holograma)
        return holograma["id"]

    def atualizar_tipo(self, tipo: str, dados: dict) -> None:
        with self._lock:
            alvos = [h for h in self._abertos.values() if h["tipo"] == tipo]
            for h in alvos:
                h["dados"], h["atualizado"] = dados, time.time()
            copias = [dict(h) for h in alvos]
        for h in copias:
            self.app.barramento.publicar("holograma.atualizar", holograma=h)

    def aberto(self, tipo: str) -> bool:
        with self._lock:
            return any(h["tipo"] == tipo for h in self._abertos.values())

    def fechar(self, id_: str | None = None, tipo: str | None = None) -> int:
        with self._lock:
            ids = [i for i, h in self._abertos.items() if (id_ and i == id_) or (tipo and h["tipo"] == tipo)]
            for i in ids:
                self._abertos.pop(i, None)
        for i in ids:
            self.app.barramento.publicar("holograma.fechar", id=i)
        return len(ids)

    def fechar_todos(self) -> int:
        with self._lock:
            ids = list(self._abertos)
            self._abertos.clear()
        for i in ids:
            self.app.barramento.publicar("holograma.fechar", id=i)
        return len(ids)

    # ------------------------------------------------------------------
    def _dados_iniciais(self, tipo: str) -> dict:
        app = self.app
        if tipo == "sistema":
            return sistema_info.coletar()
        if tipo == "lembretes":
            return {"itens": app.lembretes.listar()}
        if tipo == "rotinas":
            return {"itens": [r.para_dict() for r in app.rotinas.listar()]}
        if tipo == "atividades":
            return app.atividades.para_holograma()
        if tipo == "globo":
            prefs = app.prefs
            if prefs.get("cidade_lat") is not None:
                return {"lat": prefs.get("cidade_lat"), "lon": prefs.get("cidade_lon"), "rotulo": prefs.get("cidade_rotulo")}
            return {}
        return {}

    def _atualizar_vivos(self) -> None:
        import psutil

        psutil.cpu_percent(interval=None)  # primeira leitura é sempre 0
        while self._rodando:
            time.sleep(2)
            try:
                if self.aberto("sistema"):
                    self.atualizar_tipo("sistema", sistema_info.coletar())
            except Exception:  # noqa: BLE001
                log.exception("Erro atualizando holograma de sistema")
