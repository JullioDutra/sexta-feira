"""Modo jogo automático e overlay de jogo do traje.

Um jogo é um processo cujo executável fica numa pasta de jogos (Steam ``steamapps\\common``, Epic Games,
Riot Games, XboxGames, GOG Galaxy\\Games) ou cujo nome está na preferência ``jogos``; os launchers
(Steam, Epic, Riot Client...) não contam. Quando um jogo abre (com ``modo_jogo_auto``): plano de energia
"desempenho máximo" e "não perturbe"; ao fechar, tudo volta (plano equilibrado, notificações).

O overlay é a página ``/overlay`` do HUD aberta no Edge em modo app, no canto superior direito do monitor do
jogo, e posta "sempre visível" (``SetWindowPos`` com ``HWND_TOPMOST``). Aparece sobre jogos em janela ou em
"tela cheia sem bordas"; em tela cheia exclusiva o Windows não deixa outra janela por cima. O FPS vem do
Intel PresentMon (opcional: variável ``PRESENTMON`` ou ``dados/ferramentas/PresentMon*.exe``).
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

from ..habilidades import windows

log = logging.getLogger(__name__)

TITULO_OVERLAY = "Sexta-Feira Overlay"
LARGURA_OVERLAY, ALTURA_OVERLAY, MARGEM_OVERLAY = 300, 214, 16
PASTAS_JOGOS = ("\\steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\xboxgames\\", "\\gog galaxy\\games\\")
LAUNCHERS = {
    "steam.exe", "steamwebhelper.exe", "steamservice.exe", "steamerrorreporter.exe", "steamerrorreporter64.exe",
    "epicgameslauncher.exe", "epicwebhelper.exe", "epiconlineservices.exe", "epiconlineserviceshost.exe",
    "riotclientservices.exe", "riotclientux.exe", "riotclientuxrender.exe", "riotclientcrashhandler.exe", "vgtray.exe",
    "galaxyclient.exe", "galaxyclient helper.exe", "galaxycommunication.exe", "gog galaxy notifications renderer.exe",
    "xboxpcapp.exe", "gamingservices.exe", "gamingservicesnet.exe", "unrealcefsubprocess.exe", "crashreportclient.exe",
    "easyanticheat.exe", "easyanticheat_eos.exe", "easyanticheat_eos_setup.exe", "beservice.exe", "battleye launcher.exe",
    "unitycrashhandler64.exe", "unitycrashhandler32.exe", "cefsharp.browsersubprocess.exe", "vc_redist.x64.exe",
    "vc_redist.x86.exe", "dxsetup.exe", "ue4prereqsetup_x64.exe", "ueprereqsetup_x64.exe", "launcher.exe",
}
COLUNAS_FPS = ("msbetweenpresents", "frametime")
# PresentMon 2.x e 1.x: mesmas opções, um ou dois traços
ARGUMENTOS_PRESENTMON = (
    ["--process_id", "{pid}", "--output_stdout", "--terminate_on_proc_exit", "--stop_existing_session",
     "--session_name", "SextaFeiraFPS"],
    ["-process_id", "{pid}", "-output_stdout", "-terminate_on_proc_exit", "-stop_existing_session",
     "-session_name", "SextaFeiraFPS"],
)
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0010, 0x0040


# -- reconhecer jogos (independente do Windows, testável) ----------------------------------------------
def _normalizar_caminho(caminho: str) -> str:
    return "\\" + (caminho or "").replace("/", "\\").lower().lstrip("\\")


def _exe(nome: str) -> str:
    nome = (nome or "").strip().lower()
    return nome if nome.endswith(".exe") else nome + ".exe"


def eh_jogo(nome: str, caminho: str | None, extras: list[str] | tuple[str, ...] = ()) -> bool:
    """Se o processo é um jogo: nome na lista do usuário, ou executável numa pasta de jogos (fora os launchers)."""
    exe = _exe(nome)
    if exe in {_exe(j) for j in extras if str(j).strip()}:
        return True
    if exe in LAUNCHERS or not caminho:
        return False
    alvo = _normalizar_caminho(caminho)
    return any(pasta in alvo for pasta in PASTAS_JOGOS)


def procurar_jogo(processos: list[dict], extras: list[str] | tuple[str, ...] = ()) -> dict | None:
    """O jogo aberto (o de mais memória, se houver vários processos de jogo): {"pid", "nome", "exe"}."""
    jogos = [p for p in processos if eh_jogo(p.get("nome") or "", p.get("exe"), extras)]
    if not jogos:
        return None
    return max(jogos, key=lambda p: p.get("memoria") or 0)


def nome_amigavel(nome: str) -> str:
    """ "EldenRing.exe" -> "Elden Ring"; "FortniteClient-Win64-Shipping.exe" -> "Fortnite Client"."""
    base = re.sub(r"\.exe$", "", nome or "", flags=re.I)
    base = re.sub(r"[-_](win(64|32)|shipping|dx1[12]|vulkan|x64|x86)\b", "", base, flags=re.I)
    base = re.sub(r"[-_]+", " ", base)
    base = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base)
    return base.strip() or nome


def listar_processos() -> list[dict]:
    import psutil

    processos = []
    for p in psutil.process_iter(["pid", "name", "exe", "memory_info"]):
        info = p.info
        memoria = info.get("memory_info")
        processos.append({"pid": info["pid"], "nome": info.get("name") or "", "exe": info.get("exe") or "",
                          "memoria": memoria.rss if memoria else 0})
    return processos


# -- FPS ----------------------------------------------------------------------------------------------
class ContadorFps:
    """FPS móvel do último segundo, a partir do tempo entre quadros (ms)."""

    def __init__(self, silencio_s: float = 2.0) -> None:
        self._quadros: deque[float] = deque(maxlen=2000)
        self._ultimo = 0.0
        self._lock = threading.Lock()
        self.silencio_s = silencio_s

    def adicionar(self, ms: float, agora: float | None = None) -> None:
        if not 0 < ms < 5000:
            return
        with self._lock:
            self._quadros.append(ms)
            self._ultimo = time.monotonic() if agora is None else agora

    def fps(self, agora: float | None = None) -> float | None:
        agora = time.monotonic() if agora is None else agora
        with self._lock:
            if not self._quadros or agora - self._ultimo > self.silencio_s:
                return None
            soma = contados = 0
            for ms in reversed(self._quadros):
                if soma + ms > 1000 and contados:
                    break
                soma += ms
                contados += 1
        return round(contados * 1000 / soma, 1) if soma else None


def coluna_fps(cabecalho: list[str]) -> int | None:
    nomes = [c.strip().lower() for c in cabecalho]
    for alvo in COLUNAS_FPS:
        if alvo in nomes:
            return nomes.index(alvo)
    return None


def caminho_presentmon(pasta_dados: Path) -> Path | None:
    """PRESENTMON (variável de ambiente) ou o PresentMon*.exe mais novo em dados/ferramentas."""
    definido = os.environ.get("PRESENTMON", "").strip().strip('"')
    if definido:
        caminho = Path(definido)
        return caminho if caminho.is_file() else None
    pasta = pasta_dados / "ferramentas"
    try:
        achados = sorted(pasta.glob("PresentMon*.exe"))
    except OSError:
        return None
    return achados[-1] if achados else None


class LeitorPresentMon:
    """Roda o PresentMon para um PID e alimenta um :class:`ContadorFps`. Tenta a sintaxe 2.x e depois a 1.x."""

    def __init__(self, exe: Path, popen: Callable[..., Any] = subprocess.Popen) -> None:
        self.exe = exe
        self.popen = popen
        self.contador = ContadorFps()
        self._processo = None
        self._parar = threading.Event()
        self.erro = ""
        self.ativo = False

    def iniciar(self, pid: int) -> None:
        self._parar.clear()
        threading.Thread(target=self._laco, args=(pid,), name="presentmon", daemon=True).start()

    def _laco(self, pid: int) -> None:
        for variante in ARGUMENTOS_PRESENTMON:
            if self._parar.is_set():
                return
            argumentos = [str(self.exe)] + [a.format(pid=pid) for a in variante]
            try:
                self._processo = self.popen(argumentos, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                            creationflags=windows.SEM_JANELA)
            except OSError as erro:
                self.erro = f"PresentMon não abriu: {erro}"
                return
            if self.ler(self._processo.stdout):
                return  # leu quadros: terminou porque o jogo fechou (ou pedimos para parar)
            self._encerrar_processo()
        if not self._parar.is_set():
            self.erro = "PresentMon não mediu o jogo (rode a Sexta-Feira como administrador ou entre no grupo Performance Log Users)"
            log.info(self.erro)

    def ler(self, saida) -> bool:
        """Lê o CSV do PresentMon; devolve True se reconheceu o cabeçalho."""
        indice = None
        for bruta in saida:
            if self._parar.is_set():
                return True
            linha = bruta.decode("utf-8", "replace") if isinstance(bruta, bytes) else bruta
            if not linha.strip():
                continue
            campos = next(csv.reader(io.StringIO(linha)), [])
            if indice is None:
                indice = coluna_fps(campos)
                self.ativo = indice is not None
                continue
            if len(campos) > indice:
                try:
                    self.contador.adicionar(float(campos[indice]))
                except ValueError:
                    pass
        self.ativo = False
        return indice is not None

    def fps(self) -> float | None:
        return self.contador.fps()

    def _encerrar_processo(self) -> None:
        processo, self._processo = self._processo, None
        if processo is None:
            return
        try:
            processo.terminate()
        except OSError:
            pass

    def parar(self) -> None:
        self._parar.set()
        self.ativo = False
        self._encerrar_processo()


# -- janela do overlay (Windows) ----------------------------------------------------------------------
def posicao_overlay(area: tuple[int, int, int, int], largura: int = LARGURA_OVERLAY,
                    margem: int = MARGEM_OVERLAY) -> tuple[int, int]:
    """Canto superior direito da área do monitor."""
    esquerda, topo, direita, _base = area
    return max(esquerda, direita - largura - margem), topo + margem


def caminho_edge() -> str | None:
    achado = shutil.which("msedge")
    if achado:
        return achado
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidato = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if candidato.is_file():
                return str(candidato)
    return None


def _set_window_pos():
    import ctypes
    from ctypes import wintypes

    funcao = ctypes.windll.user32.SetWindowPos
    funcao.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    funcao.restype = wintypes.BOOL
    return funcao


class JanelaOverlay:
    """Abre, fixa por cima de tudo e fecha a janela do overlay (Edge em modo app)."""

    def __init__(self, pasta_dados: Path) -> None:
        self.perfil = pasta_dados / "edge_overlay"
        self._processo = None
        self._hwnd: int | None = None
        self._lock = threading.Lock()

    def _monitor(self, exe_jogo: str | None) -> tuple[int, int, int, int]:
        from ..habilidades import janelas

        lista = janelas.monitores()
        indice = next((i for i, m in enumerate(lista) if m["principal"]), 0)
        if exe_jogo:
            alvo = exe_jogo.lower().removesuffix(".exe")
            janela = next((j for j in janelas.listar() if j.exe == alvo), None)
            if janela is not None:
                indice = janelas.monitor_da_janela(janela, lista)
        return lista[indice]["tela"] if lista else (0, 0, 1920, 1080)

    def abrir(self, url: str, exe_jogo: str | None = None) -> tuple[bool, str]:
        if not windows.WINDOWS:
            return False, "O overlay de jogo só funciona no Windows."
        edge = caminho_edge()
        if edge is None:
            return False, "Não encontrei o Microsoft Edge, que abre o overlay."
        self.fechar()
        try:
            area = self._monitor(exe_jogo)
        except Exception as erro:  # noqa: BLE001 - sem a posição, o canto do monitor principal serve
            log.info("Não consegui achar o monitor do jogo: %s", erro)
            area = (0, 0, 1920, 1080)
        x, y = posicao_overlay(area)
        self.perfil.mkdir(parents=True, exist_ok=True)
        try:
            processo = subprocess.Popen([edge, f"--app={url}", f"--window-size={LARGURA_OVERLAY},{ALTURA_OVERLAY}",
                                         f"--window-position={x},{y}", f"--user-data-dir={self.perfil}",
                                         "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"],
                                        creationflags=windows.SEM_JANELA)
        except OSError as erro:
            return False, f"Não consegui abrir o overlay: {erro}"
        with self._lock:
            self._processo, self._hwnd = processo, None
        threading.Thread(target=self._fixar, args=(area,), name="overlay-fixar", daemon=True).start()
        return True, ""

    def _achar(self) -> int | None:
        from ..habilidades import janelas

        try:
            return next((j.hwnd for j in janelas.listar() if j.titulo.startswith(TITULO_OVERLAY)), None)
        except Exception:  # noqa: BLE001
            return None

    def _fixar(self, area: tuple[int, int, int, int]) -> None:
        """Espera a janela aparecer (título "Sexta-Feira Overlay") e põe por cima de tudo, no canto superior
        direito do monitor, sem roubar o foco. A largura real vem da janela (com zoom de 125%, 150%... o Edge
        a deixa maior que o pedido)."""
        limite = time.monotonic() + 20
        while time.monotonic() < limite:
            hwnd = self._achar()
            if hwnd:
                with self._lock:
                    self._hwnd = hwnd
                largura = LARGURA_OVERLAY
                try:
                    import ctypes
                    from ctypes import wintypes

                    retangulo = wintypes.RECT()
                    if ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(retangulo)):
                        largura = retangulo.right - retangulo.left
                except (OSError, AttributeError):
                    pass
                self.manter_no_topo(*posicao_overlay(area, largura))
                return
            time.sleep(0.4)
        log.warning("A janela do overlay não apareceu")

    def manter_no_topo(self, x: int | None = None, y: int | None = None) -> None:
        with self._lock:
            hwnd = self._hwnd
        if not hwnd or not windows.WINDOWS:
            return
        try:
            flags = SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOSIZE | (SWP_NOMOVE if x is None else 0)
            _set_window_pos()(hwnd, HWND_TOPMOST, x or 0, y or 0, 0, 0, flags)
        except (OSError, AttributeError) as erro:
            log.info("SetWindowPos falhou: %s", erro)

    def aberta(self) -> bool:
        with self._lock:
            return self._processo is not None

    def fechar(self) -> None:
        with self._lock:
            processo, hwnd = self._processo, self._hwnd
            self._processo = self._hwnd = None
        if processo is None and hwnd is None:
            return
        hwnd = hwnd or self._achar()
        if hwnd and windows.WINDOWS:
            try:
                import ctypes

                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                return
            except (OSError, AttributeError):
                pass
        if processo is not None:
            try:
                processo.terminate()
            except OSError:
                pass
