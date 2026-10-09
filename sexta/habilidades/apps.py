"""Descobre o que abrir a partir de um nome falado: app, site, pasta ou URL."""

from __future__ import annotations

import logging
import re
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..util.texto import normalizar
from . import windows

log = logging.getLogger(__name__)

APPS_PADRAO = {
    "calculadora": "calc", "bloco de notas": "notepad", "notepad": "notepad", "paint": "mspaint",
    "explorador de arquivos": "explorer", "explorador": "explorer", "arquivos": "explorer", "explorer": "explorer",
    "configuracoes": "ms-settings:", "configuracao": "ms-settings:", "ajustes": "ms-settings:",
    "configuracoes de som": "ms-settings:sound", "configuracoes de bluetooth": "ms-settings:bluetooth",
    "configuracoes de wifi": "ms-settings:network-wifi", "windows update": "ms-settings:windowsupdate",
    "gerenciador de tarefas": "taskmgr", "terminal": "wt", "prompt de comando": "cmd", "cmd": "cmd",
    "powershell": "powershell", "painel de controle": "control", "camera": "microsoft.windows.camera:",
    "loja": "ms-windows-store:", "microsoft store": "ms-windows-store:", "relogio": "ms-clock:",
    "alarmes": "ms-clock:", "edge": "msedge", "lixeira": "shell:RecycleBinFolder",
}
SITES_PADRAO = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com", "gmail": "https://mail.google.com",
    "email": "https://mail.google.com", "netflix": "https://www.netflix.com", "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com", "twitter": "https://x.com", "x": "https://x.com",
    "github": "https://github.com", "whatsapp web": "https://web.whatsapp.com", "linkedin": "https://www.linkedin.com",
    "twitch": "https://www.twitch.tv", "spotify web": "https://open.spotify.com", "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com", "drive": "https://drive.google.com", "google drive": "https://drive.google.com",
    "agenda": "https://calendar.google.com", "calendario": "https://calendar.google.com",
    "amazon": "https://www.amazon.com.br", "mercado livre": "https://www.mercadolivre.com.br",
    "g1": "https://g1.globo.com", "globo": "https://www.globo.com", "ge": "https://ge.globo.com",
    "uol": "https://www.uol.com.br", "tradutor": "https://translate.google.com", "prime video": "https://www.primevideo.com",
    "disney": "https://www.disneyplus.com", "max": "https://play.max.com", "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai", "reddit": "https://www.reddit.com", "wikipedia": "https://pt.wikipedia.org",
}
PASTAS = {"downloads": "downloads", "documentos": "documentos", "meus documentos": "documentos",
          "imagens": "imagens", "fotos": "imagens", "musicas": "musicas", "videos": "videos",
          "area de trabalho": "area de trabalho", "desktop": "area de trabalho"}

# nome falado -> executáveis (para fechar programas)
PROCESSOS = {
    "chrome": ["chrome.exe"], "google chrome": ["chrome.exe"], "edge": ["msedge.exe"], "navegador": ["msedge.exe", "chrome.exe"],
    "firefox": ["firefox.exe"], "opera": ["opera.exe"], "spotify": ["Spotify.exe"], "discord": ["Discord.exe"],
    "steam": ["steam.exe"], "word": ["WINWORD.EXE"], "excel": ["EXCEL.EXE"], "powerpoint": ["POWERPNT.EXE"],
    "outlook": ["OUTLOOK.EXE", "olk.exe"], "vscode": ["Code.exe"], "vs code": ["Code.exe"],
    "visual studio code": ["Code.exe"], "bloco de notas": ["notepad.exe"], "notepad": ["notepad.exe"],
    "calculadora": ["CalculatorApp.exe"], "whatsapp": ["WhatsApp.exe", "WhatsApp.Root.exe"],
    "teams": ["ms-teams.exe", "Teams.exe"], "obs": ["obs64.exe"], "epic games": ["EpicGamesLauncher.exe"],
    "paint": ["mspaint.exe"], "vlc": ["vlc.exe"], "telegram": ["Telegram.exe"], "zoom": ["Zoom.exe"],
}
NUNCA_FECHAR = {"explorer.exe", "csrss.exe", "winlogon.exe", "svchost.exe", "lsass.exe", "dwm.exe", "services.exe",
                "smss.exe", "wininit.exe", "system", "python.exe", "pythonw.exe", "ollama.exe", "ollama app.exe"}
_PREFIXOS = re.compile(r"^(o |a |os |as )?(app |aplicativo |programa |site do |site da |site |pasta |pasta de |a pasta )?")


@dataclass
class Alvo:
    tipo: str   # "app", "comando", "site", "url", "pasta"
    valor: str
    nome: str


