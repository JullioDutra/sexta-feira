"""Descobre os endereços IP locais do computador (para o celular acessar)."""

from __future__ import annotations

import socket


def ip_principal() -> str | None:
    """IP da interface usada para sair para a internet (não envia pacotes)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            return None if ip.startswith("127.") else ip
    except OSError:
        return None


def ips_locais() -> list[str]:
    ips: list[str] = []
    principal = ip_principal()
    if principal:
        ips.append(principal)
    try:
        import psutil

        for enderecos in psutil.net_if_addrs().values():
            for end in enderecos:
                if end.family == socket.AF_INET:
                    ip = end.address
                    if not ip.startswith(("127.", "169.254.")) and ip not in ips:
                        ips.append(ip)
    except Exception:  # noqa: BLE001 - psutil é opcional aqui
        pass
    return ips


def nome_do_computador() -> str:
    return socket.gethostname()
