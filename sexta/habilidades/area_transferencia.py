"""Área de transferência: ler o que foi copiado, escrever um texto novo e colar.

No Windows usa a API do sistema (ctypes); no Linux/macOS tenta wl-paste, xclip ou
pbpaste — só para testes e desenvolvimento.
"""

from __future__ import annotations

import shutil
import subprocess
import time

from . import windows

LIMITE = 5_000  # caracteres entregues ao modelo de IA (cabe no contexto junto com as ferramentas)


class ErroAreaTransferencia(Exception):
    pass


def ler() -> str:
    if windows.WINDOWS:
        return _ler_windows()
    for comando in (["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"], ["pbpaste"]):
        if shutil.which(comando[0]):
            r = subprocess.run(comando, capture_output=True, timeout=5)
            return r.stdout.decode("utf-8", "replace")
    raise ErroAreaTransferencia("Não sei ler a área de transferência neste sistema.")


def escrever(texto: str) -> None:
    if windows.WINDOWS:
        _escrever_windows(texto)
        return
    for comando in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["pbcopy"]):
        if shutil.which(comando[0]):
            subprocess.run(comando, input=texto.encode("utf-8"), timeout=5)
            return
    raise ErroAreaTransferencia("Não sei escrever na área de transferência neste sistema.")


def colar() -> None:
    """Cola (Ctrl+V) na janela que estiver em foco."""
    time.sleep(0.15)
    windows.apertar_combinacao("ctrl", "v")


# -- Windows --------------------------------------------------------------------

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _api():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    return ctypes, user32, kernel32


def _abrir(user32) -> None:
    for _ in range(10):  # outro programa pode estar com a área de transferência aberta
        if user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise ErroAreaTransferencia("A área de transferência está ocupada por outro programa.")


def _ler_windows() -> str:
    ctypes, user32, kernel32 = _api()
    _abrir(user32)
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ponteiro = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(ponteiro)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _escrever_windows(texto: str) -> None:
    ctypes, user32, kernel32 = _api()
    dados = texto.encode("utf-16-le") + b"\x00\x00"
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dados))
    if not handle:
        raise ErroAreaTransferencia("Sem memória para a área de transferência.")
    ponteiro = kernel32.GlobalLock(handle)
    ctypes.memmove(ponteiro, dados, len(dados))
    kernel32.GlobalUnlock(handle)
    _abrir(user32)
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise ErroAreaTransferencia("O Windows recusou o texto na área de transferência.")
    finally:
        user32.CloseClipboard()
