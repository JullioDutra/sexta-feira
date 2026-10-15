"""Leitura estática de executáveis do Windows (PE): cabeçalhos, seções, entropia e importações.

Nada aqui executa o arquivo: só lê os bytes. Os cabeçalhos e as seções são lidos por um leitor próprio
(pequeno e previsível); as importações usam o ``pefile`` quando ele está instalado (lida melhor com
arquivos estranhos e com as importações atrasadas) e, sem ele, o mesmo leitor próprio.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

MAQUINAS = {0x14C: "x86 (32 bits)", 0x8664: "x64 (64 bits)", 0xAA64: "ARM64", 0x1C4: "ARM (32 bits)",
            0x200: "Itanium"}
SUBSISTEMAS = {1: "nativo (driver)", 2: "programa com janela", 3: "programa de console", 9: "Windows CE",
               10: "EFI", 14: "Xbox", 16: "aplicativo de inicialização"}
DIR_IMPORT, DIR_SEGURANCA, DIR_IMPORT_ATRASADO, DIR_CLR = 1, 4, 13, 14
SECAO_EXECUTAVEL, SECAO_GRAVAVEL = 0x20000000, 0x80000000
ARQUIVO_DLL = 0x2000
MAX_DLLS, MAX_FUNCOES = 256, 4000
LER_SECAO_MAX = 64 * 1024 * 1024  # entropia: só o começo de seções enormes

# nomes de seção deixados por compactadores conhecidos ("packers"): escondem o código real da análise estática
SECOES_COMPACTADORES = {
    "upx0": "UPX", "upx1": "UPX", "upx2": "UPX", ".aspack": "ASPack", ".adata": "ASPack", ".mpress1": "MPRESS",
    ".mpress2": "MPRESS", ".themida": "Themida", ".winlice": "WinLicense", ".vmp0": "VMProtect", ".vmp1": "VMProtect",
    ".vmp2": "VMProtect", ".petite": "Petite", ".nsp0": "NsPack", ".nsp1": "NsPack", ".enigma1": "Enigma",
    ".enigma2": "Enigma", "pec2": "PECompact", ".pec": "PECompact", ".perplex": "Perplex",
}


class ErroPE(Exception):
    """O arquivo começa com MZ, mas não é um PE que eu consiga ler."""


@dataclass
class Secao:
    nome: str
    endereco_virtual: int
    tamanho_virtual: int
    tamanho_bruto: int
    posicao_bruta: int
    caracteristicas: int
    entropia: float = 0.0

    @property
    def executavel(self) -> bool:
        return bool(self.caracteristicas & SECAO_EXECUTAVEL)

    @property
    def gravavel(self) -> bool:
        return bool(self.caracteristicas & SECAO_GRAVAVEL)

    def como_dict(self) -> dict:
        return {"nome": self.nome, "tamanho_bruto": self.tamanho_bruto, "tamanho_virtual": self.tamanho_virtual,
                "entropia": round(self.entropia, 2), "executavel": self.executavel, "gravavel": self.gravavel}


@dataclass
class InfoPE:
    maquina: str
    bits: int
    dll: bool
    subsistema: str
    compilado_em: datetime | None
    timestamp: int
    secoes: list[Secao]
    diretorios: list[tuple[int, int]]
    importacoes: dict[str, list[str]] = field(default_factory=dict)
    sobra: int = 0                   # bytes depois da última seção (fora a assinatura): instaladores guardam dados aí
    leitor_importacoes: str = "proprio"

    @property
    def dotnet(self) -> bool:
        return _diretorio(self.diretorios, DIR_CLR)[1] > 0

    @property
    def assinatura_embutida(self) -> bool:
        return _diretorio(self.diretorios, DIR_SEGURANCA)[1] > 0

    @property
    def compactadores(self) -> list[str]:
        return sorted({SECOES_COMPACTADORES[s.nome.lower()] for s in self.secoes if s.nome.lower() in SECOES_COMPACTADORES})

    def funcoes(self) -> set[str]:
        """Todas as funções importadas, sem o sufixo A/W ("CreateProcessW" -> "CreateProcess")."""
        return {sem_sufixo(f) for lista in self.importacoes.values() for f in lista}

    def como_dict(self) -> dict:
        return {
            "arquitetura": self.maquina, "bits": self.bits, "tipo": "DLL (biblioteca)" if self.dll else "programa (.exe)",
            "subsistema": self.subsistema,
            "compilado_em": self.compilado_em.strftime("%d/%m/%Y %H:%M") if self.compilado_em else None,
            "secoes": [s.como_dict() for s in self.secoes], "dotnet": self.dotnet,
            "assinatura_embutida": self.assinatura_embutida, "compactadores": self.compactadores,
            "dlls": sorted(self.importacoes), "total_funcoes": sum(len(v) for v in self.importacoes.values()),
            "sobra_bytes": self.sobra, "leitor": self.leitor_importacoes,
        }


def sem_sufixo(funcao: str) -> str:
    if len(funcao) > 2 and funcao[-1] in "AW" and funcao[-2].islower():
        return funcao[:-1]
    return funcao


def entropia(dados: bytes) -> float:
    """Entropia de Shannon em bits por byte (0 a 8). Acima de ~7,2 os dados parecem compactados ou cifrados."""
    if not dados:
        return 0.0
    contagem = np.bincount(np.frombuffer(dados, dtype=np.uint8), minlength=256)
    p = contagem[contagem > 0] / len(dados)
    return float(-(p * np.log2(p)).sum())


def _diretorio(diretorios: list[tuple[int, int]], indice: int) -> tuple[int, int]:
    return diretorios[indice] if indice < len(diretorios) else (0, 0)


def _u16(dados, pos: int) -> int:
    return struct.unpack_from("<H", dados, pos)[0]


def _u32(dados, pos: int) -> int:
    return struct.unpack_from("<I", dados, pos)[0]


def ler(dados, *, tamanho_arquivo: int | None = None, usar_pefile: bool = True, caminho: str | None = None) -> InfoPE:
    """Lê o PE em ``dados`` (``bytes`` ou ``mmap``). ``caminho`` é passado ao pefile (que lê do disco)."""
    total = tamanho_arquivo if tamanho_arquivo is not None else len(dados)
    try:
        if dados[:2] != b"MZ":
            raise ErroPE("não começa com MZ")
        pos_pe = _u32(dados, 0x3C)
        if pos_pe <= 0 or pos_pe + 24 > total or dados[pos_pe:pos_pe + 4] != b"PE\0\0":
            raise ErroPE("cabeçalho PE ausente (pode ser um programa do MS-DOS)")
        coff = pos_pe + 4
        maquina = _u16(dados, coff)
        n_secoes = _u16(dados, coff + 2)
        timestamp = _u32(dados, coff + 4)
        tam_opcional = _u16(dados, coff + 16)
        caracteristicas = _u16(dados, coff + 18)
        opcional = coff + 20
        magico = _u16(dados, opcional)
        if magico not in (0x10B, 0x20B):
            raise ErroPE("cabeçalho opcional desconhecido")
        pe64 = magico == 0x20B
        subsistema = _u16(dados, opcional + 68)
        pos_n_dirs, pos_dirs = (opcional + 108, opcional + 112) if pe64 else (opcional + 92, opcional + 96)
        n_dirs = min(_u32(dados, pos_n_dirs), 16)
        diretorios = [(_u32(dados, pos_dirs + 8 * i), _u32(dados, pos_dirs + 8 * i + 4)) for i in range(n_dirs)]
        secoes: list[Secao] = []
        pos = opcional + tam_opcional
        for _ in range(min(n_secoes, 96)):
            if pos + 40 > total:
                break
            nome = bytes(dados[pos:pos + 8]).split(b"\0", 1)[0].decode("latin-1")
            secoes.append(Secao(nome, _u32(dados, pos + 12), _u32(dados, pos + 8), _u32(dados, pos + 16),
                                _u32(dados, pos + 20), _u32(dados, pos + 36)))
            pos += 40
    except (struct.error, IndexError, ValueError) as erro:
        raise ErroPE(f"cabeçalho truncado ({erro})") from None

    for s in secoes:
        inicio = min(s.posicao_bruta, total)
        fim = min(inicio + min(s.tamanho_bruto, LER_SECAO_MAX), total)
        s.entropia = entropia(bytes(dados[inicio:fim]))

    fim_secoes = max((s.posicao_bruta + s.tamanho_bruto for s in secoes if s.tamanho_bruto), default=total)
    pos_assinatura, tam_assinatura = _diretorio(diretorios, DIR_SEGURANCA)  # aqui é posição no arquivo, não RVA
    sobra = max(0, total - fim_secoes)
    if tam_assinatura and pos_assinatura >= fim_secoes:
        sobra = max(0, sobra - tam_assinatura)

    compilado = None
    if timestamp:
        try:
            compilado = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            compilado = None
    info = InfoPE(MAQUINAS.get(maquina, f"desconhecida (0x{maquina:X})"), 64 if pe64 else 32,
                  bool(caracteristicas & ARQUIVO_DLL), SUBSISTEMAS.get(subsistema, f"outro ({subsistema})"),
                  compilado, timestamp, secoes, diretorios, sobra=sobra)

    importacoes = _importacoes_pefile(caminho, dados) if usar_pefile else None
    if importacoes is not None:
        info.importacoes, info.leitor_importacoes = importacoes, "pefile"
    else:
        info.importacoes = _importacoes_proprias(dados, total, secoes, diretorios, pe64)
    return info


def pefile_disponivel() -> bool:
    try:
        import pefile  # noqa: F401
    except ImportError:
        return False
    return True


def _importacoes_pefile(caminho: str | None, dados) -> dict[str, list[str]] | None:
    try:
        import pefile
    except ImportError:
        return None
    try:
        pe = pefile.PE(caminho, fast_load=True) if caminho else pefile.PE(data=bytes(dados), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                               pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        resultado: dict[str, list[str]] = {}
        for entrada in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) + getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []):
            dll = entrada.dll.decode("latin-1", "replace").lower() if entrada.dll else "?"
            nomes = resultado.setdefault(dll, [])
            for imp in entrada.imports[:MAX_FUNCOES]:
                nomes.append(imp.name.decode("latin-1", "replace") if imp.name else f"#{imp.ordinal}")
            if len(resultado) >= MAX_DLLS:
                break
        pe.close()
        return resultado
    except Exception:  # noqa: BLE001 - arquivo estranho: o leitor próprio tenta
        return None


def _rva_para_posicao(rva: int, secoes: list[Secao]) -> int | None:
    for s in secoes:
        tamanho = max(s.tamanho_virtual, s.tamanho_bruto)
        if s.endereco_virtual <= rva < s.endereco_virtual + tamanho:
            return rva - s.endereco_virtual + s.posicao_bruta
    return None


def _texto_c(dados, pos: int, total: int, limite: int = 256) -> str:
    fim = min(pos + limite, total)
    trecho = bytes(dados[pos:fim])
    return trecho.split(b"\0", 1)[0].decode("latin-1", "replace")


def _importacoes_proprias(dados, total: int, secoes: list[Secao], diretorios: list[tuple[int, int]],
                          pe64: bool) -> dict[str, list[str]]:
    rva, tamanho = _diretorio(diretorios, DIR_IMPORT)
    if not rva or not tamanho:
        return {}
    pos = _rva_para_posicao(rva, secoes)
    if pos is None:
        return {}
    largura, bit_ordinal = (8, 1 << 63) if pe64 else (4, 1 << 31)
    formato = "<Q" if pe64 else "<I"
    resultado: dict[str, list[str]] = {}
    try:
        for _ in range(MAX_DLLS):
            if pos + 20 > total:
                break
            original, _ts, _enc, nome_rva, primeiro = struct.unpack_from("<IIIII", dados, pos)
            pos += 20
            if not (original or nome_rva or primeiro):
                break
            pos_nome = _rva_para_posicao(nome_rva, secoes)
            dll = _texto_c(dados, pos_nome, total).lower() if pos_nome is not None else "?"
            funcoes = resultado.setdefault(dll, [])
            pos_thunk = _rva_para_posicao(original or primeiro, secoes)
            if pos_thunk is None:
                continue
            for _ in range(MAX_FUNCOES):
                if pos_thunk + largura > total:
                    break
                valor = struct.unpack_from(formato, dados, pos_thunk)[0]
                pos_thunk += largura
                if not valor:
                    break
                if valor & bit_ordinal:
                    funcoes.append(f"#{valor & 0xFFFF}")
                    continue
                pos_func = _rva_para_posicao(valor & 0x7FFFFFFF, secoes)
                if pos_func is not None:
                    funcoes.append(_texto_c(dados, pos_func + 2, total))
    except struct.error:
        pass
    return resultado


def data_suspeita(info: InfoPE, agora: datetime | None = None) -> str | None:
    """Datas de compilação no futuro (ou antes do Windows NT) foram alteradas ou são sem sentido.

    Muitos compiladores modernos (builds reprodutíveis) gravam um número qualquer no lugar da data: por isso isso
    pesa pouco."""
    if info.compilado_em is None:
        return None
    agora = agora or datetime.now(timezone.utc)
    if info.compilado_em > agora.replace(microsecond=0) and (info.compilado_em - agora).days > 1:
        return f"a data de compilação está no futuro ({info.compilado_em:%d/%m/%Y})"
    if info.compilado_em.year < 1995:
        return f"a data de compilação é antiga demais para ser real ({info.compilado_em:%d/%m/%Y})"
    return None


def parece_compactado(info: InfoPE) -> list[str]:
    """Indícios de que o código está compactado ou cifrado (e a análise estática vê pouco)."""
    indicios = [f"seções do compactador {nome}" for nome in info.compactadores]
    altas = [s for s in info.secoes if s.executavel and s.entropia >= 7.2 and s.tamanho_bruto > 1024]
    if altas:
        indicios.append("código com entropia muito alta (" + ", ".join(f"{s.nome or '?'} {s.entropia:.1f}" for s in altas)
                        + "): parece compactado ou cifrado")
    gravavel_exec = [s for s in info.secoes if s.executavel and s.gravavel and s.tamanho_bruto > 0]
    if gravavel_exec and not info.compactadores:
        indicios.append("seção que é ao mesmo tempo gravável e executável (" + ", ".join(s.nome or "?" for s in gravavel_exec)
                        + ")")
    return indicios
