"""Sensores do traje: temperaturas, GPU, discos, rede, atualizações e bateria do PC (Windows).

Cada leitura é independente, tem tempo-limite e fica em cache: o relatório junta tudo em paralelo e nunca
segura a voz por muito tempo. As lentas (atualizações do Windows, relatório da bateria) rodam em segundo
plano e o relatório mostra o último valor conhecido (ou "verificando…").

Fontes:
- temperatura da CPU: LibreHardwareMonitor / OpenHardwareMonitor abertos (WMI ``root/LibreHardwareMonitor``,
  ``root/OpenHardwareMonitor``, classe ``Sensor``); sem eles, ``MSAcpi_ThermalZoneTemperature`` (``root/wmi``,
  décimos de Kelvin — nem todo PC expõe, e às vezes só como administrador);
- GPU: ``nvidia-smi``; sem ele, o uso pelos contadores "GPU Engine" e a temperatura pelo LibreHardwareMonitor;
- saúde dos discos: ``Get-PhysicalDisk``; atualizações: ``Microsoft.Update.Session`` (COM) e ``winget upgrade``;
- bateria: ``powercfg /batteryreport /xml`` (capacidade de projeto x carga total).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, TimeoutError as TempoEsgotado
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..habilidades import windows

log = logging.getLogger(__name__)

DICA_LHM = "indisponível — instale/abra o LibreHardwareMonitor (librehardwaremonitor.org)"
CACHE_ATUALIZACOES_S = 6 * 3600
CACHE_BATERIA_S = 24 * 3600
ALVO_PING = ("1.1.1.1", 443)

SCRIPT_TEMPERATURAS = r"""
$s = $null; $fonte = ''
foreach ($ns in 'root/LibreHardwareMonitor', 'root/OpenHardwareMonitor') {
  try { $s = Get-CimInstance -Namespace $ns -ClassName Sensor -Filter "SensorType='Temperature'" -ErrorAction Stop } catch { $s = $null }
  if ($s) { $fonte = ($ns -split '/')[1]; break }
}
$acpi = @()
if (-not $s) {
  try { $acpi = @(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop | ForEach-Object { $_.CurrentTemperature }) } catch { }
}
[pscustomobject]@{ fonte = $fonte; sensores = @($s | Select-Object Name, Identifier, Value); acpi = $acpi } | ConvertTo-Json -Depth 4 -Compress
"""
SCRIPT_DISCOS = ("Get-PhysicalDisk | Select-Object FriendlyName, MediaType, HealthStatus, OperationalStatus, Size | "
                 "ConvertTo-Json -Compress")
SCRIPT_ATUALIZACOES = ("(New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher()"
                       ".Search('IsInstalled=0 and IsHidden=0').Updates.Count")
SCRIPT_GPU_CONTADORES = ("$t = 0; (Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage' -ErrorAction "
                         "SilentlyContinue).CounterSamples | ForEach-Object { $t += $_.CookedValue }; [math]::Round($t, 1)")


# -- interpretação (independente do Windows, testável) -----------------------------------------------
def _lista(valor: Any) -> list:
    if valor is None:
        return []
    return valor if isinstance(valor, list) else [valor]


def _json(saida: str) -> Any:
    saida = (saida or "").strip()
    if not saida:
        return None
    try:
        return json.loads(saida)
    except json.JSONDecodeError:
        return None


def interpretar_temperaturas(saida: str) -> dict:
    """Saída do SCRIPT_TEMPERATURAS -> {"cpu": °C|None, "gpu": °C|None, "fonte": str, "erro": str}."""
    dados = _json(saida) or {}
    sensores = [s for s in _lista(dados.get("sensores")) if isinstance(s, dict) and s.get("Value") is not None]
    cpu = gpu = None
    if sensores:
        def ident(s):
            return str(s.get("Identifier") or "").lower()

        da_cpu = [s for s in sensores if "cpu" in ident(s)]
        preferidos = ("cpu package", "core (tctl/tdie)", "tctl/tdie", "tdie", "tctl", "package", "core average")
        escolhido = next((s for nome in preferidos for s in da_cpu if str(s.get("Name") or "").lower() == nome), None)
        if escolhido is not None:
            cpu = float(escolhido["Value"])
        elif da_cpu:
            cpu = max(float(s["Value"]) for s in da_cpu)
        da_gpu = [s for s in sensores if "gpu" in ident(s)]
        nucleo = next((s for s in da_gpu if str(s.get("Name") or "").lower() in ("gpu core", "gpu temperature")), None)
        if nucleo is not None:
            gpu = float(nucleo["Value"])
        elif da_gpu:
            gpu = max(float(s["Value"]) for s in da_gpu)
        fonte = "LibreHardwareMonitor" if "libre" in str(dados.get("fonte", "")).lower() else "OpenHardwareMonitor"
        return {"cpu": _arred(cpu), "gpu": _arred(gpu), "fonte": fonte, "erro": "" if cpu is not None else DICA_LHM}
    acpi = [float(v) for v in _lista(dados.get("acpi")) if isinstance(v, (int, float)) and v > 0]
    if acpi:
        celsius = max(v / 10 - 273.15 for v in acpi)
        if 5 < celsius < 130:  # alguns PCs devolvem lixo fixo (ex.: 27,8 °C ou 0)
            return {"cpu": _arred(celsius), "gpu": None, "fonte": "ACPI (zona térmica)", "erro": ""}
    return {"cpu": None, "gpu": None, "fonte": "", "erro": DICA_LHM}


def _arred(valor: float | None, casas: int = 0) -> float | None:
    if valor is None:
        return None
    return round(float(valor), casas) if casas else float(round(float(valor)))


def interpretar_nvidia_smi(saida: str) -> dict | None:
    """ "temperatura, uso, memória usada, memória total, nome" (uma linha por placa) -> a primeira placa."""
    for linha in (saida or "").splitlines():
        partes = [p.strip() for p in linha.split(",")]
        if len(partes) < 5:
            continue

        def numero(texto: str) -> float | None:
            try:
                return float(texto)
            except ValueError:
                return None  # "[N/A]"

        return {"temp": numero(partes[0]), "uso": numero(partes[1]), "vram_usada": numero(partes[2]),
                "vram_total": numero(partes[3]), "nome": ", ".join(partes[4:]), "fonte": "nvidia-smi"}
    return None


def interpretar_discos(saida: str) -> list[dict]:
    """Saída do Get-PhysicalDisk -> [{"nome", "tipo", "saude", "ok", "tamanho_gb"}]."""
    discos = []
    for d in _lista(_json(saida)):
        if not isinstance(d, dict):
            continue
        saude = str(d.get("HealthStatus") or "?")
        tipo = d.get("MediaType")
        tipo = {"3": "HDD", "4": "SSD", "0": "", "HDD": "HDD", "SSD": "SSD"}.get(str(tipo), str(tipo or ""))
        discos.append({"nome": str(d.get("FriendlyName") or "Disco"), "tipo": tipo,
                       "saude": {"Healthy": "saudável", "Warning": "atenção", "Unhealthy": "com defeito", "0": "saudável",
                                 "1": "atenção", "2": "com defeito"}.get(saude, saude.lower()),
                       "ok": saude in ("Healthy", "0"),
                       "tamanho_gb": round((d.get("Size") or 0) / 1e9) if isinstance(d.get("Size"), (int, float)) else None})
    return discos


_SSID = re.compile(r"^\s*SSID\s*:\s*(.+?)\s*$", re.M)


def interpretar_ssid(saida: str) -> str | None:
    """ "netsh wlan show interfaces" -> o nome da rede Wi-Fi (a linha "SSID", não "BSSID")."""
    m = _SSID.search(saida or "")
    return m.group(1) if m else None


def interpretar_winget(saida: str) -> int | None:
    """Conta as linhas da tabela do "winget upgrade" (depois da linha de traços)."""
    linhas = (saida or "").splitlines()
    inicio = next((i for i, l in enumerate(linhas) if re.fullmatch(r"\s*-{10,}\s*", l)), None)
    if inicio is None:
        return 0 if re.search(r"no installed package|nenhum pacote|no applicable|nenhuma atualiza", saida or "", re.I) else None
    total = 0
    for linha in linhas[inicio + 1:]:
        if not linha.strip():
            break
        if re.match(r"^\s*\d+\s+\S*\s*(upgrades?|atualiza)", linha, re.I):
            break
        total += 1
    return total


def interpretar_bateria(xml: str) -> dict | None:
    """Relatório XML do powercfg -> {"projetada_mwh", "atual_mwh", "saude_pct"}; None se não há bateria."""
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError:
        return None
    for elemento in raiz.iter():
        if elemento.tag.rsplit("}", 1)[-1] != "Battery":
            continue
        valores = {filho.tag.rsplit("}", 1)[-1]: (filho.text or "").strip() for filho in elemento}
        try:
            projetada = int(valores.get("DesignCapacity") or 0)
            atual = int(valores.get("FullChargeCapacity") or 0)
        except ValueError:
            continue
        if projetada <= 0:
            continue
        return {"projetada_mwh": projetada, "atual_mwh": atual, "saude_pct": round(100 * atual / projetada),
                "nome": valores.get("Id") or valores.get("Manufacturer") or "Bateria"}
    return None


# -- coleta --------------------------------------------------------------------------------------------
def _rodar(comando: list[str], timeout: float) -> str:
    """Roda um programa sem janela e devolve a saída (vazia se falhar)."""
    resultado = subprocess.run(comando, capture_output=True, timeout=timeout, creationflags=windows.SEM_JANELA)
    if resultado.returncode != 0:
        erro = resultado.stderr.decode("utf-8", "replace").strip().splitlines()
        raise OSError(erro[0] if erro else f"{Path(comando[0]).name} terminou com código {resultado.returncode}")
    return resultado.stdout.decode("utf-8", "replace")


def medir_ping(alvo: tuple[str, int] = ALVO_PING, timeout: float = 2.0) -> float | None:
    """Latência (ms) de uma conexão TCP: funciona em qualquer idioma do Windows e sem administrador."""
    inicio = time.perf_counter()
    try:
        with socket.create_connection(alvo, timeout=timeout):
            pass
    except OSError:
        return None
    return round((time.perf_counter() - inicio) * 1000)


class Sensores:
    """Leituras com cache. Os comandos externos passam por ``rodar``/``powershell`` (os testes trocam os dois)."""

    def __init__(self, pasta: Path, *, rodar: Callable[[list[str], float], str] | None = None,
                 powershell: Callable[[str, float], str] | None = None, ping: Callable[[], float | None] | None = None,
                 no_windows: bool | None = None) -> None:
        self.pasta = pasta
        self.rodar = rodar or _rodar
        self.powershell = powershell or (lambda script, timeout: windows.powershell(script, timeout=timeout))
        self.ping = ping or medir_ping
        self.no_windows = windows.WINDOWS if no_windows is None else no_windows
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._em_andamento: set[str] = set()
        self._nvidia = shutil.which("nvidia-smi") if self.no_windows else None

    # -- cache ----------------------------------------------------------------------------------------
    def _em_cache(self, chave: str, idade: float) -> Any:
        with self._lock:
            item = self._cache.get(chave)
        if item and time.monotonic() - item[0] < idade:
            return item[1]
        return None

    def _guardar(self, chave: str, valor: Any) -> Any:
        with self._lock:
            self._cache[chave] = (time.monotonic(), valor)
        return valor

    def ultimo(self, chave: str) -> Any:
        with self._lock:
            item = self._cache.get(chave)
        return item[1] if item else None

    def _em_fundo(self, chave: str, funcao: Callable[[], Any]) -> None:
        """Atualiza ``chave`` numa thread (uma por vez)."""
        with self._lock:
            if chave in self._em_andamento:
                return
            self._em_andamento.add(chave)

        def rodar():
            try:
                self._guardar(chave, funcao())
            except Exception as erro:  # noqa: BLE001 - a leitura lenta nunca derruba nada
                log.info("Leitura %s falhou: %s", chave, erro)
                self._guardar(chave, {"erro": str(erro)[:200]})
            finally:
                with self._lock:
                    self._em_andamento.discard(chave)

        threading.Thread(target=rodar, name=f"traje-{chave}", daemon=True).start()

    def verificando(self, chave: str) -> bool:
        with self._lock:
            return chave in self._em_andamento

    # -- leituras -------------------------------------------------------------------------------------
    def temperaturas(self, idade: float = 5.0) -> dict:
        """{"cpu", "gpu", "fonte", "erro"} (°C)."""
        if (valor := self._em_cache("temperaturas", idade)) is not None:
            return valor
        if not self.no_windows:
            return self._guardar("temperaturas", {"cpu": None, "gpu": None, "fonte": "", "erro": "só no Windows"})
        try:
            valor = interpretar_temperaturas(self.powershell(SCRIPT_TEMPERATURAS, 12))
        except (OSError, subprocess.TimeoutExpired, windows.NaoSuportado) as erro:
            valor = {"cpu": None, "gpu": None, "fonte": "", "erro": f"{DICA_LHM} ({erro})"}
        return self._guardar("temperaturas", valor)

    def gpu(self, idade: float = 2.0) -> dict:
        """{"nome", "temp", "uso", "vram_usada", "vram_total", "fonte", "erro"}."""
        if (valor := self._em_cache("gpu", idade)) is not None:
            return valor
        vazio = {"nome": "", "temp": None, "uso": None, "vram_usada": None, "vram_total": None, "fonte": "", "erro": ""}
        if not self.no_windows:
            return self._guardar("gpu", {**vazio, "erro": "só no Windows"})
        if self._nvidia:
            try:
                saida = self.rodar([self._nvidia, "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,name",
                                    "--format=csv,noheader,nounits"], 5)
                if (lido := interpretar_nvidia_smi(saida)) is not None:
                    return self._guardar("gpu", {**vazio, **lido})
            except (OSError, subprocess.TimeoutExpired) as erro:
                log.info("nvidia-smi falhou: %s", erro)
        valor = dict(vazio, fonte="contadores do Windows")
        try:
            valor["uso"] = min(100.0, float(self.powershell(SCRIPT_GPU_CONTADORES, 12).strip().replace(",", ".") or 0))
        except (OSError, ValueError, subprocess.TimeoutExpired, windows.NaoSuportado) as erro:
            valor["erro"] = f"uso da GPU indisponível ({erro})"
        valor["temp"] = self.temperaturas(idade=30).get("gpu")
        if valor["temp"] is None:
            valor["erro"] = (valor["erro"] + "; " if valor["erro"] else "") + "temperatura: abra o LibreHardwareMonitor"
        return self._guardar("gpu", valor)

    def uso(self) -> dict:
        """CPU e RAM agora (psutil, instantâneo)."""
        import psutil

        memoria = psutil.virtual_memory()
        return {"cpu": psutil.cpu_percent(interval=None), "ram": round(memoria.percent),
                "ram_usada": round(memoria.used / 2**30, 1), "ram_total": round(memoria.total / 2**30, 1)}

    def espaco(self) -> list[dict]:
        """Uso das unidades fixas: [{"unidade", "pct", "livre_gb", "total_gb", "sistema"}]."""
        import os

        import psutil

        sistema = (os.environ.get("SystemDrive", "C:") + "\\").upper() if self.no_windows else "/"
        unidades = []
        try:
            particoes = psutil.disk_partitions(all=False)
        except OSError:
            particoes = []
        vistos = set()
        for p in particoes:
            if "cdrom" in p.opts or not p.fstype or p.mountpoint in vistos:
                continue
            if not self.no_windows and p.mountpoint != "/":
                continue
            vistos.add(p.mountpoint)
            try:
                u = psutil.disk_usage(p.mountpoint)
            except OSError:
                continue
            unidades.append({"unidade": p.mountpoint.rstrip("\\") or p.mountpoint, "pct": round(u.percent),
                             "livre_gb": round(u.free / 2**30), "total_gb": round(u.total / 2**30),
                             "sistema": p.mountpoint.upper() == sistema})
        if not unidades:
            try:
                u = psutil.disk_usage(sistema)
                unidades.append({"unidade": sistema.rstrip("\\"), "pct": round(u.percent), "livre_gb": round(u.free / 2**30),
                                 "total_gb": round(u.total / 2**30), "sistema": True})
            except OSError:
                pass
        return sorted(unidades, key=lambda u: (not u["sistema"], u["unidade"]))

    def saude_discos(self, idade: float = 600) -> dict:
        if (valor := self._em_cache("saude_discos", idade)) is not None:
            return valor
        if not self.no_windows:
            return self._guardar("saude_discos", {"discos": [], "erro": "só no Windows"})
        try:
            valor = {"discos": interpretar_discos(self.powershell(SCRIPT_DISCOS, 20)), "erro": ""}
        except (OSError, subprocess.TimeoutExpired, windows.NaoSuportado) as erro:
            valor = {"discos": [], "erro": str(erro)[:200]}
        return self._guardar("saude_discos", valor)

    def rede(self, idade: float = 3.0) -> dict:
        if (valor := self._em_cache("rede", idade)) is not None:
            return valor
        ssid = None
        if self.no_windows:
            try:
                ssid = interpretar_ssid(self.rodar(["netsh", "wlan", "show", "interfaces"], 5))
            except (OSError, subprocess.TimeoutExpired):
                ssid = None
        ping = self.ping()
        return self._guardar("rede", {"ping_ms": ping, "ssid": ssid, "erro": "" if ping is not None else "sem internet"})

    def latencia(self, idade: float = 3.0) -> float | None:
        """Só o ping (o overlay pede toda hora; o SSID não precisa)."""
        if (valor := self._em_cache("ping", idade)) is not None:
            return valor.get("ms")
        return self._guardar("ping", {"ms": self.ping()})["ms"]

    # -- leituras lentas (em segundo plano) -------------------------------------------------------------
    def _ler_atualizacoes(self) -> dict:
        windows_n = None
        erro = ""
        try:
            windows_n = int(self.powershell(SCRIPT_ATUALIZACOES, 180).strip() or 0)
        except (OSError, ValueError, subprocess.TimeoutExpired, windows.NaoSuportado) as e:
            erro = f"Windows Update: {e}"
        winget_n = None
        winget = shutil.which("winget")
        if winget:
            try:
                winget_n = interpretar_winget(self.rodar([winget, "upgrade", "--accept-source-agreements",
                                                          "--disable-interactivity"], 90))
            except (OSError, subprocess.TimeoutExpired) as e:
                log.info("winget upgrade falhou: %s", e)
        return {"windows": windows_n, "winget": winget_n, "verificado": datetime.now().isoformat(timespec="seconds"),
                "erro": erro}

    def atualizacoes(self) -> dict:
        """Atualizações pendentes (cache de 6 h). A primeira leitura demora: devolve "verificando"."""
        if not self.no_windows:
            return {"windows": None, "winget": None, "verificado": None, "verificando": False, "erro": "só no Windows"}
        valor = self._em_cache("atualizacoes", CACHE_ATUALIZACOES_S)
        if valor is None:
            self._em_fundo("atualizacoes", self._ler_atualizacoes)
            valor = self.ultimo("atualizacoes") or {"windows": None, "winget": None, "verificado": None, "erro": ""}
        return {**valor, "verificando": self.verificando("atualizacoes")}

    def _ler_bateria(self) -> dict:
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "bateria.xml"
            self.rodar(["powercfg", "/batteryreport", "/xml", "/output", str(arquivo)], 30)
            texto = arquivo.read_text(encoding="utf-8", errors="replace") if arquivo.exists() else ""
        lido = interpretar_bateria(texto)
        return {"presente": lido is not None, **(lido or {}), "erro": ""}

    def bateria(self) -> dict:
        """Saúde da bateria (cache de 1 dia). Em desktop: {"presente": False}."""
        if not self.no_windows:
            return {"presente": False, "erro": "só no Windows", "verificando": False}
        valor = self._em_cache("bateria", CACHE_BATERIA_S)
        if valor is None:
            self._em_fundo("bateria", self._ler_bateria)
            valor = self.ultimo("bateria") or {"presente": None, "erro": ""}
        return {**valor, "verificando": self.verificando("bateria")}

    def aquecer(self) -> None:
        """Começa as leituras lentas cedo (ao iniciar), para o primeiro relatório já ter os números."""
        self.atualizacoes()
        self.bateria()

    # -- tudo junto ----------------------------------------------------------------------------------
    def coletar(self, timeout: float = 8.0) -> dict:
        """Todas as leituras em paralelo; o que passar do tempo-limite sai como "sem resposta"."""
        tarefas = {"temperaturas": self.temperaturas, "gpu": self.gpu, "uso": self.uso, "espaco": self.espaco,
                   "saude_discos": self.saude_discos, "rede": self.rede, "atualizacoes": self.atualizacoes,
                   "bateria": self.bateria}
        resultado: dict[str, Any] = {}
        executor = ThreadPoolExecutor(max_workers=len(tarefas), thread_name_prefix="traje-coleta")
        futuros = {nome: executor.submit(funcao) for nome, funcao in tarefas.items()}
        limite = time.monotonic() + timeout
        for nome, futuro in futuros.items():
            try:
                resultado[nome] = futuro.result(timeout=max(0.05, limite - time.monotonic()))
            except TempoEsgotado:
                resultado[nome] = {"erro": "sem resposta (demorou demais)"}
            except Exception as erro:  # noqa: BLE001
                log.info("Leitura %s falhou: %s", nome, erro)
                resultado[nome] = {"erro": str(erro)[:200]}
        executor.shutdown(wait=False)
        return resultado
