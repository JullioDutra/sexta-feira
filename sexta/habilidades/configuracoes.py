"""Configurações do Windows por voz: brilho, Wi-Fi, Bluetooth, modo escuro, plano de energia,
não perturbe e dispositivo de saída de áudio.

Cada função levanta ``ErroConfiguracao`` com uma mensagem pronta para ser falada.
"""

from __future__ import annotations

import logging
import re

from ..util.texto import normalizar
from . import windows

log = logging.getLogger(__name__)


class ErroConfiguracao(Exception):
    pass


def _ps(comando: str, timeout: float = 20) -> str:
    try:
        return windows.powershell(comando, timeout=timeout)
    except windows.NaoSuportado:
        raise
    except Exception as erro:  # noqa: BLE001
        raise ErroConfiguracao(str(erro)) from erro


# -- brilho ------------------------------------------------------------------------

def brilho_atual() -> int:
    saida = _ps("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop)"
                ".CurrentBrightness | Select-Object -First 1")
    if not saida.strip().isdigit():
        raise ErroConfiguracao("Seu monitor não informa o brilho ao Windows.")
    return int(saida.strip())


def definir_brilho(valor: int) -> int:
    valor = max(0, min(100, int(valor)))
    try:
        _ps("Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop | "
            f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={valor}}} | Out-Null")
    except ErroConfiguracao:
        raise ErroConfiguracao("Seu monitor não aceita ajuste de brilho pelo Windows. Isso é comum em PCs de mesa: "
                               "use os botões do monitor.") from None
    return valor


def mudar_brilho(delta: int) -> int:
    return definir_brilho(brilho_atual() + delta)


# -- rádios (Wi-Fi e Bluetooth) ----------------------------------------------------------

_RADIOS = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and
  $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
