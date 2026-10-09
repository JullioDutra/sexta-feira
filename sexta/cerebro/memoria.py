"""Memória de longo prazo: fatos que o usuário pede para a Sexta lembrar."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from ..util.texto import normalizar


class Memoria:
    LIMITE = 60

    def __init__(self, arquivo: Path) -> None:
        self.arquivo = arquivo
        self._lock = threading.Lock()
        self._fatos: list[dict] = []
        if arquivo.exists():
            try:
                self._fatos = json.loads(arquivo.read_text(encoding="utf-8")).get("fatos", [])
            except (OSError, json.JSONDecodeError):
                self._fatos = []

    def lembrar(self, texto: str) -> bool:
        texto = texto.strip().rstrip(".")
        if not texto:
            return False
        with self._lock:
            if any(normalizar(f["texto"]) == normalizar(texto) for f in self._fatos):
                return False
            self._fatos.append({"texto": texto, "criado": time.time()})
            self._fatos = self._fatos[-self.LIMITE:]
            self._salvar()
        return True

    def esquecer(self, trecho: str) -> list[str]:
        alvo = normalizar(trecho)
        with self._lock:
            removidos = [f["texto"] for f in self._fatos if alvo and alvo in normalizar(f["texto"])]
            self._fatos = [f for f in self._fatos if f["texto"] not in removidos]
            if removidos:
                self._salvar()
        return removidos

    def listar(self) -> list[str]:
        with self._lock:
            return [f["texto"] for f in self._fatos]

    def para_prompt(self) -> str:
        fatos = self.listar()
        return "\n".join(f"- {f}" for f in fatos) if fatos else "- (nenhum ainda)"

    def _salvar(self) -> None:
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps({"fatos": self._fatos}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.arquivo)
