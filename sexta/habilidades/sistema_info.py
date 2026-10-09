"""Leituras do sistema (CPU, memória, disco, bateria, rede) para o holograma de sistema."""

from __future__ import annotations

import time

_rede_anterior: tuple[float, int, int] | None = None


def coletar() -> dict:
    import psutil

    global _rede_anterior
    memoria = psutil.virtual_memory()
    try:
        disco = psutil.disk_usage("C:\\" if psutil.WINDOWS else "/")
        disco_info = {"usado": round(disco.used / 2**30), "total": round(disco.total / 2**30), "pct": disco.percent}
    except OSError:
        disco_info = None
    bateria = None
    try:
        b = psutil.sensors_battery()
        if b is not None:
            bateria = {"pct": round(b.percent), "carregando": bool(b.power_plugged)}
    except (AttributeError, NotImplementedError):
        pass
    rede = psutil.net_io_counters()
    agora = time.monotonic()
    descida = subida = 0.0
    if _rede_anterior:
        dt = max(0.1, agora - _rede_anterior[0])
        descida = (rede.bytes_recv - _rede_anterior[1]) / dt
        subida = (rede.bytes_sent - _rede_anterior[2]) / dt
    _rede_anterior = (agora, rede.bytes_recv, rede.bytes_sent)
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "nucleos": psutil.cpu_count(logical=True),
        "ram": {"usado": round(memoria.used / 2**30, 1), "total": round(memoria.total / 2**30, 1), "pct": memoria.percent},
        "disco": disco_info,
        "bateria": bateria,
        "rede": {"desce_kbps": round(descida / 1024), "sobe_kbps": round(subida / 1024)},
        "ligado_ha": _tempo_ligado(time.time() - psutil.boot_time()),
    }


def _tempo_ligado(segundos: float) -> str:
    horas = int(segundos // 3600)
    minutos = int(segundos % 3600 // 60)
    if horas >= 24:
        return f"{horas // 24}d {horas % 24}h"
    return f"{horas}h {minutos:02d}min"


def resumo(dados: dict) -> str:
    partes = [f"Processador em {round(dados['cpu'])}%", f"memória em {round(dados['ram']['pct'])}%"]
    if dados.get("disco"):
        partes.append(f"disco com {dados['disco']['pct']:.0f}% ocupado")
    texto = ", ".join(partes) + "."
    if dados.get("bateria"):
        b = dados["bateria"]
        texto += f" Bateria em {b['pct']}%" + (", carregando." if b["carregando"] else ".")
    return texto + f" Ligado há {dados['ligado_ha']}."
