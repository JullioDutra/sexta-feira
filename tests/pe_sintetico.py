"""Monta executáveis PE mínimos (32 bits) em bytes, para testar a análise estática sem arquivos reais.

O resultado nunca roda (o código é lixo ou zeros): serve só para o leitor de cabeçalhos, seções e importações.
"""

from __future__ import annotations

import os
import struct

ALINHAMENTO = 0x200


def _alinhar(dados: bytes, alinhamento: int = ALINHAMENTO) -> bytes:
    return dados + b"\0" * (-len(dados) % alinhamento)


def _tabela_importacoes(importacoes: dict[str, list[str]], va: int) -> tuple[bytes, int]:
    """Bytes da seção de importações (descritores, ILTs, nomes) começando no endereço virtual ``va``."""
    dlls = list(importacoes)
    pos = (len(dlls) + 1) * 20
    ilts = []
    for dll in dlls:
        ilts.append(pos)
        pos += (len(importacoes[dll]) + 1) * 4
    nomes_func: dict[tuple[str, str], int] = {}
    corpo_nomes = b""
    for dll in dlls:
        for f in importacoes[dll]:
            nomes_func[(dll, f)] = pos + len(corpo_nomes)
            entrada = struct.pack("<H", 0) + f.encode() + b"\0"
            corpo_nomes += entrada + (b"\0" if len(entrada) % 2 else b"")
    nomes_dll = {}
    for dll in dlls:
        nomes_dll[dll] = pos + len(corpo_nomes)
        corpo_nomes += dll.encode() + b"\0"
    descritores = b""
    for dll, ilt in zip(dlls, ilts):
        descritores += struct.pack("<IIIII", va + ilt, 0, 0, va + nomes_dll[dll], va + ilt)
    descritores += b"\0" * 20
    corpo_ilt = b""
    for dll in dlls:
        for f in importacoes[dll]:
            corpo_ilt += struct.pack("<I", va + nomes_func[(dll, f)])
        corpo_ilt += b"\0" * 4
    return descritores + corpo_ilt + corpo_nomes, (len(dlls) + 1) * 20


def montar_pe(importacoes: dict[str, list[str]] | None = None, *, codigo: bytes | None = None,
              nomes_secoes: tuple[str, str] = (".text", ".idata"), timestamp: int = 1_700_000_000,
              dll: bool = False, clr: bool = False, strings: list[str] | None = None, sobra: bytes = b"",
              codigo_aleatorio: bool = False) -> bytes:
    importacoes = importacoes if importacoes is not None else {"kernel32.dll": ["ExitProcess", "GetStartupInfoW"]}
    if codigo is None:
        codigo = os.urandom(0x1000) if codigo_aleatorio else b"\x90" * 0x200
    if strings:
        codigo += b"\0".join(s.encode() for s in strings) + b"\0"
    texto_bruto = _alinhar(codigo)
    va_texto, va_imp = 0x1000, 0x1000 + ((len(texto_bruto) + 0xFFF) // 0x1000) * 0x1000
    imp_bruto, imp_tamanho = _tabela_importacoes(importacoes, va_imp) if importacoes else (b"", 0)
    imp_bruto = _alinhar(imp_bruto) if imp_bruto else b""

    dos = bytearray(0x40)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)
    secoes = [(nomes_secoes[0], va_texto, len(codigo), texto_bruto, 0x60000020)]
    if imp_bruto:
        secoes.append((nomes_secoes[1], va_imp, len(imp_bruto), imp_bruto, 0xC0000040))
    coff = struct.pack("<HHIIIHH", 0x14C, len(secoes), timestamp, 0, 0, 0xE0, 0x0102 | (0x2000 if dll else 0))
    opcional = bytearray(0xE0)
    struct.pack_into("<H", opcional, 0, 0x10B)
    struct.pack_into("<H", opcional, 68, 2)
    struct.pack_into("<I", opcional, 92, 16)
    if imp_bruto:
        struct.pack_into("<II", opcional, 96 + 8 * 1, va_imp, imp_tamanho)
    if clr:
        struct.pack_into("<II", opcional, 96 + 8 * 14, va_texto, 0x48)
    cabecalho = bytes(dos) + b"PE\0\0" + coff + bytes(opcional)
    posicao = ALINHAMENTO * ((len(cabecalho) + 40 * len(secoes) + ALINHAMENTO - 1) // ALINHAMENTO)
    tabela = b""
    corpo = b""
    for nome, va, tam_virtual, bruto, caracteristicas in secoes:
        tabela += struct.pack("<8sIIIIIIHHI", nome.encode()[:8], tam_virtual, va, len(bruto), posicao + len(corpo),
                              0, 0, 0, 0, caracteristicas)
        corpo += bruto
    return _alinhar(cabecalho + tabela, ALINHAMENTO) + corpo + sobra
