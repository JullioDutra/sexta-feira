"""Ações no Windows: mídia, volume, print, bloqueio de tela, energia, pastas.

Tudo usa APIs oficiais do Windows (via ctypes/pycaw). Em outros sistemas as
funções devolvem um aviso em vez de quebrar — útil para testar o resto do projeto.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

WINDOWS = sys.platform == "win32"

VK = {
    "tocar_pausar": 0xB3, "proxima": 0xB0, "anterior": 0xB1, "parar": 0xB2,
    "mudo": 0xAD, "volume_menos": 0xAE, "volume_mais": 0xAF,
}
KEYEVENTF_KEYUP = 0x0002
SEM_JANELA = 0x08000000 if WINDOWS else 0  # CREATE_NO_WINDOW


class NaoSuportado(Exception):
    pass


def _exigir_windows() -> None:
    if not WINDOWS:
        raise NaoSuportado("Essa ação só funciona no Windows.")


def apertar_tecla(nome: str, vezes: int = 1) -> None:
    _exigir_windows()
    user32 = ctypes.windll.user32
    codigo = VK[nome]
    for _ in range(vezes):
        user32.keybd_event(codigo, 0, 0, 0)
        user32.keybd_event(codigo, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.01)


# -- volume -----------------------------------------------------------------

def _volume_endpoint():
    _exigir_windows()
    import comtypes

    try:
        comtypes.CoInitialize()
    except OSError:
        pass  # já inicializado nesta thread
    from pycaw.pycaw import AudioUtilities

    return AudioUtilities.GetSpeakers().EndpointVolume


def volume_atual() -> int | None:
    try:
        return round(_volume_endpoint().GetMasterVolumeLevelScalar() * 100)
    except NaoSuportado:
        raise
    except Exception as erro:  # noqa: BLE001
        log.warning("Não consegui ler o volume: %s", erro)
        return None


def definir_volume(percentual: int) -> int:
    percentual = max(0, min(100, int(percentual)))
    try:
        endpoint = _volume_endpoint()
        endpoint.SetMute(0, None)
        endpoint.SetMasterVolumeLevelScalar(percentual / 100, None)
        return percentual
    except NaoSuportado:
        raise
    except Exception as erro:  # noqa: BLE001 - sem pycaw: usa as teclas de volume (2% por toque)
        log.warning("pycaw falhou (%s); usando teclas de volume", erro)
        apertar_tecla("volume_menos", 50)
        apertar_tecla("volume_mais", percentual // 2)
        return percentual


def mudar_volume(delta: int) -> int:
    atual = volume_atual()
    if atual is None:
        apertar_tecla("volume_mais" if delta > 0 else "volume_menos", max(1, abs(delta) // 2))
        return -1
    return definir_volume(atual + delta)


def silenciar(mudo: bool = True) -> None:
    try:
        _volume_endpoint().SetMute(1 if mudo else 0, None)
    except NaoSuportado:
        raise
    except Exception:  # noqa: BLE001
        apertar_tecla("mudo")


# -- tela, sessão e energia ---------------------------------------------------

def print_da_tela(pasta: Path) -> Path:
    from PIL import ImageGrab

    pasta.mkdir(parents=True, exist_ok=True)
    imagem = ImageGrab.grab(all_screens=True)
    arquivo = pasta / f"print_{datetime.now():%Y-%m-%d_%H-%M-%S}_{uuid.uuid4().hex[:4]}.png"
    imagem.save(arquivo)
    return arquivo


def bloquear_windows() -> None:
    _exigir_windows()
    if not ctypes.windll.user32.LockWorkStation():
        raise OSError("O Windows recusou o bloqueio da tela.")


def sessao_bloqueada() -> bool | None:
    """True se a tela de bloqueio do Windows está ativa (``None`` fora do Windows)."""
    if not WINDOWS:
        return None
    user32 = ctypes.windll.user32
    desktop = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
    if not desktop:
        return True
    user32.CloseDesktop(desktop)
    return False


def energia(acao: str, segundos: int = 30) -> str:
    _exigir_windows()
    comandos = {
        "desligar": ["shutdown", "/s", "/t", str(segundos), "/c", "Sexta-Feira: desligando o computador."],
        "reiniciar": ["shutdown", "/r", "/t", str(segundos), "/c", "Sexta-Feira: reiniciando o computador."],
        "cancelar": ["shutdown", "/a"],
        "suspender": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
    }
    resultado = subprocess.run(comandos[acao], capture_output=True, text=True, creationflags=SEM_JANELA)
    if resultado.returncode not in (0, 1116):  # 1116 = não havia desligamento para cancelar
        raise OSError((resultado.stderr or resultado.stdout or "").strip() or f"código {resultado.returncode}")
    return acao


# -- pastas conhecidas ----------------------------------------------------------

_PASTAS_GUID = {
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "documentos": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "imagens": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "musicas": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
    "area de trabalho": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
}
_PASTAS_PADRAO = {"downloads": "Downloads", "documentos": "Documents", "imagens": "Pictures",
                  "musicas": "Music", "videos": "Videos", "area de trabalho": "Desktop"}


def pasta_conhecida(nome: str) -> Path:
    """Caminho real (respeita OneDrive/pasta movida) de Downloads, Documentos, etc."""
    if WINDOWS:
        try:
            class GUID(ctypes.Structure):
                _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                            ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

            guid = GUID()
            ctypes.oledll.ole32.CLSIDFromString(_PASTAS_GUID[nome], ctypes.byref(guid))
            caminho = ctypes.c_wchar_p()
            ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(caminho))
            valor = caminho.value
            ctypes.windll.ole32.CoTaskMemFree(caminho)
            if valor:
                return Path(valor)
        except Exception:  # noqa: BLE001
            pass
    return Path.home() / _PASTAS_PADRAO[nome]


def abrir_no_sistema(alvo: str) -> None:
    """Abre arquivo, pasta, programa ou URI (ms-settings:, spotify: ...) com o programa padrão."""
    if WINDOWS:
        os.startfile(alvo)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", alvo])
    else:
        subprocess.Popen(["xdg-open", alvo], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def abrir_app_da_loja(app_id: str) -> None:
    """Abre qualquer app do Menu Iniciar (inclusive da Microsoft Store) pelo AppID."""
    _exigir_windows()
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"], creationflags=SEM_JANELA)


def apps_do_menu_iniciar() -> list[dict]:
    """Lista [{"nome", "id"}] via PowerShell Get-StartApps."""
    if not WINDOWS:
        return []
    import json

    comando = "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
    resultado = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + comando],
        capture_output=True, timeout=20, creationflags=SEM_JANELA,
    )
    if resultado.returncode != 0 or not resultado.stdout:
        log.warning("Get-StartApps falhou: %s", resultado.stderr.decode("utf-8", "replace")[:200])
        return []
    dados = json.loads(resultado.stdout.decode("utf-8-sig", "replace"))
    if isinstance(dados, dict):
        dados = [dados]
    return [{"nome": d.get("Name", ""), "id": d.get("AppID", "")} for d in dados if d.get("AppID")]


def fechar_processos(executaveis: list[str]) -> int:
    """Pede para fechar (como clicar no X): o programa pode perguntar se quer salvar."""
    fechados = 0
    for exe in executaveis:
        if WINDOWS:
            r = subprocess.run(["taskkill", "/IM", exe], capture_output=True, creationflags=SEM_JANELA)
            if r.returncode == 0:
                fechados += 1
        else:
            r = subprocess.run(["pkill", "-f", exe], capture_output=True)
            fechados += int(r.returncode == 0)
    return fechados
