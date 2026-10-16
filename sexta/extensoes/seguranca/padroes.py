"""Padrões que a análise estática procura: textos perigosos (em scripts e dentro de programas),
strings interessantes (URLs, IPs, caminhos, chaves de registro) e capacidades pelas funções importadas.

Cada achado vira um ``Motivo``: o que foi visto em linguagem simples, um peso para o risco e as
evidências (o trecho exato). Os pesos são heurísticos: muitos programas legítimos usam as mesmas
funções, por isso o veredito sempre fala em "indícios", nunca em certeza.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from dataclasses import dataclass, field

MAX_EVIDENCIAS = 6
MAX_STRINGS = 25
MIN_STRING = 5


@dataclass
class Motivo:
    id: str
    texto: str             # em linguagem simples ("baixa algo da internet e executa")
    peso: int              # positivo aumenta o risco; negativo (ex.: assinatura válida) diminui
    evidencias: list[str] = field(default_factory=list)
    tecnica: str = ""      # etiqueta curta para a memória ("download_execucao", "injecao"...)

    def como_dict(self) -> dict:
        return {"id": self.id, "texto": self.texto, "peso": self.peso, "evidencias": self.evidencias[:MAX_EVIDENCIAS],
                "tecnica": self.tecnica}


# -- textos perigosos ------------------------------------------------------------------------------------
_I = re.I
DOWNLOAD = re.compile(r"Invoke-WebRequest|\biwr\b|\bwget(?:\.exe)?\s|\bcurl(?:\.exe)?\s|Net\.WebClient|DownloadString|"
                      r"DownloadFile|DownloadData|Start-BitsTransfer|bitsadmin(?:\.exe)?\s+/transfer|"
                      r"certutil(?:\.exe)?\s+[^\n]*-urlcache|MSXML2\.(?:Server)?XMLHTTP|WinHttp\.WinHttpRequest|"
                      r"URLDownloadToFile|Invoke-RestMethod|\birm\s+https?:", _I)
EXECUCAO = re.compile(r"Invoke-Expression|\biex\b|Start-Process|ShellExecute|WScript\.Shell|\.Run\s*\(|\bExec\s*\(|"
                      r"\bcmd(?:\.exe)?\s+/[ck]\b|Shell\.Application|ADODB\.Stream|\brundll32\b|\bregsvr32\b|\bmshta\b|"
                      r"child_process|\|\s*(?:powershell|pwsh|iex)\b|&\s*\$\w+", _I)
POWERSHELL_CODIFICADO = re.compile(r"(?:powershell|pwsh)(?:\.exe)?[^\n]{0,80}?\s-(?:e|ec|en|enc|enco|encodedcommand)\s+"
                                   r"([A-Za-z0-9+/=]{16,})", _I)
BASE64_LONGO = re.compile(r"[A-Za-z0-9+/]{300,}={0,2}")

# (id, regex, peso, texto, técnica) — o peso vale para scripts; dentro de programas alguns pesam menos (veja abaixo)
PADROES: list[tuple[str, re.Pattern, int, str, str]] = [
    ("defender", re.compile(r"Set-MpPreference[^\n]*-Disable\w+|DisableRealtimeMonitoring|DisableAntiSpyware|"
                            r"Add-MpPreference[^\n]*-Exclusion(?:Path|Process|Extension)|"
                            r"\bsc(?:\.exe)?\s+(?:stop|config|delete)\s+WinDefend|Stop-Service[^\n]*WinDefend|"
                            r"netsh\s+(?:advfirewall\s+set\s+\w+\s+state\s+off|firewall\s+set\s+opmode\s+(?:mode=)?disable)|"
                            r"Set-NetFirewallProfile[^\n]*-Enabled\s+\$?False", _I),
     4, "tenta desativar o antivírus (Defender) ou o firewall, ou criar exceções neles", "desativar_defesas"),
    ("amsi", re.compile(r"AmsiUtils|amsiInitFailed|AmsiScanBuffer|amsiContext", _I),
     5, "mexe na proteção de scripts do Windows (AMSI), algo que quase só malware faz", "desativar_defesas"),
    ("copias_sombra", re.compile(r"vssadmin(?:\.exe)?\s+delete\s+shadows|wmic(?:\.exe)?\s+shadowcopy\s+delete|"
                                 r"bcdedit[^\n]*recoveryenabled\s+no|wbadmin(?:\.exe)?\s+delete\s+catalog|"
                                 r"Win32_ShadowCopy[^\n]*Delete", _I),
     5, "apaga as cópias de segurança do Windows (comportamento típico de ransomware)", "ransomware"),
    ("persistencia", re.compile(r"CurrentVersion\\+Run(?:Once)?\b|schtasks(?:\.exe)?\s+/create|Register-ScheduledTask|"
                                r"New-ScheduledTask|Start Menu\\+Programs\\+Startup|shell:startup|New-Service\b|"
                                r"\bsc(?:\.exe)?\s+create\b", _I),
     2, "se instala para iniciar junto com o Windows", "persistencia"),
    ("credenciais", re.compile(r"\\Login Data\b|\\Local State\b|\\Network\\Cookies|wallet\.dat|logins\.json|key4\.db|"
                               r"CryptUnprotectData|ProtectedData\]::Unprotect", _I),
     3, "lê senhas, cookies ou carteiras salvos no navegador", "roubo_credenciais"),
    ("lolbin", re.compile(r"mshta(?:\.exe)?\s+(?:https?:|javascript:|vbscript:)|regsvr32[^\n]*/i:\s*https?:|"
                          r"rundll32(?:\.exe)?\s+javascript:|certutil(?:\.exe)?[^\n]*-decode", _I),
     3, "usa programas do próprio Windows de um jeito comum em ataques", "lolbin"),
    ("conexao_reversa", re.compile(r"Net\.Sockets\.TCPClient[^\n]{0,300}GetStream", _I),
     3, "abre uma conexão de rede que recebe comandos (controle remoto)", "controle_remoto"),
    ("usuario_admin", re.compile(r"net(?:\.exe)?\s+user\s+\S+\s+\S+\s+/add|"
                                 r"net(?:\.exe)?\s+localgroup\s+administra\w*\s+\S+\s+/add", _I),
     3, "cria um usuário ou o coloca como administrador", "privilegios"),
    ("apagar_rastros", re.compile(r"wevtutil(?:\.exe)?\s+cl\b|Clear-EventLog|Remove-EventLog", _I),
     2, "apaga os registros de eventos do Windows", "apagar_rastros"),
    ("uac", re.compile(r"EnableLUA[^\n]{0,40}\b0\b|ConsentPromptBehaviorAdmin[^\n]{0,40}\b0\b", _I),
     2, "desliga a confirmação de administrador (UAC)", "desativar_defesas"),
    ("oculto", re.compile(r"\s-w(?:indowstyle)?\s+h(?:idden)?\b|-WindowStyle\s+Hidden|-ExecutionPolicy\s+Bypass|"
                          r"\s-ep\s+bypass\b|\s-exec\s+bypass\b|\.Run\s*\([^,\n]+,\s*0\b|CreateNoWindow\s*=\s*\$?true", _I),
     1, "roda escondido, sem janela, ou passando por cima da política de scripts", "execucao_oculta"),
]
# dentro de programas, estes textos aparecem também em softwares legítimos (instaladores, navegadores)
PESO_EM_PROGRAMA = {"persistencia": 1, "credenciais": 1, "oculto": 0}

OFUSCACAO = [
    (re.compile(r"\[char\]\s*\d+", _I), 10, "[char]"),
    (re.compile(r"String\.fromCharCode", _I), 5, "String.fromCharCode"),
    (re.compile(r"\bChrW?\s*\(\s*\d+\s*\)", _I), 10, "Chr(...)"),
    (re.compile(r"\w`\w+`\w"), 3, "acentos graves no meio de comandos (I`nv`oke)"),
    (re.compile(r"\beval\s*\(\s*(?:unescape|atob|function\s*\(p,a,c,k,e)", _I), 1, "eval de texto embaralhado"),
    (re.compile(r"-join\s*\(?\s*\[char", _I), 2, "-join de caracteres"),
]

EXTENSOES_SCRIPT = {".ps1": "PowerShell", ".psm1": "PowerShell", ".psd1": "PowerShell", ".bat": "lote do Windows (.bat)",
                    ".cmd": "lote do Windows (.cmd)", ".js": "JavaScript", ".jse": "JavaScript codificado",
                    ".vbs": "VBScript", ".vbe": "VBScript codificado", ".wsf": "Windows Script", ".hta": "aplicativo HTML (.hta)",
                    ".py": "Python", ".sh": "shell", ".reg": "arquivo de registro (.reg)"}


def _contexto(texto: str, inicio: int, fim: int, folga: int = 50) -> str:
    a, b = max(0, inicio - folga), min(len(texto), fim + folga)
    trecho = texto[a:b].replace("\r", " ").replace("\n", " ⏎ ")
    trecho = re.sub(r"\s{2,}", " ", trecho).strip()
    return ("…" if a else "") + trecho + ("…" if b < len(texto) else "")


def _linha(texto: str, pos: int) -> int:
    return texto.count("\n", 0, pos) + 1


def _evidencias(regex: re.Pattern, texto: str, script: bool, limite: int = MAX_EVIDENCIAS) -> list[str]:
    achados = []
    for m in regex.finditer(texto):
        prefixo = f"linha {_linha(texto, m.start())}: " if script else ""
        achados.append(prefixo + _contexto(texto, m.start(), m.end()))
        if len(achados) >= limite:
            break
    return achados


def decodificar_powershell(blob: str) -> str | None:
    """O texto de um ``powershell -enc <base64>`` (UTF-16LE). ``None`` se não for base64 válido."""
    try:
        bruto = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=False)
    except (binascii.Error, ValueError):
        return None
    for codificacao in ("utf-16-le", "utf-8"):
        try:
            texto = bruto.decode(codificacao)
        except UnicodeDecodeError:
            continue
        if texto and sum(c.isprintable() or c in "\r\n\t" for c in texto) / len(texto) > 0.9:
            return texto
    return None


def analisar_texto(texto: str, *, script: bool = True, profundidade: int = 0) -> list[Motivo]:
    """Procura padrões perigosos num script (ou nas strings de um programa, com ``script=False``)."""
    motivos: list[Motivo] = []
    baixa = _evidencias(DOWNLOAD, texto, script)
    executa = _evidencias(EXECUCAO, texto, script)
    if baixa and executa:
        motivos.append(Motivo("download_execucao", "baixa algo da internet e executa", 4 if script else 2,
                              list(dict.fromkeys(baixa[:3] + executa[:3])), "download_execucao"))
    elif baixa:
        motivos.append(Motivo("download", "baixa arquivos ou dados da internet", 1 if script else 0, baixa, "rede"))

    for id_, regex, peso, descricao, tecnica in PADROES:
        achados = _evidencias(regex, texto, script)
        if achados:
            motivos.append(Motivo(id_, descricao, peso if script else PESO_EM_PROGRAMA.get(id_, peso), achados, tecnica))

    codificados = list(POWERSHELL_CODIFICADO.finditer(texto))
    if codificados:
        evidencias = []
        for m in codificados[:3]:
            decodificado = decodificar_powershell(m.group(1))
            evidencia = _contexto(texto, m.start(), min(m.end(), m.start() + 120))
            if decodificado:
                evidencia += f" → decodificado: {decodificado[:300]}"
                if profundidade == 0:  # o comando escondido também é analisado (um nível só)
                    for interno in analisar_texto(decodificado, script=True, profundidade=1):
                        interno.evidencias = [f"(dentro do base64) {e}" for e in interno.evidencias]
                        motivos.append(interno)
            evidencias.append(evidencia)
        motivos.append(Motivo("powershell_base64", "esconde um comando do PowerShell em base64", 3, evidencias, "ofuscacao"))
    elif script and re.search(r"FromBase64String|atob\s*\(|base64\s+-d", texto, _I):
        motivos.append(Motivo("base64", "decodifica dados em base64 durante a execução", 1,
                              _evidencias(re.compile(r"FromBase64String|atob\s*\(|base64\s+-d", _I), texto, script),
                              "ofuscacao"))
    if script and (blocos := BASE64_LONGO.findall(texto)):
        motivos.append(Motivo("bloco_codificado", "tem um bloco grande de dados codificados (pode esconder outro programa)",
                              1, [f"{len(b)} caracteres: {b[:60]}…" for b in blocos[:3]], "ofuscacao"))

    if script:
        sinais = []
        for regex, minimo, nome in OFUSCACAO:
            n = len(regex.findall(texto))
            if n >= minimo:
                sinais.append(f"{n}× {nome}")
        if sinais:
            motivos.append(Motivo("ofuscacao", "o texto está embaralhado para esconder o que faz", 2, sinais, "ofuscacao"))
    encontrados = {m.id for m in motivos}
    if script and "download_execucao" in encontrados and encontrados & {"oculto", "ofuscacao", "powershell_base64",
                                                                        "bloco_codificado"}:
        motivos.append(Motivo("download_escondido", "e faz isso de forma escondida", 1, [], "download_execucao"))
    return _juntar(motivos)


def _juntar(motivos: list[Motivo]) -> list[Motivo]:
    """Um motivo por id (o de dentro do base64 junta as evidências ao de fora, com o maior peso)."""
    por_id: dict[str, Motivo] = {}
    for m in motivos:
        if m.id in por_id:
            atual = por_id[m.id]
            atual.peso = max(atual.peso, m.peso)
            atual.evidencias += [e for e in m.evidencias if e not in atual.evidencias]
        else:
            por_id[m.id] = m
    return list(por_id.values())


# -- strings ---------------------------------------------------------------------------------------------
_ASCII = re.compile(rb"[\x20-\x7e]{%d,}" % MIN_STRING)
_UTF16 = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % MIN_STRING)
URL = re.compile(r"\b(?:https?|ftp)://[^\s\"'<>`{}|\\^]{4,200}", _I)
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
CAMINHO = re.compile(r"(?:\b[A-Za-z]:\\|%[A-Za-z]+%\\|\\\\[\w.$-]+\\)[^\s\"'<>|*?]{2,200}")
REGISTRO = re.compile(r"\b(?:HKEY_(?:LOCAL_MACHINE|CURRENT_USER|CLASSES_ROOT|USERS)|HKLM|HKCU|HKCR)(?::)?\\[^\s\"'<>|]{3,200}|"
                      r"\bSOFTWARE\\(?:Microsoft|Wow6432Node|Policies|Classes)\\[^\s\"'<>|]{3,200}", _I)
# URLs que aparecem em quase todo programa assinado (certificados, esquemas XML) não dizem nada
URLS_COMUNS = re.compile(r"^https?://(?:[\w.-]*\.)?(?:digicert|verisign|symcb|symcd|thawte|globalsign|sectigo|"
                         r"comodoca|usertrust|entrust|godaddy|microsoft\.com/(?:pki|pkiops)|crl\.|ocsp\.|"
                         r"schemas\.(?:microsoft|openxmlformats)\.|www\.w3\.org|ns\.adobe\.com|purl\.org)", _I)


def extrair_strings(dados: bytes, limite: int = 200_000) -> list[str]:
    """Textos legíveis (ASCII e UTF-16) dentro de um arquivo binário, como o ``strings`` do Linux."""
    achadas = [m.group().decode("ascii") for m in _ASCII.finditer(dados)]
    achadas += [m.group().decode("utf-16-le") for m in _UTF16.finditer(dados)]
    return achadas[:limite]


def _ip_interessante(texto: str) -> bool:
    try:
        ip = ipaddress.ip_address(texto)
    except ValueError:
        return False
    if ip.is_unspecified or ip.is_loopback or ip.is_multicast or ip.is_reserved:
        return False
    partes = texto.split(".")
    return not (partes[0] in ("1", "2", "3", "4", "5", "6") and all(len(p) <= 2 for p in partes))  # "1.2.3.4" = versão


def _unicos(itens, limite: int = MAX_STRINGS) -> list[str]:
    vistos: dict[str, None] = {}
    for item in itens:
        item = item.strip().rstrip(".,;:)")
        if item and item not in vistos:
            vistos[item] = None
            if len(vistos) >= limite:
                break
    return list(vistos)


def strings_interessantes(textos: list[str]) -> dict[str, list[str]]:
    """URLs, IPs, caminhos e chaves de registro, sem repetição (até ``MAX_STRINGS`` de cada)."""
    urls, ips, caminhos, registro = [], [], [], []
    for s in textos:
        urls += [u for u in URL.findall(s) if not URLS_COMUNS.match(u)]
        ips += [i for i in IPV4.findall(s) if _ip_interessante(i)]
        caminhos += CAMINHO.findall(s)
        registro += REGISTRO.findall(s)
    return {"urls": _unicos(urls), "ips": _unicos(ips), "caminhos": _unicos(caminhos), "registro": _unicos(registro)}


def filtrar_strings(textos: list[str], filtro: str, limite: int = 80) -> list[str]:
    filtro = filtro.lower()
    return _unicos((s for s in textos if filtro in s.lower()), limite)


# -- capacidades pelas importações -----------------------------------------------------------------------
CAPACIDADES: dict[str, tuple[str, set[str]]] = {
    "rede": ("rede (internet)", {
        "WSAStartup", "socket", "connect", "send", "recv", "InternetOpen", "InternetOpenUrl", "InternetReadFile",
        "InternetConnect", "HttpSendRequest", "HttpOpenRequest", "WinHttpOpen", "WinHttpConnect", "WinHttpSendRequest",
        "URLDownloadToFile", "URLDownloadToCacheFile", "gethostbyname", "getaddrinfo", "DnsQuery_", "FtpPutFile"}),
    "injecao": ("injeção em outros processos", {
        "VirtualAllocEx", "WriteProcessMemory", "CreateRemoteThread", "CreateRemoteThreadEx", "NtCreateThreadEx",
        "RtlCreateUserThread", "QueueUserAPC", "NtQueueApcThread", "SetThreadContext", "NtUnmapViewOfSection",
        "ZwUnmapViewOfSection", "NtWriteVirtualMemory"}),
    "criptografia": ("criptografia", {
        "CryptEncrypt", "CryptDecrypt", "CryptGenKey", "CryptAcquireContext", "CryptImportKey", "CryptDeriveKey",
        "BCryptEncrypt", "BCryptDecrypt", "BCryptGenerateSymmetricKey", "CryptProtectData", "CryptUnprotectData"}),
    "persistencia": ("persistência (iniciar com o Windows)", {
        "RegSetValueEx", "RegSetValue", "RegCreateKeyEx", "RegCreateKey", "CreateService", "ChangeServiceConfig",
        "StartService"}),
    "teclado": ("teclado", {
        "SetWindowsHookEx", "GetAsyncKeyState", "GetKeyboardState", "RegisterRawInputDevices", "GetRawInputData",
        "GetKeyState"}),
    "tela": ("captura de tela", {"BitBlt", "GetDesktopWindow", "CreateCompatibleBitmap", "GetDIBits"}),
    "execucao": ("execução de outros programas", {
        "CreateProcess", "CreateProcessAsUser", "ShellExecute", "ShellExecuteEx", "WinExec"}),
    "privilegios": ("privilégios", {"AdjustTokenPrivileges", "OpenProcessToken", "LookupPrivilegeValue",
                                    "ImpersonateLoggedOnUser", "DuplicateTokenEx"}),
    "anti_analise": ("detecção de depurador", {"IsDebuggerPresent", "CheckRemoteDebuggerPresent",
                                               "NtQueryInformationProcess", "OutputDebugString"}),
}


def capacidades(funcoes: set[str]) -> dict[str, list[str]]:
    """capacidade -> funções importadas que a indicam (só as capacidades presentes)."""
    achadas = {}
    for chave, (_rotulo, nomes) in CAPACIDADES.items():
        presentes = sorted(f for f in funcoes if f in nomes or any(n.endswith("_") and f.startswith(n) for n in nomes))
        if presentes:
            achadas[chave] = presentes
    return achadas


def motivos_das_importacoes(caps: dict[str, list[str]], funcoes: set[str], strings_texto: str) -> list[Motivo]:
    """Combinações de funções que, juntas, costumam indicar comportamento malicioso.

    Funções isoladas quase nunca bastam: um editor de texto também importa ``RegSetValueEx``."""
    motivos = []
    injecao = caps.get("injecao", [])
    escreve_em_outro = {"VirtualAllocEx", "WriteProcessMemory"} <= funcoes or "NtWriteVirtualMemory" in funcoes
    dispara = funcoes & {"CreateRemoteThread", "CreateRemoteThreadEx", "NtCreateThreadEx", "RtlCreateUserThread",
                         "QueueUserAPC", "NtQueueApcThread", "SetThreadContext"}
    if escreve_em_outro and dispara:
        motivos.append(Motivo("injecao", "pode escrever e rodar código dentro de outros programas (injeção de processo)",
                              3, injecao, "injecao"))
    elif {"NtUnmapViewOfSection", "ZwUnmapViewOfSection"} & funcoes and "SetThreadContext" in funcoes:
        motivos.append(Motivo("injecao", "pode substituir o código de outro programa na memória (process hollowing)",
                              3, injecao, "injecao"))
    teclado = set(caps.get("teclado", []))
    if "SetWindowsHookEx" in teclado and teclado & {"GetAsyncKeyState", "GetKeyboardState", "GetKeyState"}:
        motivos.append(Motivo("teclado", "pode monitorar o que é digitado (atalhos globais e jogos também fazem isso)",
                              2, sorted(teclado), "teclado"))
    elif {"RegisterRawInputDevices", "GetRawInputData"} <= teclado and "rede" in caps:
        motivos.append(Motivo("teclado", "lê a entrada do teclado diretamente e também usa a rede", 1, sorted(teclado),
                              "teclado"))
    if "URLDownloadToFile" in funcoes or "URLDownloadToCacheFile" in funcoes:
        motivos.append(Motivo("baixa_arquivos", "baixa arquivos da internet direto para o disco", 1,
                              [f for f in caps.get("rede", []) if f.startswith("URLDownload")], "rede"))
    if "CryptUnprotectData" in funcoes and re.search(r"Login Data|Local State|Cookies|wallet", strings_texto, _I) \
            and "rede" in caps:
        motivos.append(Motivo("dpapi_navegador", "decifra dados protegidos do Windows, cita arquivos de senhas do "
                                                 "navegador e usa a rede (padrão de ladrões de senha)", 3,
                              ["CryptUnprotectData"], "roubo_credenciais"))
    cripto = set(caps.get("criptografia", []))
    if cripto & {"CryptEncrypt", "BCryptEncrypt"} and {"FindFirstFile", "FindNextFile"} <= funcoes \
            and re.search(r"vssadmin|shadowcopy|\.locked|ransom|bitcoin|decrypt your files", strings_texto, _I):
        motivos.append(Motivo("ransomware", "cifra arquivos, percorre pastas e cita resgate ou cópias de sombra "
                                            "(padrão de ransomware)", 4, sorted(cripto), "ransomware"))
    return motivos


# -- MITRE ATT&CK ----------------------------------------------------------------------------------------
# Cada achado -> técnicas do ATT&CK (https://attack.mitre.org), o vocabulário comum de quem trabalha com
# segurança: deixa os relatórios comparáveis entre análises, agentes e ferramentas externas.
ATTACK: dict[str, tuple[tuple[str, str], ...]] = {
    "defender": (("T1562.001", "Impair Defenses: Disable or Modify Tools"),
                 ("T1562.004", "Impair Defenses: Disable or Modify System Firewall")),
    "amsi": (("T1562.001", "Impair Defenses: Disable or Modify Tools"),),
    "copias_sombra": (("T1490", "Inhibit System Recovery"),),
    "persistencia": (("T1547.001", "Boot or Logon Autostart: Registry Run Keys / Startup Folder"),
                     ("T1053.005", "Scheduled Task/Job: Scheduled Task"),
                     ("T1543.003", "Create or Modify System Process: Windows Service")),
    "credenciais": (("T1555.003", "Credentials from Web Browsers"),),
    "dpapi_navegador": (("T1555.003", "Credentials from Web Browsers"),),
    "lolbin": (("T1218", "System Binary Proxy Execution"),),
    "conexao_reversa": (("T1059", "Command and Scripting Interpreter"), ("T1071", "Application Layer Protocol")),
    "usuario_admin": (("T1136.001", "Create Account: Local Account"), ("T1098", "Account Manipulation")),
    "apagar_rastros": (("T1070.001", "Indicator Removal: Clear Windows Event Logs"),),
    "uac": (("T1548.002", "Abuse Elevation Control Mechanism: Bypass UAC"),),
    "oculto": (("T1564.003", "Hide Artifacts: Hidden Window"),),
    "download_execucao": (("T1105", "Ingress Tool Transfer"), ("T1059", "Command and Scripting Interpreter")),
    "download": (("T1105", "Ingress Tool Transfer"),),
    "download_escondido": (("T1105", "Ingress Tool Transfer"),),
    "baixa_arquivos": (("T1105", "Ingress Tool Transfer"),),
    "powershell_base64": (("T1059.001", "Command and Scripting Interpreter: PowerShell"),
                          ("T1027", "Obfuscated Files or Information")),
    "ofuscacao": (("T1027", "Obfuscated Files or Information"),),
    "bloco_codificado": (("T1027", "Obfuscated Files or Information"),),
    "base64": (("T1140", "Deobfuscate/Decode Files or Information"),),
    "compactado": (("T1027.002", "Obfuscated Files or Information: Software Packing"),),
    "sem_importacoes": (("T1027.002", "Obfuscated Files or Information: Software Packing"),),
    "injecao": (("T1055", "Process Injection"),),
    "teclado": (("T1056.001", "Input Capture: Keylogging"),),
    "ransomware": (("T1486", "Data Encrypted for Impact"), ("T1490", "Inhibit System Recovery")),
    "macros": (("T1204.002", "User Execution: Malicious File"), ("T1059.005", "Command and Scripting Interpreter: Visual Basic")),
    "dupla_extensao": (("T1036.007", "Masquerading: Double File Extension"),),
    "dupla_extensao_interna": (("T1036.007", "Masquerading: Double File Extension"),),
    "nome_disfarcado": (("T1036.002", "Masquerading: Right-to-Left Override"),),
    "extensao_falsa": (("T1036.008", "Masquerading: Masquerade File Type"),),
    "atalho_comando": (("T1204.002", "User Execution: Malicious File"),),
    "imagem_disco": (("T1553.005", "Subvert Trust Controls: Mark-of-the-Web Bypass"),),
    "zip_com_senha": (("T1027.013", "Obfuscated Files or Information: Encrypted/Encoded File"),),
    "pdf_ativo": (("T1204.002", "User Execution: Malicious File"),),
    "rtf_objeto": (("T1203", "Exploitation for Client Execution"),),
    "assinatura_alterada": (("T1553.002", "Subvert Trust Controls: Code Signing"),),
}


def mapear_attack(motivos: list[Motivo]) -> list[dict]:
    """Técnicas do ATT&CK dos achados que pesam a favor do risco, sem repetir, com os achados de origem."""
    saida: dict[str, dict] = {}
    for m in motivos:
        if m.peso <= 0:
            continue
        for tid, nome in ATTACK.get(m.id, ()):
            item = saida.setdefault(tid, {"id": tid, "nome": nome, "achados": [],
                                          "url": f"https://attack.mitre.org/techniques/{tid.replace('.', '/')}/"})
            if m.id not in item["achados"]:
                item["achados"].append(m.id)
    return sorted(saida.values(), key=lambda t: t["id"])


def indicadores(relatorio: dict) -> dict:
    """IOCs (indicadores de comprometimento) para procurar em outros PCs, no firewall ou no VirusTotal."""
    strings = relatorio.get("strings") or {}
    urls = list(strings.get("urls") or [])
    dominios = sorted({re.sub(r"^[a-z]+://", "", u, flags=re.I).split("/")[0].split(":")[0].lower() for u in urls} - {""})
    return {
        "sha256": relatorio.get("sha256", ""), "md5": relatorio.get("md5", ""), "sha1": relatorio.get("sha1", ""),
        "urls": urls[:MAX_STRINGS], "dominios": dominios[:MAX_STRINGS], "ips": list(strings.get("ips") or [])[:MAX_STRINGS],
        "registro": list(strings.get("registro") or [])[:MAX_STRINGS],
    }
