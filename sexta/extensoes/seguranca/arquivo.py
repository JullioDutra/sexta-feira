"""Análise estática de um arquivo: hashes, tipo real, PE, assinatura, strings, scripts, ASAR, ZIP.

O arquivo nunca é executado nem aberto por outro programa: só os bytes são lidos. O resultado é um
veredito em linguagem simples (baixo, médio ou alto risco) com os motivos e as evidências, e sempre os
limites da análise estática. Sem evidência forte, nunca diz "é vírus".
"""

from __future__ import annotations

import hashlib
import json
import mmap
import re
import struct
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import padroes, pe
from .padroes import Motivo

LER_STRINGS_MAX = 16 * 1024 * 1024   # strings: o começo do arquivo e o fim (onde ficam recursos e dados extras)
LER_FIM_MAX = 2 * 1024 * 1024
LER_SCRIPT_MAX = 4 * 1024 * 1024
LIMITE_ALTO, LIMITE_MEDIO = 6, 3
ROTULOS_RISCO = {"alto": "alto risco", "medio": "risco médio", "baixo": "baixo risco"}

EXTENSOES_PROGRAMA = {".exe", ".dll", ".scr", ".com", ".pif", ".sys", ".cpl", ".ocx", ".msi", ".msix", ".appx"}
EXTENSOES_PERIGOSAS = EXTENSOES_PROGRAMA | set(padroes.EXTENSOES_SCRIPT) | {".lnk", ".jar", ".iso", ".img", ".vhd",
                                                                             ".vhdx", ".chm", ".url"}
EXTENSOES_DOCUMENTO = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".jpg", ".jpeg", ".png",
                       ".gif", ".mp3", ".mp4", ".avi", ".mkv", ".zip", ".rar", ".csv", ".rtf", ".odt"}
DUPLA_EXTENSAO = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|jpe?g|png|gif|txt|mp3|mp4|avi|mkv|zip|rar|csv)\s*\."
                            r"(?:exe|scr|com|pif|bat|cmd|js|jse|vbs|vbe|ps1|hta|lnk|msi|wsf|cpl)$", re.I)
INVISIVEIS = {"‮": "inversão da direita para a esquerda (RLO)", "‭": "LRO", "​": "espaço invisível",
              "‎": "marca LRM", "‏": "marca RLM"}

LIMITES = [
    "Análise estática: li os bytes do arquivo, mas não o executei. O que ele faria ao rodar não foi observado.",
    "Programas compactados, cifrados ou que baixam partes da internet podem esconder comportamento desta análise.",
    "Funções e textos suspeitos também aparecem em programas legítimos; são indícios, não provas.",
]


class ErroAnalise(Exception):
    """Mensagem já pronta para falar ("Não encontrei o arquivo...")."""


