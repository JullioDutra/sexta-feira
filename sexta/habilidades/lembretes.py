"""Lembretes e alarmes (SQLite), com repetição diária, em dias úteis ou semanal."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from ..util.tempo import descrever_quando, formatar_hora
from ..util.texto import normalizar
from ..voz.audio import SOM_ALARME, SOM_LEMBRETE

log = logging.getLogger(__name__)

REPETICOES = ["nao", "diario", "dias_uteis", "semanal"]
DURACAO_ALARME_S = 90


def proxima_ocorrencia(quando: datetime, repetir: str, agora: datetime) -> datetime | None:
    if repetir == "nao":
        return None
    passo = timedelta(days=7 if repetir == "semanal" else 1)
    proxima = quando + passo
    while proxima <= agora or (repetir == "dias_uteis" and proxima.weekday() >= 5):
        proxima += timedelta(days=1) if repetir == "dias_uteis" else passo
    return proxima


class Lembretes:
    def __init__(self, app, arquivo: Path) -> None:
        self.app = app
        self._db = sqlite3.connect(str(arquivo), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._alarme = threading.Event()
        self._rodando = False
        with self._lock:
            self._db.execute(
                """CREATE TABLE IF NOT EXISTS lembretes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    texto TEXT NOT NULL,
                    quando REAL NOT NULL,
                    repetir TEXT NOT NULL DEFAULT 'nao',
                    alarme INTEGER NOT NULL DEFAULT 0,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    criado REAL NOT NULL,
                    disparado REAL)""")
            self._db.commit()

    # -- consulta / edição -----------------------------------------------
    @staticmethod
    def _dict(linha: sqlite3.Row) -> dict:
        quando = datetime.fromtimestamp(linha["quando"])
        return {"id": linha["id"], "texto": linha["texto"], "quando": quando.isoformat(timespec="minutes"),
                "descricao": descrever_quando(quando), "hora": formatar_hora(quando), "repetir": linha["repetir"],
                "alarme": bool(linha["alarme"])}

    def criar(self, texto: str, quando: datetime, repetir: str = "nao", alarme: bool = False) -> dict:
        if repetir not in REPETICOES:
            repetir = "nao"
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO lembretes (texto, quando, repetir, alarme, criado) VALUES (?, ?, ?, ?, ?)",
                (texto.strip(), quando.timestamp(), repetir, int(alarme), time.time()))
            self._db.commit()
            linha = self._db.execute("SELECT * FROM lembretes WHERE id = ?", (cur.lastrowid,)).fetchone()
        self._mudou()
        return self._dict(linha)

    def listar(self) -> list[dict]:
        with self._lock:
            linhas = self._db.execute("SELECT * FROM lembretes WHERE ativo = 1 ORDER BY quando").fetchall()
        return [self._dict(l) for l in linhas]

    def do_dia(self, dia: datetime | None = None) -> list[dict]:
        dia = (dia or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        inicio, fim = dia.timestamp(), (dia + timedelta(days=1)).timestamp()
        with self._lock:
            linhas = self._db.execute("SELECT * FROM lembretes WHERE ativo = 1 AND quando >= ? AND quando < ? ORDER BY quando",
                                      (inicio, fim)).fetchall()
        return [self._dict(l) for l in linhas]

    def cancelar(self, id_: int) -> bool:
        with self._lock:
            cur = self._db.execute("UPDATE lembretes SET ativo = 0 WHERE id = ? AND ativo = 1", (id_,))
            self._db.commit()
        if cur.rowcount:
            self._mudou()
        return bool(cur.rowcount)

    def cancelar_por_texto(self, trecho: str) -> list[str]:
        alvo = normalizar(trecho)
        removidos = [l for l in self.listar() if alvo and alvo in normalizar(l["texto"])]
        for l in removidos:
            self.cancelar(l["id"])
        return [l["texto"] for l in removidos]

    def cancelar_todos(self) -> int:
        with self._lock:
            cur = self._db.execute("UPDATE lembretes SET ativo = 0 WHERE ativo = 1")
            self._db.commit()
        self._mudou()
        return cur.rowcount

    def _mudou(self) -> None:
        self.app.barramento.publicar("lembretes", itens=self.listar())
        hologramas = getattr(self.app, "hologramas", None)
        if hologramas and hologramas.aberto("lembretes"):
            hologramas.atualizar_tipo("lembretes", {"itens": self.listar()})

    # -- disparo --------------------------------------------------------------
    def iniciar(self) -> None:
        self._rodando = True
        threading.Thread(target=self._laco, name="lembretes", daemon=True).start()

    def parar(self) -> None:
        self._rodando = False
        self.parar_alarme()

    def alarme_ativo(self) -> bool:
        return self._alarme.is_set()

    def parar_alarme(self) -> bool:
        if not self._alarme.is_set():
            return False
        self._alarme.clear()
        self.app.fala.parar()
        self.app.barramento.publicar("alarme.fim")
        return True

    def _laco(self) -> None:
        primeira = True
        while self._rodando:
            try:
                agora = datetime.now()
                with self._lock:
                    vencidos = self._db.execute("SELECT * FROM lembretes WHERE ativo = 1 AND quando <= ? ORDER BY quando",
                                                (agora.timestamp(),)).fetchall()
                for linha in vencidos:
                    atrasado = agora.timestamp() - linha["quando"] > 120
                    self._disparar(linha, agora, perdido=atrasado and primeira)
            except Exception:  # noqa: BLE001
                log.exception("Erro verificando lembretes")
            primeira = False
            time.sleep(1.0)

    def _disparar(self, linha: sqlite3.Row, agora: datetime, perdido: bool) -> None:
        proxima = proxima_ocorrencia(datetime.fromtimestamp(linha["quando"]), linha["repetir"], agora)
        with self._lock:
            if proxima:
                self._db.execute("UPDATE lembretes SET quando = ?, disparado = ? WHERE id = ?",
                                 (proxima.timestamp(), time.time(), linha["id"]))
            else:
                self._db.execute("UPDATE lembretes SET ativo = 0, disparado = ? WHERE id = ?", (time.time(), linha["id"]))
            self._db.commit()
        texto = linha["texto"]
        alarme = bool(linha["alarme"]) and not perdido
        log.info("Lembrete disparado: %s", texto)
        self.app.barramento.publicar("lembrete", id=linha["id"], texto=texto, alarme=alarme, perdido=perdido)
        tratamento = self.app.prefs.get("tratamento") or "chefe"
        fala = self.app.fala
        if perdido:
            fala.falar(f"{tratamento}, enquanto eu estava desligada você tinha um lembrete: {texto}.")
        elif alarme:
            threading.Thread(target=self._tocar_alarme, args=(texto,), daemon=True).start()
        else:
            fala.tocar_som(SOM_LEMBRETE)
            fala.falar(f"{tratamento.capitalize()}, lembrete: {texto}.")
        self._mudou()

    def _tocar_alarme(self, texto: str) -> None:
        self._alarme.set()
        fala = self.app.fala
        inicio = time.monotonic()
        while self._alarme.is_set() and time.monotonic() - inicio < DURACAO_ALARME_S:
            fala.tocar_som(SOM_ALARME)
            fala.tocar_som(SOM_ALARME)
            fala.falar(f"Alarme: {texto}.")
            fala.aguardar(30)
            for _ in range(40):  # ~4 s de pausa, interrompível
                if not self._alarme.is_set():
                    break
                time.sleep(0.1)
        if self._alarme.is_set():
            self._alarme.clear()
            self.app.barramento.publicar("alarme.fim")
