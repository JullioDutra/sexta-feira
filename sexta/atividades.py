"""Registro de atividades: tudo que a Sexta-Feira faz no PC fica anotado.

As entradas vão para ``dados/atividades.jsonl`` (uma por linha), aparecem no
holograma "Atividades" e podem ser consultadas por voz ("o que você fez hoje?").
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

NIVEIS = {1: "livre", 2: "confirmada", 3: "rosto"}
# Ferramentas só de consulta não poluem o registro
SILENCIOSAS = {"holograma", "obter_clima", "obter_noticias", "memoria"}


class Atividades:
    MEMORIA = 200
    ARQUIVO_MAX = 2 * 2**20  # ao passar de 2 MB, guarda só a metade mais nova

    def __init__(self, app, arquivo: Path) -> None:
        self.app = app
        self.arquivo = arquivo
        self._itens: deque[dict[str, Any]] = deque(maxlen=self.MEMORIA)
        self._lock = threading.Lock()
        self._carregar()

    def _carregar(self) -> None:
        if not self.arquivo.exists():
            return
        try:
            linhas = self.arquivo.read_text(encoding="utf-8").splitlines()[-self.MEMORIA:]
        except OSError:
            return
        for linha in linhas:
            try:
                self._itens.append(json.loads(linha))
            except json.JSONDecodeError:
                continue

    def anotar(self, registro: dict[str, Any]) -> None:
        if registro.get("ferramenta") in SILENCIOSAS and registro.get("situacao") == "ok":
            return
        item = {
            "ts": time.time(),
            "ferramenta": registro.get("ferramenta", ""),
            "argumentos": _resumir_args(registro.get("argumentos") or {}),
            "nivel": NIVEIS.get(int(registro.get("nivel") or 1), "livre"),
            "situacao": registro.get("situacao", "ok"),
            "resumo": str(registro.get("resumo") or "")[:240],
            "canal": registro.get("canal", ""),
        }
        with self._lock:
            self._itens.append(item)
            try:
                with self.arquivo.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                if self.arquivo.stat().st_size > self.ARQUIVO_MAX:
                    linhas = self.arquivo.read_text(encoding="utf-8").splitlines()
                    self.arquivo.write_text("\n".join(linhas[len(linhas) // 2:]) + "\n", encoding="utf-8")
            except OSError as erro:
                log.warning("Não consegui gravar o registro de atividades: %s", erro)
        self.app.barramento.publicar("atividade", atividade=item)
        hologramas = getattr(self.app, "hologramas", None)
        if hologramas is not None and hologramas.aberto("atividades"):
            hologramas.atualizar_tipo("atividades", self.para_holograma())

    def listar(self, limite: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._itens)[-limite:][::-1]

    def para_holograma(self) -> dict[str, Any]:
        return {"itens": self.listar(40)}

    def resumo_de_hoje(self) -> str:
        inicio = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        feitos = [i for i in self.listar(self.MEMORIA) if i["ts"] >= inicio and i["situacao"] == "ok"]
        if not feitos:
            return "Hoje ainda não fiz nada no computador."
        ultimos = "; ".join(i["resumo"].rstrip(".") for i in feitos[:5] if i["resumo"])
        return f"Hoje fiz {len(feitos)} ações. As últimas: {ultimos}."


def _resumir_args(args: dict[str, Any]) -> dict[str, Any]:
    """Guarda os argumentos sem textos enormes (ex.: conteúdo colado)."""
    saida = {}
    for chave, valor in args.items():
        if isinstance(valor, str) and len(valor) > 120:
            valor = valor[:117] + "..."
        elif isinstance(valor, (list, dict)):
            texto = json.dumps(valor, ensure_ascii=False)
            valor = texto if len(texto) <= 120 else texto[:117] + "..."
        saida[chave] = valor
    return saida
