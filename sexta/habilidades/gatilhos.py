"""Sensores dos protocolos: percebem eventos do PC e avisam ``Rotinas.disparar``.

Só ficam ligados os sensores que algum protocolo ativo usa, e todos são leves
(leituras a cada poucos segundos, sem ganchos no sistema):

- app_aberto / app_fechado: lista de processos (psutil);
- bateria_baixa: nível da bateria;
- pendrive: unidades removíveis;
- arquivo_novo: arquivos novos (e já completos) numa pasta;
- wifi: nome da rede conectada;
- voltar_ao_pc: tempo sem mexer no mouse/teclado (e, opcionalmente, o rosto na câmera).

O desbloqueio do Windows é avisado pelo vigia que já existe em ``app.py``.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from ..util.texto import normalizar
from . import windows

log = logging.getLogger(__name__)

IGNORAR_EXTENSOES = {".crdownload", ".part", ".tmp", ".download", ".partial"}


# -- leituras do sistema ----------------------------------------------------------------

def nomes_processos() -> set[str]:
    import psutil

    nomes = set()
    for p in psutil.process_iter(["name"]):
        nome = p.info.get("name")
        if nome:
            nomes.add(nome)
    return nomes


def bateria() -> tuple[int, bool] | None:
    import psutil

    try:
        b = psutil.sensors_battery()
    except (AttributeError, NotImplementedError, OSError):
        return None
    return (round(b.percent), bool(b.power_plugged)) if b else None


def unidades_removiveis() -> dict[str, str]:
    """{ponto de montagem: rótulo}"""
    import psutil

    unidades = {}
    for parte in psutil.disk_partitions(all=False):
        removivel = "removable" in parte.opts if windows.WINDOWS else parte.mountpoint.startswith(("/media/", "/run/media/"))
        if removivel:
            unidades[parte.mountpoint] = _rotulo(parte.mountpoint)
    return unidades


def _rotulo(unidade: str) -> str:
    if not windows.WINDOWS:
        return Path(unidade).name
    import ctypes

    buffer = ctypes.create_unicode_buffer(261)
    if ctypes.windll.kernel32.GetVolumeInformationW(unidade, buffer, 261, None, None, None, None, 0):
        return buffer.value
    return ""


def rede_wifi() -> str | None:
    """Nome (SSID) da rede Wi-Fi conectada, ou ``None``."""
    try:
        if windows.WINDOWS:
            r = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, timeout=8,
                               creationflags=windows.SEM_JANELA)
            for linha in r.stdout.decode("oem", "replace").splitlines():
                m = re.match(r"^\s*SSID\s*:\s*(.+?)\s*$", linha)  # "BSSID" não casa por causa do ^\s*SSID
                if m:
                    return m.group(1)
            return None
        r = subprocess.run(["iwgetid", "-r"], capture_output=True, timeout=5)
        return r.stdout.decode().strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def segundos_ocioso() -> float | None:
    """Há quanto tempo ninguém mexe no mouse/teclado (Windows)."""
    if not windows.WINDOWS:
        return None
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


def em_reuniao() -> bool:
    """Outro programa está usando o microfone (Teams, Zoom, Meet, Discord...)?

    O Windows anota em ``CapabilityAccessManager`` quem está com o microfone aberto
    (``LastUsedTimeStop == 0``). A própria Sexta-Feira (Python) é ignorada.
    """
    if not windows.WINDOWS:
        return False
    import winreg

    raiz = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

    def em_uso(caminho: str) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, caminho) as k:
                parada, _ = winreg.QueryValueEx(k, "LastUsedTimeStop")
                inicio, _ = winreg.QueryValueEx(k, "LastUsedTimeStart")
                return parada == 0 and inicio > 0
        except OSError:
            return False

    def filhos(caminho: str) -> list[str]:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, caminho) as k:
                return [winreg.EnumKey(k, i) for i in range(winreg.QueryInfoKey(k)[0])]
        except OSError:
            return []

    for nome in filhos(raiz):
        if nome == "NonPackaged":
            for exe in filhos(f"{raiz}\\NonPackaged"):
                if "python" not in exe.lower() and em_uso(f"{raiz}\\NonPackaged\\{exe}"):
                    return True
        elif em_uso(f"{raiz}\\{nome}"):
            return True
    return False


def chovendo(app) -> bool:
    """Está chovendo agora na cidade do usuário (ou chove na hora atual com 60%+)?"""
    prefs = app.prefs
    if prefs.get("cidade_lat") is None:
        return False
    local = {"lat": prefs.get("cidade_lat"), "lon": prefs.get("cidade_lon"),
             "rotulo": prefs.get("cidade_rotulo") or prefs.get("cidade")}
    try:
        dados = app.clima.obter(local)  # usa o cache de 10 min do serviço de clima
    except Exception as erro:  # noqa: BLE001
        log.warning("Condição 'chovendo' sem dados do clima: %s", erro)
        return False
    if dados["atual"]["icone"] in ("chuva", "chuva_forte", "tempestade"):
        return True
    proxima = (dados.get("horas") or [{}])[0]
    return (proxima.get("chuva") or 0) >= 60


def resolver_pasta(nome: str) -> Path | None:
    nome = (nome or "").strip().strip('"')
    if not nome:
        return None
    caminho = Path(nome).expanduser()
    if caminho.is_absolute():
        return caminho
    conhecidas = {"downloads": "downloads", "documentos": "documentos", "imagens": "imagens", "fotos": "imagens",
                  "musicas": "musicas", "videos": "videos", "area de trabalho": "area de trabalho",
                  "desktop": "area de trabalho"}
    chave = normalizar(nome)
    if chave in conhecidas:
        return windows.pasta_conhecida(conhecidas[chave])
    return Path.home() / nome


# -- o vigia --------------------------------------------------------------------------------

class Vigia:
    PASSO_S = 2.0

    def __init__(self, app) -> None:
        self.app = app
        self._rodando = False
        self._proximo: dict[str, float] = {}
        self._processos: set[str] | None = None
        self._bateria_avisada: dict[int, bool] = {}
        self._unidades: dict[str, str] | None = None
        self._pastas: dict[Path, dict[str, int]] = {}
        self._pendentes: dict[Path, dict[str, int]] = {}
        self._rede: str | None = None
        self._rede_lida = False
        self._ausente_desde: float | None = None
        self._ultima_camera = 0.0

    def iniciar(self) -> None:
        self._rodando = True
        threading.Thread(target=self._laco, name="vigia-protocolos", daemon=True).start()

    def parar(self) -> None:
        self._rodando = False

    def _laco(self) -> None:
        while self._rodando:
            try:
                self.verificar()
            except Exception:  # noqa: BLE001 - um sensor com erro não pode derrubar os outros
                log.exception("Erro no vigia de protocolos")
            time.sleep(self.PASSO_S)

    def _hora_de(self, sensor: str, intervalo: float) -> bool:
        agora = time.monotonic()
        if agora < self._proximo.get(sensor, 0):
            return False
        self._proximo[sensor] = agora + intervalo
        return True

    def verificar(self) -> None:
        uso = self.app.rotinas.sensores_necessarios()
        if ("app_aberto" in uso or "app_fechado" in uso) and self._hora_de("processos", 2):
            self._ver_processos()
        elif not ("app_aberto" in uso or "app_fechado" in uso):
            self._processos = None
        if "bateria_baixa" in uso and self._hora_de("bateria", 30):
            self._ver_bateria(uso["bateria_baixa"])
        if "pendrive" in uso and self._hora_de("pendrive", 3):
            self._ver_unidades()
        if "arquivo_novo" in uso and self._hora_de("pastas", 4):
            self._ver_pastas([p for p in (resolver_pasta(str(v)) for v in uso["arquivo_novo"]) if p])
        if "wifi" in uso and self._hora_de("wifi", 10):
            self._ver_wifi()
        if "voltar_ao_pc" in uso and self._hora_de("presenca", 2):
            self._ver_presenca(min(float(v or 5) for v in uso["voltar_ao_pc"]))

    # -- sensores ------------------------------------------------------------------------
    def _ver_processos(self) -> None:
        atuais = nomes_processos()
        anteriores, self._processos = self._processos, atuais
        if anteriores is None:  # primeira leitura: só memoriza
            return
        for nome in sorted(atuais - anteriores):
            self.app.rotinas.disparar("app_aberto", app=nome)
        for nome in sorted(anteriores - atuais):
            self.app.rotinas.disparar("app_fechado", app=nome)

    def _ver_bateria(self, limites: list) -> None:
        leitura = bateria()
        if leitura is None:
            return
        pct, carregando = leitura
        for limite in {int(v or 20) for v in limites}:
            abaixo = pct <= limite and not carregando
            if abaixo and not self._bateria_avisada.get(limite):
                self._bateria_avisada[limite] = True
                self.app.rotinas.disparar("bateria_baixa", pct=pct, carregando=carregando, bateria=pct)
            elif carregando or pct > limite + 3:
                self._bateria_avisada[limite] = False

    def _ver_unidades(self) -> None:
        atuais = unidades_removiveis()
        anteriores, self._unidades = self._unidades, atuais
        if anteriores is None:
            return
        for unidade in atuais.keys() - anteriores.keys():
            self.app.rotinas.disparar("pendrive", unidade=unidade, rotulo=atuais[unidade])

    def _ver_pastas(self, pastas: list[Path]) -> None:
        for pasta in pastas:
            try:
                atuais = {e.name: e.stat().st_size for e in os.scandir(pasta)
                          if e.is_file() and not e.name.startswith((".", "~$"))
                          and Path(e.name).suffix.lower() not in IGNORAR_EXTENSOES}
            except OSError:
                continue
            if pasta not in self._pastas:  # primeira leitura
                self._pastas[pasta] = atuais
                self._pendentes[pasta] = {}
                continue
            conhecidos = self._pastas[pasta]
            pendentes = self._pendentes[pasta]
            for nome, tamanho in atuais.items():
                if nome in conhecidos:
                    continue
                if pendentes.get(nome) == tamanho:  # tamanho parou de mudar: o download terminou
                    conhecidos[nome] = tamanho
                    pendentes.pop(nome)
                    self.app.rotinas.disparar("arquivo_novo", pasta=str(pasta), arquivo=str(pasta / nome))
                else:
                    pendentes[nome] = tamanho
            for nome in list(conhecidos):
                if nome not in atuais:
                    conhecidos.pop(nome)

    def _ver_wifi(self) -> None:
        atual = rede_wifi()
        anterior, self._rede = self._rede, atual
        if not self._rede_lida:
            self._rede_lida = True
            return
        if atual and atual != anterior:
            self.app.rotinas.disparar("wifi", rede=atual)

    def _ver_presenca(self, minutos: float) -> None:
        ocioso = segundos_ocioso()
        if ocioso is None:
            return
        if ocioso >= minutos * 60:
            if self._ausente_desde is None:
                self._ausente_desde = time.time() - ocioso
            if self.app.prefs.get("presenca_camera") and self._camera_viu_voce():
                self._voltou()
            return
        if self._ausente_desde is not None and ocioso < 5:
            self._voltou()

    def _camera_viu_voce(self) -> bool:
        """Enquanto você está fora, espia a câmera a cada 30 s procurando o seu rosto."""
        if time.monotonic() - self._ultima_camera < 30 or not self.app.rosto.cadastrado():
            return False
        self._ultima_camera = time.monotonic()
        try:
            return bool(self.app.rosto.verificar(timeout=1.5, exigir_piscada=False).ok)
        except Exception:  # noqa: BLE001
            return False

    def _voltou(self) -> None:
        if self._ausente_desde is None:
            return
        minutos = (time.time() - self._ausente_desde) / 60
        self._ausente_desde = None
        self.app.rotinas.disparar("voltar_ao_pc", ausente_min=round(minutos, 1))
