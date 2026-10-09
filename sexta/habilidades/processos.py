"""Processos: o que está pesando (CPU, RAM, GPU por app), programas travados e encerrar à força."""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict

from ..util.texto import normalizar
from . import windows
from .apps import NUNCA_FECHAR, PROCESSOS

log = logging.getLogger(__name__)

IGNORAR = {"system idle process", "idle", "system", "registry", "memory compression", "secure system"}


def top(ordem: str = "cpu", limite: int = 6, amostra: float = 0.6) -> list[dict]:
    """Apps agrupados por nome (Chrome com 30 processos vira uma linha só)."""
    import psutil

    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except (psutil.Error, OSError):
            continue
    time.sleep(amostra)
    nucleos = psutil.cpu_count(logical=True) or 1
    grupos: dict[str, dict] = defaultdict(lambda: {"cpu": 0.0, "ram_mb": 0.0, "processos": 0, "pids": []})
    for p in procs:
        try:
            nome = (p.info.get("name") or "").removesuffix(".exe")
            if not nome or nome.lower() in IGNORAR:
                continue
            g = grupos[nome]
            g["cpu"] += p.cpu_percent(None) / nucleos
            mem = p.info.get("memory_info")
            g["ram_mb"] += (mem.rss if mem else 0) / 2**20
            g["processos"] += 1
            g["pids"].append(p.pid)
        except (psutil.Error, OSError):
            continue
    gpu = uso_gpu() if ordem == "gpu" else {}
    linhas = []
    for nome, g in grupos.items():
        uso = sum(gpu.get(pid, 0.0) for pid in g["pids"]) if gpu else None
        linhas.append({"nome": nome, "cpu": round(g["cpu"], 1), "ram_mb": round(g["ram_mb"]),
                       "gpu": round(uso, 1) if uso is not None else None, "processos": g["processos"]})
    chave = {"cpu": "cpu", "ram": "ram_mb", "memoria": "ram_mb", "gpu": "gpu"}.get(ordem, "cpu")
    linhas.sort(key=lambda l: l.get(chave) or 0, reverse=True)
    return linhas[:limite]


def uso_gpu() -> dict[int, float]:
    """% de uso da GPU por PID (contadores de desempenho do Windows)."""
    if not windows.WINDOWS:
        return {}
    try:
        saida = windows.powershell(
            "(Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage' -ErrorAction SilentlyContinue)"
            ".CounterSamples | Where-Object CookedValue -gt 0 | "
            "ForEach-Object { $_.InstanceName + '=' + [math]::Round($_.CookedValue, 1) }", timeout=15)
    except (OSError, windows.NaoSuportado) as erro:
        log.warning("Não consegui ler a GPU por processo: %s", erro)
        return {}
    uso: dict[int, float] = defaultdict(float)
    for linha in saida.splitlines():
        m = re.search(r"pid_(\d+).*=([\d.,]+)", linha)
        if m:
            uso[int(m.group(1))] += float(m.group(2).replace(",", "."))
    return dict(uso)


def travados() -> list[dict]:
    """Programas com janela que o Windows considera "Não respondendo"."""
    if not windows.WINDOWS:
        return []
    from . import janelas

    import ctypes

    user32 = ctypes.windll.user32
    vistos: dict[str, dict] = {}
    for j in janelas.listar():
        if user32.IsHungAppWindow(j.hwnd) and j.exe not in vistos:
            vistos[j.exe] = {"nome": j.exe, "titulo": j.titulo}
    return list(vistos.values())


def encerrar(nome: str) -> tuple[int, list[str]]:
    """Encerra à força todos os processos com esse nome. Devolve (quantos, nomes)."""
    import psutil

    alvo = normalizar(nome)
    exes = {e.lower() for e in PROCESSOS.get(alvo, [])}
    if not exes:
        alvo_exe = alvo.replace(" ", "")
        exes = {p.info["name"].lower() for p in psutil.process_iter(["name"])
                if p.info.get("name") and normalizar(p.info["name"].rsplit(".", 1)[0]).replace(" ", "") == alvo_exe}
    exes -= NUNCA_FECHAR
    if not exes:
        return 0, []
    total = 0
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info.get("name") or "").lower() in exes:
                p.kill()
                total += 1
        except (psutil.Error, OSError):
            continue
    return total, sorted(exes)


def fechar_travados() -> list[str]:
    fechados = []
    for item in travados():
        quantos, _ = encerrar(item["nome"])
        if quantos:
            fechados.append(item["nome"])
    return fechados


def descrever(linhas: list[dict], ordem: str) -> str:
    if not linhas:
        return "Não consegui ler os processos."
    if ordem == "gpu":
        com_gpu = [l for l in linhas if l.get("gpu")]
        if not com_gpu:
            return "Nenhum programa está usando a placa de vídeo de forma relevante agora."
        return "Na GPU: " + "; ".join(f"{l['nome']} {l['gpu']:.0f}%" for l in com_gpu[:4]) + "."
    if ordem in ("ram", "memoria"):
        return "Mais memória: " + "; ".join(f"{l['nome']} {_mb(l['ram_mb'])}" for l in linhas[:4]) + "."
    return "Mais processador: " + "; ".join(f"{l['nome']} {l['cpu']:.0f}% e {_mb(l['ram_mb'])}" for l in linhas[:4]) + "."


def _mb(valor: float) -> str:
    return f"{valor / 1024:.1f} GB".replace(".", ",") if valor >= 1024 else f"{valor:.0f} MB"