class CatalogoApps:
    def __init__(self, arquivo: Path) -> None:
        self.arquivo = arquivo
        self._apps_usuario: dict[str, str] = {}
        self._sites_usuario: dict[str, str] = {}
        self._menu: list[dict] = []
        self._menu_carregado_em = 0.0
        self._lock = threading.Lock()
        self.recarregar()

    def recarregar(self) -> None:
        if not self.arquivo.exists():
            return
        try:
            dados = yaml.safe_load(self.arquivo.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as erro:
            log.error("Erro lendo %s: %s", self.arquivo.name, erro)
            return
        self._apps_usuario = {normalizar(k): str(v) for k, v in (dados.get("apps") or {}).items()}
        self._sites_usuario = {normalizar(k): str(v) for k, v in (dados.get("sites") or {}).items()}

    def menu_iniciar(self, forcar: bool = False) -> list[dict]:
        with self._lock:
            if forcar or not self._menu or time.time() - self._menu_carregado_em > 600:
                try:
                    self._menu = windows.apps_do_menu_iniciar()
                except Exception as erro:  # noqa: BLE001
                    log.warning("Não consegui listar os apps do Menu Iniciar: %s", erro)
                self._menu_carregado_em = time.time()
            return self._menu

    # ------------------------------------------------------------------
    def resolver(self, pedido: str) -> Alvo | None:
        bruto = pedido.strip().strip('"\'')
        if re.search(r"\.(exe|bat|cmd|lnk|msc|ps1)$", bruto, re.I):
            return Alvo("comando", bruto, Path(bruto).name)
        if re.match(r"^(https?://|www\.)", bruto, re.I) or re.match(r"^[\w-]+(\.[\w-]+)+(/\S*)?$", bruto):
            url = bruto if bruto.lower().startswith("http") else f"https://{bruto}"
            return Alvo("url", url, bruto)
        if re.match(r"^[a-zA-Z]:\\", bruto) or bruto.startswith("\\\\"):
            return Alvo("comando", bruto, Path(bruto).name)
        nome = _PREFIXOS.sub("", normalizar(bruto)).strip()
        if not nome:
            return None
        for tabela, tipo in ((self._apps_usuario, "comando"), (self._sites_usuario, "site")):
            if nome in tabela:
                valor = tabela[nome]
                return Alvo("site" if valor.startswith("http") else tipo, valor, nome)
        if nome in PASTAS:
            return Alvo("pasta", PASTAS[nome], nome)
        if nome in APPS_PADRAO:
            return Alvo("comando", APPS_PADRAO[nome], nome)

        menu = self.menu_iniciar()
        if menu:
            from rapidfuzz import fuzz, process

            nomes = [normalizar(a["nome"]) for a in menu]
            achado = process.extractOne(nome, nomes, scorer=fuzz.WRatio, score_cutoff=86)
            if achado:
                app = menu[achado[2]]
                return Alvo("app", app["id"], app["nome"])
        if nome in SITES_PADRAO:
            return Alvo("site", SITES_PADRAO[nome], nome)
        if menu:
            from rapidfuzz import fuzz, process

            achado = process.extractOne(nome, [normalizar(a["nome"]) for a in menu], scorer=fuzz.token_set_ratio, score_cutoff=90)
            if achado:
                app = menu[achado[2]]
                return Alvo("app", app["id"], app["nome"])
        return None

    def sugestoes(self, pedido: str, n: int = 3) -> list[str]:
        menu = self.menu_iniciar()
        if not menu:
            return []
        from rapidfuzz import fuzz, process

        nomes = [a["nome"] for a in menu]
        return [m[0] for m in process.extract(normalizar(pedido), nomes, scorer=fuzz.WRatio,
                                              processor=normalizar, limit=n, score_cutoff=55)]

    def abrir(self, pedido: str) -> tuple[bool, str]:
        alvo = self.resolver(pedido)
        if alvo is None:
            sugestoes = self.sugestoes(pedido)
            dica = f" Você quis dizer {', '.join(sugestoes)}?" if sugestoes else ""
            return False, f"Não encontrei '{pedido}' nos apps do computador.{dica}"
        try:
            if alvo.tipo in ("site", "url"):
                webbrowser.open(alvo.valor)
            elif alvo.tipo == "app":
                windows.abrir_app_da_loja(alvo.valor)
            elif alvo.tipo == "pasta":
                windows.abrir_no_sistema(str(windows.pasta_conhecida(alvo.valor)))
            else:
                windows.abrir_no_sistema(alvo.valor)
        except Exception as erro:  # noqa: BLE001
            log.warning("Falha ao abrir %s: %s", alvo, erro)
            return False, f"Não consegui abrir {alvo.nome}: {erro}"
        rotulo = {"site": "o site", "url": "o endereço", "pasta": "a pasta"}.get(alvo.tipo, "")
        return True, f"Abrindo {rotulo + ' ' if rotulo else ''}{alvo.nome}."

    def fechar(self, pedido: str) -> tuple[bool, str]:
        nome = _PREFIXOS.sub("", normalizar(pedido)).strip()
        executaveis = PROCESSOS.get(nome)
        if not executaveis:
            executaveis = self._procurar_processo(nome)
        executaveis = [e for e in executaveis or [] if e.lower() not in NUNCA_FECHAR]
        if not executaveis:
            return False, f"Não encontrei '{pedido}' aberto."
        fechados = windows.fechar_processos(executaveis)
        if fechados == 0:
            return False, f"{pedido} não parece estar aberto."
        return True, f"Fechando {pedido}."

    @staticmethod
    def _procurar_processo(nome: str) -> list[str]:
        try:
            import psutil
            from rapidfuzz import fuzz
        except ImportError:
            return []
        candidatos: dict[str, float] = {}
        for proc in psutil.process_iter(["name"]):
            exe = proc.info.get("name") or ""
            base = normalizar(exe.rsplit(".", 1)[0])
            if not base:
                continue
            nota = fuzz.WRatio(nome, base)
            if nota >= 88:
                candidatos[exe] = max(nota, candidatos.get(exe, 0))
        return sorted(candidatos, key=candidatos.get, reverse=True)[:1]