# -- tipo real -----------------------------------------------------------------------------------------
MAGICOS: list[tuple[int, bytes, str, str]] = [
    (0, b"MZ", "pe", "programa do Windows (PE)"),
    (0, b"%PDF", "pdf", "documento PDF"),
    (0, b"PK\x03\x04", "zip", "arquivo ZIP"),
    (0, b"PK\x05\x06", "zip", "arquivo ZIP (vazio)"),
    (0, b"\x7fELF", "elf", "programa do Linux (ELF)"),
    (0, b"\xcf\xfa\xed\xfe", "macho", "programa do macOS (Mach-O)"),
    (0, b"\xce\xfa\xed\xfe", "macho", "programa do macOS (Mach-O)"),
    (0, b"\xca\xfe\xba\xbe", "macho", "programa do macOS (universal) ou classe Java"),
    (0, b"Rar!\x1a\x07", "rar", "arquivo RAR"),
    (0, b"7z\xbc\xaf\x27\x1c", "7z", "arquivo 7-Zip"),
    (0, b"\x1f\x8b", "gzip", "arquivo GZIP"),
    (0, b"MSCF", "cab", "arquivo CAB (pacote do Windows)"),
    (0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole", "documento OLE (Office antigo ou instalador MSI)"),
    (0, b"L\x00\x00\x00\x01\x14\x02\x00", "lnk", "atalho do Windows (.lnk)"),
    (0, b"\x89PNG\r\n\x1a\n", "imagem", "imagem PNG"),
    (0, b"\xff\xd8\xff", "imagem", "imagem JPEG"),
    (0, b"GIF8", "imagem", "imagem GIF"),
    (0, b"{\\rtf", "rtf", "documento RTF"),
    (0, b"ID3", "midia", "áudio MP3"),
    (4, b"ftyp", "midia", "vídeo ou áudio MP4"),
    (0, b"RIFF", "midia", "mídia RIFF (WAV/AVI/WebP)"),
    (0x8001, b"CD001", "iso", "imagem de disco (ISO)"),
    (0, b"Windows Registry Editor", "script", "arquivo de registro (.reg)"),
    (0, b"\xff\xfeW\x00i\x00n\x00d\x00o\x00w\x00s\x00 \x00R\x00e\x00g", "script", "arquivo de registro (.reg)"),
]


def identificar(cabeca: bytes, extensao: str) -> tuple[str, str]:
    """(categoria, descrição) pelo conteúdo (magic bytes); a extensão só desempata texto."""
    for pos, magico, categoria, descricao in MAGICOS:
        if cabeca[pos:pos + len(magico)] == magico:
            return categoria, descricao
    if _parece_asar(cabeca):
        return "asar", "pacote de aplicativo Electron (ASAR)"
    if extensao in padroes.EXTENSOES_SCRIPT and _parece_texto(cabeca):
        return "script", f"script {padroes.EXTENSOES_SCRIPT[extensao]}"
    if cabeca.startswith(b"#!"):
        return "script", "script com interpretador (#!)"
    if _parece_texto(cabeca):
        return "texto", "arquivo de texto"
    return "outro", "formato não reconhecido"


def _parece_texto(cabeca: bytes) -> bool:
    if not cabeca:
        return True
    if cabeca.startswith((b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")):
        return True
    amostra = cabeca[:4096]
    imprimiveis = sum(32 <= b < 127 or b in (9, 10, 13) or b >= 0x80 for b in amostra)
    return b"\x00" not in amostra and imprimiveis / len(amostra) > 0.95


def _parece_asar(cabeca: bytes) -> bool:
    if len(cabeca) < 20:
        return False
    tamanho_pickle, _ = struct.unpack_from("<II", cabeca, 0)
    return tamanho_pickle == 4 and cabeca[16:26].lstrip().startswith(b'{"files"')


def ler_texto(bruto: bytes) -> str:
    """Decodifica um script (UTF-8, UTF-16 com BOM ou Windows-1252)."""
    if bruto.startswith(b"\xff\xfe") or bruto.startswith(b"\xfe\xff"):
        return bruto.decode("utf-16", "replace")
    if bruto.startswith(b"\xef\xbb\xbf"):
        return bruto[3:].decode("utf-8", "replace")
    try:
        return bruto.decode("utf-8")
    except UnicodeDecodeError:
        return bruto.decode("cp1252", "replace")


# -- ASAR (Electron) ------------------------------------------------------------------------------------
def ler_asar(caminho: Path) -> tuple[dict, int]:
    """(cabeçalho JSON, posição dos dados) de um ``app.asar``."""
    with open(caminho, "rb") as f:
        inicio = f.read(16)
        if len(inicio) < 16:
            raise ErroAnalise("O arquivo ASAR está truncado.")
        _, tamanho_cabecalho, _, tamanho_json = struct.unpack("<IIII", inicio)
        if tamanho_json > 256 * 1024 * 1024:
            raise ErroAnalise("O cabeçalho do ASAR é grande demais para ser real.")
        try:
            cabecalho = json.loads(f.read(tamanho_json).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as erro:
            raise ErroAnalise(f"Não consegui ler o índice do ASAR: {erro}") from None
    return cabecalho, 8 + tamanho_cabecalho


def listar_asar(cabecalho: dict, prefixo: str = "") -> list[dict]:
    """Todos os arquivos do ASAR: caminho, tamanho, se fica fora do pacote (unpacked) e se é executável."""
    itens = []
    for nome, no in (cabecalho.get("files") or {}).items():
        caminho = f"{prefixo}/{nome}" if prefixo else nome
        if "files" in no:
            itens += listar_asar(no, caminho)
        else:
            itens.append({"caminho": caminho, "tamanho": int(no.get("size") or 0), "fora": bool(no.get("unpacked")),
                          "offset": no.get("offset"), "executavel": bool(no.get("executable"))})
    return itens


def ler_arquivo_asar(caminho: Path, interno: str, limite: int = 20_000) -> str:
    """O texto de um arquivo de dentro do ASAR (só leitura)."""
    cabecalho, base = ler_asar(caminho)
    interno = interno.strip("/").replace("\\", "/")
    item = next((i for i in listar_asar(cabecalho) if i["caminho"] == interno), None)
    if item is None:
        raise ErroAnalise(f"Não há {interno} dentro do pacote.")
    if item["fora"]:
        externo = caminho.with_name(caminho.name + ".unpacked") / interno
        return ler_texto(externo.read_bytes()[:limite]) if externo.is_file() else ""
    with open(caminho, "rb") as f:
        f.seek(base + int(item["offset"] or 0))
        return ler_texto(f.read(min(item["tamanho"], limite)))


def resumo_asar(caminho: Path) -> tuple[dict, list[Motivo]]:
    cabecalho, _ = ler_asar(caminho)
    itens = listar_asar(cabecalho)
    pacote = {}
    try:
        pacote = json.loads(ler_arquivo_asar(caminho, "package.json") or "{}")
    except (ErroAnalise, json.JSONDecodeError, OSError):
        pacote = {}
    nativos = [i["caminho"] for i in itens if i["caminho"].endswith(".node")]
    preload = [i["caminho"] for i in itens if re.search(r"preload[^/]*\.js$", i["caminho"], re.I)]
    raiz = sorted({i["caminho"].split("/", 1)[0] for i in itens})
    dependencias = sorted((pacote.get("dependencies") or {}).keys()) if isinstance(pacote, dict) else []
    detalhes = {
        "arquivos": len(itens), "tamanho_total": sum(i["tamanho"] for i in itens),
        "nome": pacote.get("productName") or pacote.get("name") if isinstance(pacote, dict) else None,
        "versao": pacote.get("version") if isinstance(pacote, dict) else None,
        "principal": pacote.get("main") if isinstance(pacote, dict) else None,
        "raiz": raiz[:40], "modulos_nativos": nativos[:30], "preload": preload[:10], "dependencias": dependencias[:60],
        "maiores": [i["caminho"] for i in sorted(itens, key=lambda i: -i["tamanho"])[:10]],
    }
    motivos = []
    if nativos:
        motivos.append(Motivo("modulos_nativos", "traz módulos nativos (.node), que rodam fora do JavaScript", 0,
                              nativos[:6], "electron"))
    return detalhes, motivos


def electron_vizinho(caminho: Path) -> Path | None:
    """Para o .exe de um app Electron: o ``resources/app.asar`` ao lado."""
    for candidato in (caminho.parent / "resources" / "app.asar", caminho.parent / "app.asar"):
        if candidato.is_file():
            return candidato
    return None


# -- ZIP e OLE -------------------------------------------------------------------------------------------
def resumo_zip(caminho: Path) -> tuple[dict, list[Motivo]]:
    try:
        with zipfile.ZipFile(caminho) as z:
            nomes = z.namelist()
            cifrado = any(i.flag_bits & 0x1 for i in z.infolist())
    except (zipfile.BadZipFile, OSError) as erro:
        return {"erro": str(erro)}, []
    motivos = []
    perigosos = [n for n in nomes if Path(n).suffix.lower() in EXTENSOES_PERIGOSAS]
    if any(n.lower().endswith("vbaproject.bin") for n in nomes):
        motivos.append(Motivo("macros", "documento do Office com macros (código VBA)", 2,
                              [n for n in nomes if n.lower().endswith("vbaproject.bin")], "macros"))
    if perigosos:
        peso = 2 if not _eh_pacote_office(nomes) else 1
        motivos.append(Motivo("programa_compactado", "o arquivo compactado tem programas ou scripts dentro", peso,
                              perigosos[:6], "entrega"))
        if cifrado:
            motivos.append(Motivo("zip_com_senha", "o ZIP tem senha (isso também impede antivírus de olhar dentro)", 1,
                                  ["entradas cifradas"], "entrega"))
    duplas = [n for n in nomes if DUPLA_EXTENSAO.search(n)]
    if duplas:
        motivos.append(Motivo("dupla_extensao_interna", "tem arquivo com extensão dupla, disfarçado de documento", 3,
                              duplas[:6], "disfarce"))
    tipo = "documento do Office (formato aberto)" if _eh_pacote_office(nomes) else None
    if "AndroidManifest.xml" in nomes:
        tipo = "aplicativo Android (APK)"
    elif "META-INF/MANIFEST.MF" in nomes:
        tipo = "programa Java (JAR)"
    return {"entradas": len(nomes), "amostra": nomes[:30], "tipo_interno": tipo, "senha": cifrado}, motivos


def _eh_pacote_office(nomes: list[str]) -> bool:
    return "[Content_Types].xml" in nomes and any(n.startswith(("word/", "xl/", "ppt/")) for n in nomes)


# -- assinatura digital (Windows) -------------------------------------------------------------------------
SCRIPT_ASSINATURA = (
    "$s = Get-AuthenticodeSignature -LiteralPath '{caminho}'; "
    "[pscustomobject]@{{Status=$s.Status.ToString(); Mensagem=$s.StatusMessage; "
    "Assinante=$(if($s.SignerCertificate){{$s.SignerCertificate.Subject}}); "
    "Emissor=$(if($s.SignerCertificate){{$s.SignerCertificate.Issuer}}); "
    "Validade=$(if($s.SignerCertificate){{$s.SignerCertificate.NotAfter.ToString('yyyy-MM-dd')}}); "
    "Carimbo=[bool]$s.TimeStamperCertificate; Tipo=$(if($s.SignatureType){{$s.SignatureType.ToString()}})}} "
    "| ConvertTo-Json -Compress"
)
STATUS_ASSINATURA = {
    "Valid": "válida", "NotSigned": "sem assinatura", "HashMismatch": "não confere (o arquivo foi alterado)",
    "NotTrusted": "de um certificado não confiável", "UnknownError": "com erro na verificação",
    "NotSupportedFileFormat": "não se aplica a este tipo de arquivo", "Incompatible": "incompatível",
}


def aspas_ps(texto: str) -> str:
    """Escapa para dentro de aspas simples do PowerShell."""
    return texto.replace("'", "''").replace("‘", "''").replace("’", "''")


def nome_do_assinante(sujeito: str | None) -> str:
    """ "CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond" -> "Microsoft Corporation"."""
    if not sujeito:
        return ""
    m = re.search(r'(?:^|,\s*)CN="?([^",]+)', sujeito)
    return (m.group(1) if m else sujeito).strip()


def interpretar_assinatura(saida: str) -> dict:
    """Saída JSON do ``Get-AuthenticodeSignature`` -> {"status", "texto", "assinante", ...}."""
    try:
        dados = json.loads(saida or "{}")
    except json.JSONDecodeError:
        return {"status": "erro", "texto": "não consegui ler a resposta do Windows", "assinante": ""}
    if isinstance(dados, list):
        dados = dados[0] if dados else {}
    status = str(dados.get("Status") or "UnknownError")
    return {"status": status, "texto": STATUS_ASSINATURA.get(status, status), "assinante": nome_do_assinante(dados.get("Assinante")),
            "emissor": nome_do_assinante(dados.get("Emissor")), "validade": dados.get("Validade"),
            "carimbo": bool(dados.get("Carimbo")), "catalogo": dados.get("Tipo") == "Catalog",
            "mensagem": dados.get("Mensagem") or ""}


def assinatura_windows(caminho: Path, powershell: Callable[[str], str] | None = None) -> dict:
    """Confere a assinatura digital (Authenticode) pelo Windows. Fora dele, ``status`` = "indisponivel"."""
    from ...habilidades import windows

    rodar = powershell or (lambda cmd: windows.powershell(cmd, timeout=30))
    try:
        return interpretar_assinatura(rodar(SCRIPT_ASSINATURA.format(caminho=aspas_ps(str(caminho)))))
    except windows.NaoSuportado:
        return {"status": "indisponivel", "texto": "só dá para conferir no Windows", "assinante": ""}
    except Exception as erro:  # noqa: BLE001 - OSError, subprocess.TimeoutExpired e afins
        return {"status": "erro", "texto": f"o Windows não conferiu ({erro})", "assinante": ""}


# -- análise ----------------------------------------------------------------------------------------------
def hashes(caminho: Path) -> dict[str, str]:
    sha256, sha1, md5 = hashlib.sha256(), hashlib.sha1(), hashlib.md5()  # noqa: S324 - só identificação
    with open(caminho, "rb") as f:
        while bloco := f.read(1024 * 1024):
            sha256.update(bloco)
            sha1.update(bloco)
            md5.update(bloco)
    return {"sha256": sha256.hexdigest(), "sha1": sha1.hexdigest(), "md5": md5.hexdigest()}


def _amostra(caminho: Path, tamanho: int) -> bytes:
    with open(caminho, "rb") as f:
        if tamanho <= LER_STRINGS_MAX + LER_FIM_MAX:
            return f.read()
        inicio = f.read(LER_STRINGS_MAX)
        f.seek(tamanho - LER_FIM_MAX)
        return inicio + b"\0" + f.read()


def motivos_do_nome(nome: str, categoria: str) -> list[Motivo]:
    motivos = []
    invisiveis = [descricao for c, descricao in INVISIVEIS.items() if c in nome]
    if invisiveis:
        motivos.append(Motivo("nome_disfarcado", "o nome tem caracteres invisíveis que disfarçam a extensão real", 5,
                              invisiveis, "disfarce"))
    if DUPLA_EXTENSAO.search(nome):
        motivos.append(Motivo("dupla_extensao", "o nome finge ser documento, mas termina em extensão de programa", 4,
                              [nome], "disfarce"))
    extensao = Path(nome).suffix.lower()
    if categoria == "pe" and extensao in EXTENSOES_DOCUMENTO:
        motivos.append(Motivo("extensao_falsa", f"tem extensão {extensao}, mas por dentro é um programa", 5,
                              [f"começa com 'MZ' (programa do Windows), não com o formato de {extensao}"], "disfarce"))
    elif categoria == "pe" and extensao and extensao not in EXTENSOES_PROGRAMA | {".bin", ".tmp", ".dat", ".node", ".pyd", ".mui"}:
        motivos.append(Motivo("extensao_estranha", f"é um programa com a extensão {extensao}", 1, [nome], "disfarce"))
    if extensao == ".scr":
        motivos.append(Motivo("protecao_tela", "proteção de tela (.scr) é um programa comum e pouco usado hoje", 1,
                              [nome], "disfarce"))
    return motivos


def _motivos_assinatura(assinatura: dict) -> list[Motivo]:
    status = assinatura.get("status")
    quem = assinatura.get("assinante") or "desconhecido"
    if status == "Valid":
        texto = f"assinado digitalmente por {quem} (assinatura válida)"
        return [Motivo("assinado", texto, -3, [f"emissor: {assinatura.get('emissor') or '?'}",
                                                f"validade do certificado: {assinatura.get('validade') or '?'}"], "assinado")]
    if status == "NotSigned":
        return [Motivo("sem_assinatura", "não tem assinatura digital (não dá para saber quem fez)", 1,
                       [assinatura.get("mensagem") or "NotSigned"], "sem_assinatura")]
    if status == "HashMismatch":
        return [Motivo("assinatura_alterada", "a assinatura não confere: o arquivo foi alterado depois de assinado", 4,
                       [assinatura.get("mensagem") or "HashMismatch", f"assinante: {quem}"], "assinatura_invalida")]
    if status in ("NotTrusted", "UnknownError"):
        return [Motivo("assinatura_duvidosa", f"a assinatura é {assinatura.get('texto')}", 2,
                       [assinatura.get("mensagem") or status, f"assinante: {quem}"], "assinatura_invalida")]
    return []


def nivel_de_risco(pontos: int, motivos: list[Motivo]) -> str:
    if pontos >= LIMITE_ALTO or any(m.peso >= 5 for m in motivos):
        return "alto"
    if pontos >= LIMITE_MEDIO or any(m.peso >= 4 for m in motivos):
        return "medio"
    return "baixo"


def analisar(caminho: Path, *, assinatura: Callable[[Path], dict] | None = None, usar_pefile: bool = True,
             agora: datetime | None = None) -> dict:
    """Analisa o arquivo e devolve o relatório completo (um dict pronto para JSON)."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroAnalise(f"Não encontrei o arquivo {caminho}.")
    if caminho.is_dir():
        raise ErroAnalise(f"{caminho.name} é uma pasta, não um arquivo. Diga qual arquivo dela analisar.")
    try:
        tamanho = caminho.stat().st_size
        hs = hashes(caminho)
        with open(caminho, "rb") as f:
            cabeca = f.read(0x8010)
    except PermissionError:
        raise ErroAnalise(f"O Windows não me deixou ler {caminho.name} (está em uso ou protegido).") from None
    except OSError as erro:
        raise ErroAnalise(f"Não consegui ler {caminho.name}: {erro}") from None

    nome = unicodedata.normalize("NFC", caminho.name)
    extensao = caminho.suffix.lower()
    categoria, descricao = identificar(cabeca, extensao)
    motivos: list[Motivo] = motivos_do_nome(nome, categoria)
    detalhes: dict = {}
    capacidades: dict[str, list[str]] = {}
    textos: list[str] = []
    sugestoes: list[str] = []
    limites = list(LIMITES)

    if categoria in ("script", "texto") and (extensao in padroes.EXTENSOES_SCRIPT or categoria == "script"):
        with open(caminho, "rb") as f:
            texto = ler_texto(f.read(LER_SCRIPT_MAX))
        categoria = "script"
        if extensao in padroes.EXTENSOES_SCRIPT:
            descricao = f"script {padroes.EXTENSOES_SCRIPT[extensao]}"
        motivos += padroes.analisar_texto(texto, script=True)
        textos = texto.splitlines()
        detalhes["linhas"] = len(textos)
        if tamanho > LER_SCRIPT_MAX:
            limites.append(f"Li só os primeiros {LER_SCRIPT_MAX // (1024 * 1024)} MB do script.")
    elif categoria == "asar":
        detalhes["asar"], extras = resumo_asar(caminho)
        motivos += extras
        sugestoes.append("Para entender como o app funciona por dentro, peça ao agente de engenharia reversa "
                         "(\"usa o agente de engenharia reversa nesse app\").")
    else:
        amostra = _amostra(caminho, tamanho)
        textos = padroes.extrair_strings(amostra)
        juntas = "\n".join(textos)
        if categoria == "pe":
            try:
                info = _ler_pe(caminho, tamanho, usar_pefile)
            except pe.ErroPE as erro:
                info = None
                detalhes["pe_erro"] = str(erro)
                motivos.append(Motivo("pe_estranho", f"parece programa, mas o cabeçalho é estranho ({erro})", 1, [], "pe"))
            if info is not None:
                descricao = f"{'biblioteca (DLL)' if info.dll else 'programa'} do Windows, {info.maquina}"
                detalhes["pe"] = info.como_dict()
                funcoes = info.funcoes()
                capacidades = padroes.capacidades(funcoes)
                motivos += padroes.motivos_das_importacoes(capacidades, funcoes, juntas)
                motivos += _motivos_pe(info, agora)
                if info.dotnet:
                    descricao += ", .NET"
                    limites.append("É um programa .NET: o código pode ser lido com um descompilador (ILSpy) sem executá-lo; "
                                   "as importações dizem pouco nesse caso.")
                asar = electron_vizinho(caminho)
                if asar is not None:
                    descricao += ", app Electron"
                    try:
                        detalhes["asar"], extras = resumo_asar(asar)
                        detalhes["asar"]["caminho"] = str(asar)
                        motivos += extras
                    except (ErroAnalise, OSError) as erro:
                        detalhes["asar"] = {"erro": str(erro)}
                    sugestoes.append("É um app Electron: o código JavaScript fica em resources/app.asar. Para entender "
                                     "como ele funciona, peça ao agente de engenharia reversa.")
            motivos += padroes.analisar_texto(juntas, script=False)
        elif categoria == "zip":
            detalhes["zip"], extras = resumo_zip(caminho)
            motivos += extras
            if detalhes["zip"].get("tipo_interno"):
                descricao = detalhes["zip"]["tipo_interno"]
        elif categoria == "ole":
            if re.search(r"_VBA_PROJECT|VBA[\\/]|\bThisDocument\b", juntas):
                motivos.append(Motivo("macros", "documento do Office com macros (código VBA)", 2, ["_VBA_PROJECT"], "macros"))
            if extensao == ".msi" or "Windows Installer" in juntas:
                descricao = "instalador do Windows (MSI)"
                limites.append("Instaladores MSI guardam os programas compactados dentro: só o pacote foi olhado.")
            motivos += padroes.analisar_texto(juntas, script=False)
        elif categoria == "lnk":
            motivos += padroes.analisar_texto(juntas, script=True)
            if re.search(r"powershell|cmd\.exe|mshta|wscript|cscript|rundll32|regsvr32", juntas, re.I):
                motivos.append(Motivo("atalho_comando", "é um atalho que roda um comando do sistema", 2,
                                      padroes.filtrar_strings(textos, "exe", 4), "lnk"))
        elif categoria == "iso":
            motivos.append(Motivo("imagem_disco", "imagem de disco: costuma ser usada para entregar programas", 1,
                                  [nome], "entrega"))
            limites.append("O conteúdo da imagem de disco não foi aberto: monte-a e analise os arquivos de dentro.")
        elif categoria in ("pdf", "rtf"):
            if re.search(r"/JavaScript|/JS\b|/Launch|/EmbeddedFile|/OpenAction", juntas):
                achados = sorted(set(re.findall(r"/JavaScript|/JS\b|/Launch|/EmbeddedFile|/OpenAction", juntas)))
                peso = 3 if "/Launch" in achados else 1
                motivos.append(Motivo("pdf_ativo", "o documento tem conteúdo ativo (JavaScript, anexos ou ação ao abrir)",
                                      peso, achados, "documento_ativo"))
            if categoria == "rtf" and re.search(r"\\objdata|\\objupdate|Equation\.3", juntas, re.I):
                motivos.append(Motivo("rtf_objeto", "o documento RTF tem objetos embutidos (técnica usada em ataques)", 2,
                                      ["\\objdata"], "documento_ativo"))

    pontos = max(0, sum(m.peso for m in motivos))
    if categoria in ("pe", "ole") or (categoria == "script" and extensao in (".ps1", ".psm1", ".psd1", ".vbs", ".js",
                                                                              ".wsf")):
        assinatura_dados = (assinatura or assinatura_windows)(caminho)
        motivos_ass = _motivos_assinatura(assinatura_dados)
        if categoria == "script":  # scripts quase nunca são assinados: só a assinatura válida ou alterada conta
            motivos_ass = [m for m in motivos_ass if m.id in ("assinado", "assinatura_alterada")]
        motivos += motivos_ass
        pontos = max(0, sum(m.peso for m in motivos))
        if assinatura_dados.get("status") in ("indisponivel", "erro"):
            limites.append(f"Assinatura digital: {assinatura_dados['texto']}.")
    else:
        assinatura_dados = {"status": "nao_aplica", "texto": "não se aplica a este tipo de arquivo", "assinante": ""}

    motivos.sort(key=lambda m: -m.peso)
    risco = nivel_de_risco(pontos, motivos)
    strings = padroes.strings_interessantes(textos) if textos else {"urls": [], "ips": [], "caminhos": [], "registro": []}
    tecnicas = sorted({m.tecnica for m in motivos if m.tecnica and m.peso > 0})
    relatorio = {
        "tipo": "arquivo", "arquivo": nome, "caminho": str(caminho), "tamanho": tamanho, **hs,
        "categoria": categoria, "descricao": descricao, "extensao": extensao,
        "risco": risco, "pontos": pontos, "motivos": [m.como_dict() for m in motivos],
        "assinatura": assinatura_dados, "capacidades": {c: f for c, f in capacidades.items()},
        "capacidades_rotulos": {c: padroes.CAPACIDADES[c][0] for c in capacidades},
        "strings": strings, "detalhes": detalhes, "tecnicas": tecnicas, "limites": limites, "sugestoes": sugestoes,
        "quando": (agora or datetime.now()).isoformat(timespec="seconds"),
    }
    relatorio["attack"] = padroes.mapear_attack(motivos)
    relatorio["indicadores"] = padroes.indicadores(relatorio)
    relatorio["veredito"] = veredito(relatorio)
    return relatorio


def _ler_pe(caminho: Path, tamanho: int, usar_pefile: bool) -> pe.InfoPE:
    with open(caminho, "rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as dados:
            return pe.ler(dados, tamanho_arquivo=tamanho, usar_pefile=usar_pefile, caminho=str(caminho))


def _motivos_pe(info: pe.InfoPE, agora: datetime | None) -> list[Motivo]:
    motivos = []
    compactado = pe.parece_compactado(info)
    if compactado:
        forte = bool(info.compactadores) or any("entropia" in c for c in compactado)
        motivos.append(Motivo("compactado", "o código está compactado ou cifrado, o que esconde o que ele faz", 2 if forte else 1,
                              compactado, "compactado"))
    if not info.importacoes and not info.dotnet and not info.dll:
        motivos.append(Motivo("sem_importacoes", "não declara nenhuma função do Windows (comum em programas compactados)",
                              1, ["tabela de importações vazia"], "compactado"))
    data = pe.data_suspeita(info, agora.astimezone() if agora else None)
    if data:
        motivos.append(Motivo("data_estranha", data, 1, [f"timestamp {info.timestamp}"], "pe"))
    if info.subsistema.startswith("nativo"):
        motivos.append(Motivo("driver", "é um driver ou programa nativo (roda com acesso total ao sistema)", 1,
                              [info.subsistema], "driver"))
    return motivos


# -- veredito --------------------------------------------------------------------------------------------
def veredito(r: dict) -> str:
    """Duas ou três frases para falar: o nível, o principal motivo e o que fazer."""
    nome = r["arquivo"]
    assinatura = r.get("assinatura") or {}
    positivos = [m for m in r["motivos"] if m["peso"] > 0]
    if assinatura.get("status") == "Valid":
        origem = f"assinado por {assinatura.get('assinante') or 'um fabricante identificado'}"
    elif assinatura.get("status") == "NotSigned" and r["categoria"] in ("pe", "ole"):
        origem = "sem assinatura digital"
    else:
        origem = ""
    tipo = r["descricao"]
    base = f"{nome}: {tipo}" + (f", {origem}" if origem else "") + "."
    if r["risco"] == "alto":
        principais = "; ".join(m["texto"] for m in positivos[:2])
        return (f"{base} Alto risco: {principais}. Eu não abriria esse arquivo; se não souber de onde veio, apague ou "
                f"mande para a quarentena do Defender.")
    if r["risco"] == "medio":
        principais = "; ".join(m["texto"] for m in positivos[:2]) or "alguns sinais fora do comum"
        return f"{base} Risco médio: {principais}. Só abra se confiar em quem mandou."
    if positivos:
        return f"{base} Baixo risco: não vi nada grave, só {positivos[0]['texto']}."
    return f"{base} Baixo risco: não vi nada suspeito na análise estática."


def resumo_curto(r: dict) -> dict:
    """O que vai para a IA (sem as listas grandes)."""
    return {
        "arquivo": r["arquivo"], "caminho": r["caminho"], "sha256": r["sha256"], "tipo": r["descricao"],
        "risco": r["risco"], "assinatura": (r.get("assinatura") or {}).get("texto"),
        "assinante": (r.get("assinatura") or {}).get("assinante"),
        "motivos": [f"{m['texto']} (peso {m['peso']})" for m in r["motivos"]][:10],
        "capacidades": list(r.get("capacidades_rotulos", {}).values()),
        "urls": r["strings"]["urls"][:8], "ips": r["strings"]["ips"][:8], "limites": r["limites"][:2],
        "attack": [f"{t['id']} {t['nome']}" for t in r.get("attack", [])][:10],
        "dominios": (r.get("indicadores") or {}).get("dominios", [])[:8],
        "sugestoes": r.get("sugestoes", []),
    }
