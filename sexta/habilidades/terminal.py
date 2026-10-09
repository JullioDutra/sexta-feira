"""Terminal controlado: a Sexta-Feira roda comandos de uma lista permitida.

A lista fica em ``config/terminal.yaml``. Um item terminado em `` *`` aceita
qualquer argumento (ex.: ``ping *``); sem o asterisco, só o comando exato.
Qualquer coisa fora da lista — ou com encadeamento (``&``, ``|``, ``>``...) —
precisa de confirmação com rosto antes de rodar.
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from pathlib import Path

import yaml

from . import windows

log = logging.getLogger(__name__)

PERIGOSOS = re.compile(r"[&|<>^;`\n\r]|\$\(|%[^%\s]+%")
PADRAO = ["ipconfig", "ipconfig /all", "ping *", "tracert *", "nslookup *", "hostname", "whoami", "systeminfo",
          "tasklist", "winget list", "winget upgrade", "winget search *", "git status", "git log --oneline -10",
          "python --version", "node --version", "npm --version", "nvidia-smi", "wsl --list --verbose", "dir *"]
LIMITE_SAIDA = 3000


class Terminal:
    def __init__(self, arquivo: Path) -> None:
        self.arquivo = arquivo
        self.permitidos: list[str] = list(PADRAO)
        self.pasta = str(Path.home())
        self.recarregar()

    def recarregar(self) -> None:
        if not self.arquivo.exists():
            return
        try:
            dados = yaml.safe_load(self.arquivo.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as erro:
            log.error("Erro lendo %s: %s", self.arquivo.name, erro)
            return
        self.permitidos = [str(c).strip() for c in dados.get("permitidos") or [] if str(c).strip()]
        if dados.get("pasta"):
            self.pasta = str(Path(str(dados["pasta"])).expanduser())

    def permitido(self, comando: str) -> bool:
        comando = " ".join((comando or "").split())
        if not comando or PERIGOSOS.search(comando):
            return False
        try:
            partes = [p.lower() for p in shlex.split(comando, posix=False)]
        except ValueError:
            return False
        for item in self.permitidos:
            modelo = item.lower().split()
            if modelo and modelo[-1] == "*":
                base = modelo[:-1]
                if partes[:len(base)] == base:
                    return True
            elif partes == modelo:
                return True
        return False

    def executar(self, comando: str, timeout: float = 30) -> tuple[int, str]:
        if windows.WINDOWS:
            args = ["cmd", "/d", "/s", "/c", f"chcp 65001 >nul & {comando}"]
            r = subprocess.run(args, capture_output=True, timeout=timeout, cwd=self.pasta,
                               creationflags=windows.SEM_JANELA)
        else:
            r = subprocess.run(comando, shell=True, capture_output=True, timeout=timeout, cwd=self.pasta)  # noqa: S602
        saida = (r.stdout + (b"\n" + r.stderr if r.stderr else b"")).decode("utf-8", "replace").strip()
        if len(saida) > LIMITE_SAIDA:
            saida = saida[:LIMITE_SAIDA // 2] + "\n[...]\n" + saida[-LIMITE_SAIDA // 2:]
        return r.returncode, saida
