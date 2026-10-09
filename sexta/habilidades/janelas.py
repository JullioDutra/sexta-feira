"""Janelas do Windows: focar, minimizar, encaixar, mandar para outro monitor e layouts salvos.

Usa só a API do Windows (user32/dwmapi via ctypes). Layouts ficam em
``config/layouts.yaml`` (escritos à mão) e ``config/layouts_criados.yaml`` (salvos por voz).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..util.texto import normalizar
from . import windows

log = logging.getLogger(__name__)

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
WM_CLOSE = 0x0010
POSICOES = ["esquerda", "direita", "cima", "baixo", "superior_esquerda", "superior_direita", "inferior_esquerda",
            "inferior_direita", "centro", "tela_cheia"]
# fração do monitor (x, y, largura, altura)
FRACOES = {
    "esquerda": (0, 0, .5, 1), "direita": (.5, 0, .5, 1), "cima": (0, 0, 1, .5), "baixo": (0, .5, 1, .5),
    "superior_esquerda": (0, 0, .5, .5), "superior_direita": (.5, 0, .5, .5),
    "inferior_esquerda": (0, .5, .5, .5), "inferior_direita": (.5, .5, .5, .5), "centro": (.15, .1, .7, .8),
}
APELIDOS = {
    "navegador": ["chrome", "msedge", "firefox", "opera", "brave", "vivaldi"], "browser": ["chrome", "msedge", "firefox"],
    "chrome": ["chrome"], "google chrome": ["chrome"], "edge": ["msedge"], "firefox": ["firefox"],
    "vs code": ["code"], "vscode": ["code"], "visual studio code": ["code"], "code": ["code"],
    "visual studio": ["devenv"], "explorador": ["explorer"], "explorador de arquivos": ["explorer"],
    "terminal": ["windowsterminal", "cmd", "powershell", "pwsh"], "spotify": ["spotify"], "discord": ["discord"],
    "whatsapp": ["whatsapp", "whatsapp.root"], "word": ["winword"], "excel": ["excel"], "powerpoint": ["powerpnt"],
    "outlook": ["outlook", "olk"], "teams": ["ms-teams", "teams"], "steam": ["steamwebhelper", "steam"],
    "bloco de notas": ["notepad"], "obs": ["obs64"], "notion": ["notion"], "figma": ["figma"],
}
IGNORAR_EXE = {"textinputhost", "applicationframehost", "shellexperiencehost", "searchhost", "startmenuexperiencehost",
               "lockapp", "systemsettings_bg"}


class ErroJanelas(Exception):
    pass


@dataclass
class Janela:
    hwnd: int
    titulo: str
    exe: str          # nome do executável sem ".exe", minúsculo
    minimizada: bool = False
    maximizada: bool = False

    def rotulo(self) -> str:
        return f"{self.titulo} ({self.exe})" if self.titulo else self.exe


# -- escolha (independente do Windows, testável) ------------------------------------

def escolher_janela(nome: str, janelas: list[Janela]) -> Janela | None:
    alvo = normalizar(nome)
    alvo = alvo[2:] if alvo.startswith(("o ", "a ")) else alvo
    quer_hud = "sexta" in alvo or "hud" in alvo
    candidatas = [j for j in janelas if quer_hud or not normalizar(j.titulo).startswith("sexta feira")]
    exes = APELIDOS.get(alvo)
    if exes:
        for exe in exes:  # a ordem dos apelidos é a preferência
            achada = next((j for j in candidatas if j.exe == exe), None)
            if achada:
                return achada
    exata = next((j for j in candidatas if j.exe == alvo.replace(" ", "")), None)
    if exata:
        return exata
    from rapidfuzz import fuzz

    melhor, nota_melhor = None, 0.0
    for j in candidatas:
        nota = max(fuzz.WRatio(alvo, j.exe), fuzz.partial_ratio(alvo, normalizar(j.titulo)) - 3)
        if nota > nota_melhor:
            melhor, nota_melhor = j, nota
    return melhor if nota_melhor >= 80 else None


def retangulo_destino(posicao: str | dict, area: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """(x, y, largura, altura) em pixels dentro da área de trabalho do monitor."""
    esquerda, topo, direita, base = area
    largura, altura = direita - esquerda, base - topo
    if isinstance(posicao, dict):
        fx, fy, fl, fa = (float(posicao.get(k, padrao)) for k, padrao in (("x", 0), ("y", 0), ("l", 1), ("a", 1)))
    else:
        fx, fy, fl, fa = FRACOES[posicao]
    return (round(esquerda + fx * largura), round(topo + fy * altura), round(fl * largura), round(fa * altura))


# -- Windows ---------------------------------------------------------------------

_TIPOS_PRONTOS = False


def _user32():
    global _TIPOS_PRONTOS
    windows._exigir_windows()
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    if not _TIPOS_PRONTOS:  # handles de 64 bits não podem ser truncados para int de 32
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        _TIPOS_PRONTOS = True
    return ctypes, user32


def listar() -> list[Janela]:
    """Janelas visíveis com título, da mais à frente para a mais ao fundo."""
    ctypes, user32 = _user32()
    from ctypes import wintypes

    import psutil

    dwmapi = ctypes.windll.dwmapi
    janelas: list[Janela] = []
    nomes_pid: dict[int, str] = {}
    GWL_EXSTYLE, WS_EX_TOOLWINDOW, DWMWA_CLOAKED = -20, 0x00000080, 14

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visitar(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # GW_OWNER
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        oculta = ctypes.c_int(0)
        dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(oculta), ctypes.sizeof(oculta))
        if oculta.value:
            return True
        tamanho = user32.GetWindowTextLengthW(hwnd)
        if tamanho == 0:
            return True
        buffer = ctypes.create_unicode_buffer(tamanho + 1)
        user32.GetWindowTextW(hwnd, buffer, tamanho + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in nomes_pid:
            try:
                nomes_pid[pid.value] = psutil.Process(pid.value).name().lower().removesuffix(".exe")
            except (psutil.Error, OSError):
                nomes_pid[pid.value] = ""
        exe = nomes_pid[pid.value]
        if exe in IGNORAR_EXE:
            return True
        janelas.append(Janela(int(hwnd), buffer.value, exe, bool(user32.IsIconic(hwnd)), bool(user32.IsZoomed(hwnd))))
        return True

    user32.EnumWindows(visitar, 0)
    return janelas


def encontrar(nome: str) -> Janela | None:
    return escolher_janela(nome, listar())


def exigir(nome: str) -> Janela:
    janela = encontrar(nome)
    if janela is None:
        raise ErroJanelas(f"Não encontrei nenhuma janela de '{nome}' aberta.")
    return janela


def focar(janela: Janela) -> None:
    ctypes, user32 = _user32()
    if user32.IsIconic(janela.hwnd):
        user32.ShowWindow(janela.hwnd, SW_RESTORE)
    # o Windows só deixa um programa trazer outra janela para frente logo depois de uma tecla
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(janela.hwnd)
    user32.BringWindowToTop(janela.hwnd)


def mostrar(janela: Janela, modo: int) -> None:
    _, user32 = _user32()
    user32.ShowWindow(janela.hwnd, modo)


def fechar(janela: Janela) -> None:
    _, user32 = _user32()
    user32.PostMessageW(janela.hwnd, WM_CLOSE, 0, 0)


def minimizar_tudo() -> None:
    windows.apertar_combinacao("win", "m")


def monitores() -> list[dict[str, Any]]:
    """[{"area": (l, t, r, b) útil, "tela": (l, t, r, b), "principal": bool}] da esquerda para a direita."""
    ctypes, user32 = _user32()
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    lista: list[dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def visitar(hmon, _hdc, _rect, _):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        w, m = info.rcWork, info.rcMonitor
        lista.append({"handle": hmon, "area": (w.left, w.top, w.right, w.bottom),
                      "tela": (m.left, m.top, m.right, m.bottom), "principal": bool(info.dwFlags & 1)})
        return True

    user32.EnumDisplayMonitors(None, None, visitar, 0)
    return sorted(lista, key=lambda m: (m["tela"][0], m["tela"][1]))


def monitor_da_janela(janela: Janela, lista: list[dict[str, Any]] | None = None) -> int:
    _, user32 = _user32()
    lista = lista or monitores()
    hmon = user32.MonitorFromWindow(janela.hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    return next((i for i, m in enumerate(lista) if m["handle"] == hmon), 0)


def _bordas_invisiveis(hwnd: int) -> tuple[int, int, int, int]:
    """No Windows 10/11 as janelas têm uma borda invisível de ~7 px; compensa para encaixar certinho."""
    ctypes, user32 = _user32()
    from ctypes import wintypes

    externo, visivel = wintypes.RECT(), wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(externo))
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(visivel), ctypes.sizeof(visivel)) != 0:
        return (0, 0, 0, 0)
    return (visivel.left - externo.left, visivel.top - externo.top,
            externo.right - visivel.right, externo.bottom - visivel.bottom)


def encaixar(janela: Janela, posicao: str | dict, monitor: int | None = None) -> None:
    _, user32 = _user32()
    lista = monitores()
    indice = monitor_da_janela(janela, lista) if monitor is None else max(0, min(int(monitor), len(lista) - 1))
    if user32.IsIconic(janela.hwnd) or user32.IsZoomed(janela.hwnd):
        user32.ShowWindow(janela.hwnd, SW_RESTORE)
    if posicao == "tela_cheia":  # leva para o monitor certo e maximiza lá
        x, y, largura, altura = retangulo_destino("centro", lista[indice]["area"])
        user32.SetWindowPos(janela.hwnd, 0, x, y, largura, altura, 0x0004 | 0x0010)
        user32.ShowWindow(janela.hwnd, SW_MAXIMIZE)
        return
    x, y, largura, altura = retangulo_destino(posicao, lista[indice]["area"])
    be, bt, bd, bb = _bordas_invisiveis(janela.hwnd)
    SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
    user32.SetWindowPos(janela.hwnd, 0, x - be, y - bt, largura + be + bd, altura + bt + bb, SWP_NOZORDER | SWP_NOACTIVATE)


def mover_para_monitor(janela: Janela, destino: int | None = None) -> int:
    """Manda a janela para outro monitor mantendo a proporção. Devolve o índice do monitor."""
    ctypes, user32 = _user32()
    from ctypes import wintypes

    lista = monitores()
    if len(lista) < 2:
        raise ErroJanelas("Só encontrei um monitor.")
    atual = monitor_da_janela(janela, lista)
    destino = (atual + 1) % len(lista) if destino is None else max(0, min(int(destino), len(lista) - 1))
    maximizada = bool(user32.IsZoomed(janela.hwnd))
    if maximizada or user32.IsIconic(janela.hwnd):
        user32.ShowWindow(janela.hwnd, SW_RESTORE)
    ret = wintypes.RECT()
    user32.GetWindowRect(janela.hwnd, ctypes.byref(ret))
    origem = lista[atual]["area"]
    lo, ao = origem[2] - origem[0], origem[3] - origem[1]
    fracao = {"x": (ret.left - origem[0]) / lo, "y": (ret.top - origem[1]) / ao,
              "l": (ret.right - ret.left) / lo, "a": (ret.bottom - ret.top) / ao}
    x, y, largura, altura = retangulo_destino(fracao, lista[destino]["area"])
    user32.SetWindowPos(janela.hwnd, 0, x, y, largura, altura, 0x0004 | 0x0010)
    if maximizada:
        user32.ShowWindow(janela.hwnd, SW_MAXIMIZE)
    return destino


def posicao_relativa(janela: Janela, lista: list[dict[str, Any]]) -> tuple[int, dict[str, float]]:
    ctypes, user32 = _user32()
    from ctypes import wintypes

    indice = monitor_da_janela(janela, lista)
    if user32.IsZoomed(janela.hwnd):
        return indice, {"x": 0, "y": 0, "l": 1, "a": 1}
    ret = wintypes.RECT()
    user32.GetWindowRect(janela.hwnd, ctypes.byref(ret))
    l, t, r, b = lista[indice]["area"]
    return indice, {"x": round((ret.left - l) / (r - l), 3), "y": round((ret.top - t) / (b - t), 3),
                    "l": round((ret.right - ret.left) / (r - l), 3), "a": round((ret.bottom - ret.top) / (b - t), 3)}


# -- layouts -------------------------------------------------------------------------

class Layouts:
    def __init__(self, app, arquivo: Path, arquivo_criados: Path) -> None:
        self.app = app
        self.arquivo = arquivo
        self.arquivo_criados = arquivo_criados
        self._layouts: dict[str, list[dict]] = {}
        self.recarregar()

    def recarregar(self) -> None:
        layouts: dict[str, list[dict]] = {}
        for arquivo in (self.arquivo, self.arquivo_criados):
            if not arquivo.exists():
                continue
            try:
                dados = yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as erro:
                log.error("Erro lendo %s: %s", arquivo.name, erro)
                continue
            for nome, itens in (dados.get("layouts") or {}).items():
                validos = [i for i in itens or [] if isinstance(i, dict) and i.get("app")]
                if validos:
                    layouts[normalizar(str(nome))] = validos
        self._layouts = layouts

    def nomes(self) -> list[str]:
        return list(self._layouts)

    def obter(self, nome: str) -> tuple[str, list[dict]] | None:
        alvo = normalizar(nome)
        for prefixo in ("layout ", "modo "):
            if alvo.startswith(prefixo) and alvo not in self._layouts:
                alvo = alvo[len(prefixo):]
        if alvo in self._layouts:
            return alvo, self._layouts[alvo]
        return None

    def aplicar(self, nome: str) -> list[str]:
        achado = self.obter(nome)
        if achado is None:
            raise ErroJanelas(f"Não conheço o layout '{nome}'. Disponíveis: {', '.join(self.nomes()) or 'nenhum'}.")
        _, itens = achado
        feitos = []
        for item in itens:
            app_nome = str(item["app"])
            janela = encontrar(app_nome)
            if janela is None and item.get("abrir", True):
                self.app.apps.abrir(str(item.get("abrir_com") or app_nome))
                limite = time.monotonic() + float(item.get("esperar", 10))
                while janela is None and time.monotonic() < limite:
                    time.sleep(0.5)
                    janela = encontrar(app_nome)
            if janela is None:
                log.info("Layout: não achei a janela de %s", app_nome)
                continue
            encaixar(janela, item.get("posicao", "tela_cheia"), item.get("monitor"))
            feitos.append(app_nome)
        return feitos

    def salvar_atual(self, nome: str, maximo: int = 6) -> list[str]:
        lista = monitores()
        janelas = [j for j in listar() if not j.minimizada and not normalizar(j.titulo).startswith("sexta feira")][:maximo]
        if not janelas:
            raise ErroJanelas("Não há janelas abertas para salvar.")
        itens = []
        for j in reversed(janelas):  # do fundo para a frente: reaplicar mantém a ordem
            monitor, posicao = posicao_relativa(j, lista)
            itens.append({"app": j.exe, "posicao": posicao, "monitor": monitor})
        dados: dict = {"layouts": {}}
        if self.arquivo_criados.exists():
            dados = yaml.safe_load(self.arquivo_criados.read_text(encoding="utf-8")) or {"layouts": {}}
            dados.setdefault("layouts", {})
        dados["layouts"][nome] = itens
        cabecalho = "# Layouts de janelas salvos pela Sexta-Feira. Pode editar ou apagar.\n"
        self.arquivo_criados.write_text(cabecalho + yaml.safe_dump(dados, allow_unicode=True, sort_keys=False),
                                        encoding="utf-8")
        self.recarregar()
        return [i["app"] for i in itens]