Function Await($op, $tipo) { $t = $asTask.MakeGenericMethod($tipo).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$r = $radios | Where-Object { $_.Kind -eq '__TIPO__' } | Select-Object -First 1
if (-not $r) { Write-Output 'SEM_RADIO'; exit }
if ('__ESTADO__' -ne '') {
  $res = Await ($r.SetStateAsync('__ESTADO__')) ([Windows.Devices.Radios.RadioAccessStatus])
  Write-Output $res
} else { Write-Output $r.State }
"""


def radio(tipo: str, ligar: bool | None) -> str:
    """tipo: "wifi" ou "bluetooth". ``ligar=None`` só consulta. Devolve "On"/"Off"/"Allowed"..."""
    kind = {"wifi": "WiFi", "bluetooth": "Bluetooth"}[tipo]
    estado = "" if ligar is None else ("On" if ligar else "Off")
    saida = _ps(_RADIOS.replace("__TIPO__", kind).replace("__ESTADO__", estado), timeout=25).strip()
    if "SEM_RADIO" in saida:
        nome = "Wi-Fi" if tipo == "wifi" else "Bluetooth"
        raise ErroConfiguracao(f"Este computador não tem {nome} (ou o adaptador está desativado no Gerenciador de Dispositivos).")
    if ligar is not None and saida and saida != "Allowed":
        raise ErroConfiguracao(f"O Windows não deixou mudar o rádio ({saida}).")
    return saida


# -- modo escuro --------------------------------------------------------------------------

def modo_escuro(ligar: bool | None) -> bool:
    """Liga/desliga o tema escuro do Windows e dos apps. ``None`` só consulta. Devolve se está escuro."""
    windows._exigir_windows()
    import winreg

    chave = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chave, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
        if ligar is None:
            valor, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return valor == 0
        claro = 0 if ligar else 1
        winreg.SetValueEx(k, "AppsUseLightTheme", 0, winreg.REG_DWORD, claro)
        winreg.SetValueEx(k, "SystemUsesLightTheme", 0, winreg.REG_DWORD, claro)
    _avisar_mudanca("ImmersiveColorSet")
    return bool(ligar)


def _avisar_mudanca(area: str) -> None:
    import ctypes

    resultado = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, area, 0x0002, 200, ctypes.byref(resultado))


# -- plano de energia ---------------------------------------------------------------------

PLANOS = {
    "economia": "a1841308-3541-4fab-bc81-f71556f20b4a",
    "equilibrado": "381b4222-f694-41f0-9685-ff5bb260df2e",
    "alto desempenho": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "desempenho maximo": "e9a42b02-d5df-448d-aa00-03f14749eb61",
}
# Windows 11 com "Modo de energia" (notebooks modernos só têm o plano Equilibrado)
SOBREPOSICOES = {
    "economia": "961cc777-2547-4f9d-8174-7d86181b8a7a",
    "equilibrado": "00000000-0000-0000-0000-000000000000",
    "alto desempenho": "ded574b5-45a0-4f42-8737-46345c09c238",
    "desempenho maximo": "ded574b5-45a0-4f42-8737-46345c09c238",
}
APELIDOS_PLANO = {
    "economia": "economia", "economia de energia": "economia", "bateria": "economia", "eco": "economia",
    "equilibrado": "equilibrado", "balanceado": "equilibrado", "normal": "equilibrado", "padrao": "equilibrado",
    "alto desempenho": "alto desempenho", "desempenho": "alto desempenho", "performance": "alto desempenho",
    "desempenho maximo": "desempenho maximo", "maximo desempenho": "desempenho maximo", "maximo": "desempenho maximo",
    "jogo": "desempenho maximo", "turbo": "desempenho maximo",
}


def _powercfg(*args: str) -> str:
    import subprocess

    r = subprocess.run(["powercfg", *args], capture_output=True, creationflags=windows.SEM_JANELA, timeout=15)
    codificacao = "oem" if windows.WINDOWS else "utf-8"  # programas de console usam a página OEM (cp850)
    texto = r.stdout.decode(codificacao, "replace")
    if r.returncode != 0:
        raise ErroConfiguracao((r.stderr.decode(codificacao, "replace") or texto).strip() or "powercfg falhou")
    return texto


def planos_instalados() -> dict[str, tuple[str, bool]]:
    """{guid: (nome, ativo)}"""
    planos = {}
    for linha in _powercfg("/list").splitlines():
        m = re.search(r"([0-9a-f-]{36})\s+\((.+?)\)\s*(\*)?", linha, re.I)
        if m:
            planos[m.group(1).lower()] = (m.group(2), bool(m.group(3)))
    return planos


def definir_plano(pedido: str) -> str:
    windows._exigir_windows()
    chave = APELIDOS_PLANO.get(normalizar(pedido))
    planos = planos_instalados()
    if chave is None:  # nome de um plano personalizado
        alvo = normalizar(pedido)
        for guid, (nome, _) in planos.items():
            if alvo and alvo in normalizar(nome):
                _powercfg("/setactive", guid)
                return nome
        raise ErroConfiguracao(f"Não conheço o plano '{pedido}'. Opções: economia, equilibrado, alto desempenho, desempenho máximo.")
    guid = PLANOS[chave]
    if guid not in planos and chave == "desempenho maximo":
        try:  # o plano "Desempenho Máximo" vem escondido: cria uma cópia dele
            saida = _powercfg("-duplicatescheme", guid)
            novo = re.search(r"[0-9a-f-]{36}", saida, re.I)
            guid = novo.group(0).lower() if novo else guid
        except ErroConfiguracao:
            guid = PLANOS["alto desempenho"]
    if guid not in planos_instalados():
        # sem o plano clássico: usa o "Modo de energia" do Windows 11
        _powercfg("/setactive", PLANOS["equilibrado"])
        _powercfg("/overlaysetactive", SOBREPOSICOES[chave])
        return chave
    _powercfg("/setactive", guid)
    return planos_instalados().get(guid, (chave, True))[0]


# -- não perturbe ------------------------------------------------------------------------

def nao_perturbe(ligar: bool) -> None:
    """Silencia as notificações do Windows (equivale ao "Não incomodar")."""
    windows._exigir_windows()
    import winreg

    chave = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, chave, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "NOC_GLOBAL_SETTING_TOASTS_ENABLED", 0, winreg.REG_DWORD, 0 if ligar else 1)
    _avisar_mudanca("Notifications")


# -- saída de áudio ----------------------------------------------------------------------

def dispositivos_saida() -> list[dict]:
    """[{"id", "nome", "padrao"}] dos alto-falantes/fones ativos."""
    windows._exigir_windows()
    import comtypes
    from pycaw.pycaw import AudioUtilities

    try:
        comtypes.CoInitialize()
    except OSError:
        pass
    padrao = ""
    try:
        alto_falantes = AudioUtilities.GetSpeakers()
        # pycaw novo devolve um AudioDevice (com .id); o antigo, a interface COM (com GetId())
        padrao = getattr(alto_falantes, "id", None) or alto_falantes.GetId()
    except Exception:  # noqa: BLE001
        pass
    saida = []
    for d in AudioUtilities.GetAllDevices():
        estado = getattr(d.state, "value", d.state)
        if d.id and d.id.startswith("{0.0.0.") and estado == 1 and d.FriendlyName:
            saida.append({"id": d.id, "nome": d.FriendlyName, "padrao": d.id == padrao})
    return saida


def definir_saida(pedido: str) -> str:
    from rapidfuzz import fuzz, process

    dispositivos = dispositivos_saida()
    if not dispositivos:
        raise ErroConfiguracao("Não encontrei dispositivos de áudio ativos.")
    alvo = normalizar(pedido)
    apelidos = {"fone": "fone headphone headset", "fones": "fone headphone headset", "caixa": "alto falante speaker",
                "caixas": "alto falante speaker", "monitor": "monitor display hdmi", "tv": "tv hdmi"}
    consulta = apelidos.get(alvo, alvo)
    nomes = [normalizar(d["nome"]) for d in dispositivos]
    achado = process.extractOne(consulta, nomes, scorer=fuzz.token_set_ratio, score_cutoff=55)
    if not achado:
        opcoes = ", ".join(d["nome"] for d in dispositivos)
        raise ErroConfiguracao(f"Não achei '{pedido}'. Saídas disponíveis: {opcoes}.")
    dispositivo = dispositivos[achado[2]]
    _politica().definir_padrao(dispositivo["id"])
    return dispositivo["nome"]


def _politica():
    """IPolicyConfig: a interface (não documentada, estável desde o Windows 7) que troca o dispositivo padrão."""
    from ctypes import c_int, c_void_p, c_wchar_p

    import comtypes
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    def lugar(nome: str):  # métodos que não usamos: só ocupam a posição certa na tabela virtual
        return COMMETHOD([], HRESULT, nome, (["in"], c_void_p), (["in"], c_void_p))

    class IPolicyConfig(IUnknown):
        _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
        _methods_ = [
            lugar("GetMixFormat"), lugar("GetDeviceFormat"), lugar("ResetDeviceFormat"), lugar("SetDeviceFormat"),
            lugar("GetProcessingPeriod"), lugar("SetProcessingPeriod"), lugar("GetShareMode"), lugar("SetShareMode"),
            lugar("GetPropertyValue"), lugar("SetPropertyValue"),
            COMMETHOD([], HRESULT, "SetDefaultEndpoint", (["in"], c_wchar_p, "id"), (["in"], c_int, "papel")),
            lugar("SetEndpointVisibility"),
        ]

    class Politica:
        def __init__(self) -> None:
            self.com = comtypes.CoCreateInstance(GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}"), IPolicyConfig,
                                                 comtypes.CLSCTX_ALL)

        def definir_padrao(self, id_: str) -> None:
            for papel in (0, 1, 2):  # console, multimídia, comunicações
                self.com.SetDefaultEndpoint(id_, papel)

    return Politica()
