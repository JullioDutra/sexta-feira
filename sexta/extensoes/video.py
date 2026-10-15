"""Vídeos: edição com ffmpeg e criação com HyperFrames (HTML → MP4), em segundo plano.

Edição dos vídeos do usuário (pasta Vídeos, ou a escolhida em Ajustes / ``VIDEOS_PASTA``):
"corta o vídeo da viagem do 0:30 ao 1:15", "junta os vídeos praia e show", "extrai o áudio do último
vídeo", "acelera o vídeo X em 2x", "comprime o vídeo X para o WhatsApp", "converte o vídeo X para
webm", "faz um GIF do vídeo X do 0:05 ao 0:10", "tira o áudio do vídeo X", "coloca legendas no vídeo X"
(transcritas no próprio PC com o Whisper) e "faz um corte vertical do vídeo X" (9:16 para Shorts/Reels).

Criação: "cria um vídeo de 15 segundos anunciando meu canal" — o cérebro escreve a composição HTML do
HyperFrames (``dados/videos/<nome>/index.html``), o ``npx hyperframes lint`` confere (até 2 correções)
e o ``npx hyperframes render`` gera o MP4.

Tudo vira um trabalho na fila (um por vez, para não brigar pela CPU), com progresso ao vivo no
holograma "Vídeos" e aviso falado no fim. A saída é sempre um arquivo novo na subpasta
``Sexta-Feira`` da pasta de vídeos: nada sobrescreve nem apaga o original.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import re
import shutil
import subprocess
import textwrap
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..cerebro.ferramentas import LIVRE, P
from ..habilidades import windows
from ..util.texto import normalizar, remover_ativacao, sem_acentos

log = logging.getLogger(__name__)

PREFERENCIAS = {"videos_pasta": "", "videos_qualidade": "media"}
HOLOGRAMAS = {"videos": "Vídeos"}
EVENTOS_ALTA_FREQUENCIA = {"video.trabalhos"}

EXTENSOES_VIDEO = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".m4v", ".flv", ".mts", ".ts", ".3gp"}
SUBPASTA_SAIDA = "Sexta-Feira"
MAX_GERADOS = 40
MAX_VARRER = 4000
ATUALIZAR_S = 0.5            # intervalo mínimo entre eventos de progresso
GIF_PADRAO_S = 10            # GIF sem trecho: os primeiros 10 segundos
TRECHO_LEGENDA_S = 30        # o Whisper ouve 30 s por vez (libera a voz da Sexta entre um trecho e outro)
TENTATIVAS_LINT = 2
NODE_MINIMO = 22

QUALIDADES = {  # preferência -> (crf do x264, preset, qualidade do hyperframes render)
    "alta": (18, "slow", "delivery"),
    "media": (23, "medium", "looks"),
    "leve": (28, "veryfast", "draft"),
}
DESTINOS_MB = {"whatsapp": 16, "discord": 10, "email": 20, "telegram": 50}
FORMATOS_VIDEO = ("mp4", "webm", "mkv", "mov", "avi")
FORMATOS_AUDIO = ("mp3", "m4a", "wav")
PROPORCOES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
TIPO_POR_EXTENSAO = {".gif": "gif", ".srt": "legenda", **{f".{f}": "audio" for f in FORMATOS_AUDIO}}
MIDIA = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
         ".avi": "video/x-msvideo", ".gif": "image/gif", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
         ".wav": "audio/wav", ".srt": "text/plain; charset=utf-8"}

INSTALAR_FFMPEG = "Instale o FFmpeg: no PowerShell, winget install Gyan.FFmpeg (e reinicie a Sexta-Feira)."
INSTALAR_NODE = "Instale o Node.js 22 ou mais novo: winget install OpenJS.NodeJS.LTS (e reinicie a Sexta-Feira)."


class ErroVideo(Exception):
    pass


class Cancelado(Exception):
    pass


# -- tempos ------------------------------------------------------------------------------------------

_NUMEROS = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
    "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14,
    "catorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50,
}
_DEZENAS = "vinte|trinta|quarenta|cinquenta"
_UNIDADES = "um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove"
_SEGUNDOS_UNIDADE = {"h": 3600, "hora": 3600, "horas": 3600, "min": 60, "mins": 60, "m": 60, "minuto": 60,
                     "minutos": 60, "s": 1, "seg": 1, "segs": 1, "segundo": 1, "segundos": 1}
_RE_UNIDADE = r"horas?|h|minutos?|mins?|m|segundos?|segs?|s"
_ENCHIMENTO = {"e", "o", "a", "no", "na", "os", "as", "de", "do", "da", "aos", "ao", "em", "nos", "exatos"}


def _norm(texto: str) -> str:
    """Como ``normalizar``, mas mantém a vírgula/ponto decimal ("1,5 minuto") e os dois-pontos ("1:15")."""
    t = sem_acentos(str(texto or "").lower().replace("-", " "))
    t = re.sub(r"(\d)[.,](\d)", r"\1#\2", t)
    t = re.sub(r"[^a-z0-9:#\s]", " ", t).replace("#", ".")
    return re.sub(r"\s+", " ", t).strip()


def _preparar_tempo(texto: str) -> str:
    t = _norm(texto)
    t = re.sub(rf"\b({_DEZENAS}) e ({_UNIDADES})\b", lambda m: str(_NUMEROS[m.group(1)] + _NUMEROS[m.group(2)]), t)
    t = re.sub(r"\b(" + "|".join(_NUMEROS) + r")\b", lambda m: str(_NUMEROS[m.group(1)]), t)
    t = re.sub(r"\bmeio minuto\b", "30 segundos", t)
    t = re.sub(r"\bmeia hora\b", "30 minutos", t)
    return re.sub(r"(\d)\s*(h|m|s|min|seg)(?=\d|\b)", r"\1 \2 ", t).strip()


def _unidade_explicita(texto: str) -> str | None:
    """A unidade escrita no texto ("minuto 2" -> "minuto", "10 segundos" -> "segundo"), se houver uma só."""
    t = _preparar_tempo(texto)
    if ":" in t:
        return None
    achadas = {_SEGUNDOS_UNIDADE[u] for u in re.findall(rf"\b({_RE_UNIDADE})\b", t)}
    return {3600: "hora", 60: "minuto", 1: "segundo"}[achadas.pop()] if len(achadas) == 1 else None


def interpretar_tempo(texto: str, unidade_padrao: str = "segundo") -> float | None:
    """ "1:15" -> 75; "30 segundos" -> 30; "minuto 2" -> 120; "1 minuto e 15" -> 75; "1h2m" -> 3720.

    Número sem unidade usa ``unidade_padrao`` ("segundo", "minuto" ou "hora"). Devolve ``None`` se não entender.
    """
    t = _preparar_tempo(texto)
    if not t:
        return None
    t = re.sub(r"^(?:(?:o|no|aos|ao|em) )?(?:(?:minuto|min|tempo|segundo) )?(?=\d+:\d)", "", t)
    if m := re.fullmatch(r"(\d+):(\d{1,2}(?:\.\d+)?)(?::(\d{1,2}(?:\.\d+)?))?", t):
        a, b, c = m.groups()
        return float(a) * 3600 + float(b) * 60 + float(c) if c is not None else float(a) * 60 + float(b)
    # "minuto 2", "segundo 30", "minuto 2 e 30": a unidade vem antes do número
    if m := re.fullmatch(r"(?:(?:o|no|aos|ao) )?(hora|minuto|segundo)s? (\d+(?:\.\d+)?)(?: e (\d+(?:\.\d+)?))?", t):
        base = _SEGUNDOS_UNIDADE[m.group(1)]
        resto = float(m.group(3)) * (base / 60 if base > 1 else 1) if m.group(3) else 0.0
        return float(m.group(2)) * base + resto
    total, achou, anterior = 0.0, False, None
    for m in re.finditer(rf"(\d+(?:\.\d+)?)\s*({_RE_UNIDADE})?\b(\s+e\s+meio\b)?", t):
        valor, unidade = float(m.group(1)), m.group(2)
        if unidade:
            base = _SEGUNDOS_UNIDADE[unidade]
        elif anterior is not None and anterior > 1:
            base = anterior // 60  # "1 minuto e 15" -> 15 segundos
        else:
            base = _SEGUNDOS_UNIDADE[unidade_padrao]
        total += valor * base + (base / 2 if m.group(3) else 0)
        achou, anterior = True, base
    if not achou:
        return None
    resto = re.sub(rf"(\d+(?:\.\d+)?)\s*({_RE_UNIDADE})?\b(\s+e\s+meio\b)?", " ", t)
    if any(p not in _ENCHIMENTO for p in resto.split()):
        return None
    return total


@dataclass
class Intervalo:
    inicio: float | None = None     # None = desde o começo
    fim: float | None = None        # None = até o fim
    do_fim: float | None = None     # "últimos N segundos"

    def resolver(self, duracao: float) -> tuple[float, float]:
        """Segundos (início, fim) dentro do vídeo; erro claro se o trecho não existir."""
        if self.do_fim is not None:
            return max(0.0, duracao - self.do_fim), duracao
        inicio = self.inicio or 0.0
        fim = duracao if self.fim is None else self.fim
        if duracao and inicio >= duracao:
            raise ErroVideo(f"O vídeo só tem {formatar_tempo(duracao)}; o trecho começa depois do fim.")
        if duracao and fim > duracao + 0.5:
            fim = duracao  # "até o 2:00" num vídeo de 1:58: corta até o fim
        if fim <= inicio:
            raise ErroVideo("O fim do trecho precisa vir depois do começo.")
        return inicio, min(fim, duracao) if duracao else fim


_SEPARADORES = r"\s+(?:ate o|ate a|ate|ao|a|pro|para o)\s+"


def interpretar_intervalo(texto: str) -> Intervalo | None:
    """ "do 0:30 ao 1:15", "do minuto 2 ao 3", "de 10 a 20 segundos", "primeiros 30 segundos",
    "últimos 10 segundos", "a partir do 1:00", "até o 0:45". ``None`` se não entender."""
    t = _norm(texto)
    t = re.sub(r"^(?:o trecho|trecho|so|somente|apenas|pega|deixa)\s+", "", t)
    t = re.sub(r"\s+(?:do video|do arquivo)$", "", t)
    if not t:
        return None
    if m := re.fullmatch(r"(?:os |o |nos )?primeiros? (.+)", t):
        fim = interpretar_tempo(m.group(1))
        return Intervalo(0.0, fim) if fim else None
    if m := re.fullmatch(r"(?:os |o |nos )?ultimos? (.+)", t):
        n = interpretar_tempo(m.group(1))
        return Intervalo(do_fim=n) if n else None
    if m := re.fullmatch(r"(?:a partir|depois|comecando|desde)\s+(?:do|de|da|o)?\s*(.+?)(?:\s+(?:em diante|ate o fim|ate o final))?", t):
        inicio = interpretar_tempo(m.group(1))
        return Intervalo(inicio, None) if inicio is not None else None
    if m := re.fullmatch(r"(?:do|de|da|dos|desde o|entre o|entre)\s+(.+?)\s+(?:ate o fim|ate o final|em diante|pra frente)", t):
        inicio = interpretar_tempo(m.group(1))
        return Intervalo(inicio, None) if inicio is not None else None
    if m := re.fullmatch(r"(?:ate|ate o|ate a)\s+(.+)", t):
        fim = interpretar_tempo(m.group(1))
        return Intervalo(0.0, fim) if fim else None
    m = re.fullmatch(r"(?:do|de|da|dos|desde o|desde|entre o|entre|no|o)\s+(.+)", t)
    corpo = m.group(1) if m else t
    separador = r"\s+e\s+(?:o\s+)?" if t.startswith("entre") else _SEPARADORES
    for sep in re.finditer(separador, corpo):
        a, b = corpo[:sep.start()], corpo[sep.end():]
        ua, ub = _unidade_explicita(a), _unidade_explicita(b)
        inicio = interpretar_tempo(a, ua or ub or "segundo")
        fim = interpretar_tempo(b, ub or ua or "segundo")
        if inicio is not None and fim is not None:
            return Intervalo(inicio, fim)
    return None


def formatar_tempo(segundos: float) -> str:
    """75 -> "1:15"; 3723 -> "1:02:03"."""
    s = int(round(max(0.0, segundos)))
    h, resto = divmod(s, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _num(valor: float) -> str:
    """Número para a linha de comando, sem notação científica nem zeros sobrando."""
    return f"{valor:.3f}".rstrip("0").rstrip(".") or "0"


# -- ffmpeg: sondagem, linhas de comando e progresso ---------------------------------------------------

@dataclass
class InfoVideo:
    duracao: float = 0.0
    largura: int = 0
    altura: int = 0
    tem_video: bool = True
    tem_audio: bool = False
    fps: float = 0.0
    tamanho: int = 0

    def descricao(self) -> str:
        partes = [formatar_tempo(self.duracao)]
        if self.largura:
            partes.append(f"{self.largura}x{self.altura}")
        if self.fps:
            partes.append(f"{self.fps:.0f} fps")
        partes.append("com áudio" if self.tem_audio else "sem áudio")
        if self.tamanho:
            partes.append(_tamanho(self.tamanho))
        return ", ".join(partes)


def ler_sonda(dados: dict) -> InfoVideo:
    """Interpreta a saída JSON do ``ffprobe -show_format -show_streams``."""
    info = InfoVideo(tem_video=False)
    formato = dados.get("format") or {}
    try:
        info.duracao = float(formato.get("duration") or 0)
        info.tamanho = int(formato.get("size") or 0)
    except (TypeError, ValueError):
        pass
    for s in dados.get("streams") or []:
        tipo = s.get("codec_type")
        if tipo == "video" and not info.tem_video and not (s.get("disposition") or {}).get("attached_pic"):
            info.tem_video = True
            info.largura, info.altura = int(s.get("width") or 0), int(s.get("height") or 0)
            try:
                num, _, den = str(s.get("avg_frame_rate") or "0/1").partition("/")
                info.fps = float(num) / float(den or 1) if float(den or 1) else 0.0
            except ValueError:
                info.fps = 0.0
            if not info.duracao:
                try:
                    info.duracao = float(s.get("duration") or 0)
                except (TypeError, ValueError):
                    pass
        elif tipo == "audio":
            info.tem_audio = True
    return info


def ler_progresso(linha: str, duracao: float) -> float | None:
    """Uma linha do ``-progress`` do ffmpeg -> fração concluída (0–1), ou ``None`` se não for de tempo."""
    chave, _, valor = linha.strip().partition("=")
    if chave == "progress" and valor == "end":
        return 1.0
    if chave in ("out_time_us", "out_time_ms") and valor.lstrip("-").isdigit():
        segundos = int(valor) / 1_000_000  # out_time_ms também vem em microssegundos (bug antigo do ffmpeg)
    elif chave == "out_time" and re.fullmatch(r"-?\d+:\d{2}:\d{2}(?:\.\d+)?", valor):
        h, m, s = valor.lstrip("-").split(":")
        segundos = int(h) * 3600 + int(m) * 60 + float(s)
    else:
        return None
    if duracao <= 0:
        return None
    return max(0.0, min(1.0, segundos / duracao))


def _base(ffmpeg: str) -> list[str]:
    # -n: nunca sobrescreve; -progress pipe:1: andamento em linhas chave=valor na saída padrão
    return [ffmpeg, "-hide_banner", "-nostdin", "-n", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]


def _codificar(qualidade: str, audio: bool = True) -> list[str]:
    crf, preset, _ = QUALIDADES.get(qualidade, QUALIDADES["media"])
    args = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
    args += ["-c:a", "aac", "-b:a", "160k"] if audio else ["-an"]
    return args + ["-movflags", "+faststart"]


def cmd_cortar(ffmpeg: str, entrada: Path, saida: Path, inicio: float, fim: float, qualidade: str,
               audio: bool = True) -> list[str]:
    return (_base(ffmpeg) + ["-ss", _num(inicio), "-i", str(entrada), "-t", _num(fim - inicio),
                             "-map", "0:v:0", "-map", "0:a:0?"] + _codificar(qualidade, audio) + [str(saida)])


def cmd_juntar(ffmpeg: str, entradas: list[tuple[Path, InfoVideo]], saida: Path, qualidade: str) -> list[str]:
    """Junta vídeos de tamanhos e codecs diferentes: todos viram o tamanho do primeiro (com tarjas), 30 fps."""
    largura = max(2, (entradas[0][1].largura or 1280) // 2 * 2)
    altura = max(2, (entradas[0][1].altura or 720) // 2 * 2)
    algum_audio = any(info.tem_audio for _, info in entradas)
    cmd = _base(ffmpeg)
    for caminho, _ in entradas:
        cmd += ["-i", str(caminho)]
    silencios: dict[int, int] = {}
    if algum_audio:
        for i, (_, info) in enumerate(entradas):
            if not info.tem_audio:  # sem áudio: silêncio do mesmo tamanho, para o concat não desalinhar
                silencios[i] = len(entradas) + len(silencios)
                cmd += ["-f", "lavfi", "-t", _num(info.duracao or 1), "-i", "anullsrc=r=48000:cl=stereo"]
    filtros, pares = [], []
    for i in range(len(entradas)):
        filtros.append(f"[{i}:v]scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
                       f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[v{i}]")
        pares.append(f"[v{i}]")
        if algum_audio:
            fonte = f"{silencios[i]}:a" if i in silencios else f"{i}:a"
            filtros.append(f"[{fonte}]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
            pares.append(f"[a{i}]")
    filtros.append(f"{''.join(pares)}concat=n={len(entradas)}:v=1:a={1 if algum_audio else 0}[v]"
                   + ("[a]" if algum_audio else ""))
    cmd += ["-filter_complex", ";".join(filtros), "-map", "[v]"]
    if algum_audio:
        cmd += ["-map", "[a]"]
    return cmd + _codificar(qualidade, algum_audio) + [str(saida)]


def cmd_extrair_audio(ffmpeg: str, entrada: Path, saida: Path) -> list[str]:
    codec = {".mp3": ["-c:a", "libmp3lame", "-q:a", "2"], ".m4a": ["-c:a", "aac", "-b:a", "192k"],
             ".wav": ["-c:a", "pcm_s16le"]}[saida.suffix.lower()]
    return _base(ffmpeg) + ["-i", str(entrada), "-vn", "-map", "0:a:0"] + codec + [str(saida)]


def cadeia_atempo(fator: float) -> str:
    """O filtro atempo aceita 0,5–2 por etapa: 4x vira "atempo=2,atempo=2"."""
    partes = []
    while fator > 2.0:
        partes.append(2.0)
        fator /= 2.0
    while fator < 0.5:
        partes.append(0.5)
        fator /= 0.5
    partes.append(fator)
    return ",".join(f"atempo={_num(p)}" for p in partes)


def cmd_velocidade(ffmpeg: str, entrada: Path, saida: Path, fator: float, audio: bool, qualidade: str) -> list[str]:
    filtro = f"[0:v]setpts=PTS/{_num(fator)}[v]"
    mapas = ["-map", "[v]"]
    if audio:
        filtro += f";[0:a]{cadeia_atempo(fator)}[a]"
        mapas += ["-map", "[a]"]
    return _base(ffmpeg) + ["-i", str(entrada), "-filter_complex", filtro] + mapas + _codificar(qualidade, audio) + [str(saida)]


def bitrate_alvo(megabytes: float, duracao: float, audio_kbps: int = 96) -> tuple[int, int | None]:
    """Bitrate de vídeo (kbit/s) para caber em ``megabytes`` e a altura máxima que ainda fica nítida."""
    if duracao <= 0:
        raise ErroVideo("Não consegui saber a duração do vídeo.")
    total_kbits = megabytes * 8 * 1024 * 0.92  # 8% de folga para o contêiner
    video = int(total_kbits / duracao - audio_kbps)
    if video < 100:
        raise ErroVideo(f"Esse vídeo é longo demais para caber em {megabytes:g} MB com qualidade aceitável. "
                        "Corte um trecho antes.")
    altura = None if video >= 2500 else 720 if video >= 1000 else 480 if video >= 450 else 360
    return video, altura


def cmd_comprimir(ffmpeg: str, entrada: Path, saida: Path, megabytes: float, info: InfoVideo) -> list[str]:
    video, altura = bitrate_alvo(megabytes, info.duracao, 96 if info.tem_audio else 0)
    cmd = _base(ffmpeg) + ["-i", str(entrada), "-map", "0:v:0", "-map", "0:a:0?"]
    if altura and info.altura > altura:
        cmd += ["-vf", f"scale=-2:{altura}"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-b:v", f"{video}k", "-maxrate", f"{video}k",
            "-bufsize", f"{video * 2}k", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", "96k", "-ac", "2"] if info.tem_audio else ["-an"]
    return cmd + ["-movflags", "+faststart", str(saida)]


def cmd_converter(ffmpeg: str, entrada: Path, saida: Path, qualidade: str, audio: bool) -> list[str]:
    formato = saida.suffix.lower().lstrip(".")
    crf, preset, _ = QUALIDADES.get(qualidade, QUALIDADES["media"])
    cmd = _base(ffmpeg) + ["-i", str(entrada), "-map", "0:v:0", "-map", "0:a:0?"]
    if formato == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-crf", str(crf + 10), "-b:v", "0", "-row-mt", "1"]
        cmd += ["-c:a", "libopus", "-b:a", "128k"] if audio else ["-an"]
    elif formato == "avi":
        cmd += ["-c:v", "mpeg4", "-q:v", "4"]
        cmd += ["-c:a", "libmp3lame", "-q:a", "3"] if audio else ["-an"]
    else:
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
        cmd += ["-c:a", "aac", "-b:a", "160k"] if audio else ["-an"]
        if formato in ("mp4", "mov"):
            cmd += ["-movflags", "+faststart"]
    return cmd + [str(saida)]


def cmd_gif(ffmpeg: str, entrada: Path, saida: Path, inicio: float, fim: float, fps: int = 12,
            largura: int = 480) -> list[str]:
    filtro = (f"fps={fps},scale={largura}:-1:flags=lanczos,split[s0][s1];"
              "[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4")
    return _base(ffmpeg) + ["-ss", _num(inicio), "-t", _num(fim - inicio), "-i", str(entrada),
                            "-filter_complex", filtro, "-loop", "0", str(saida)]


def cmd_sem_audio(ffmpeg: str, entrada: Path, saida: Path) -> list[str]:
    return _base(ffmpeg) + ["-i", str(entrada), "-map", "0:v", "-c", "copy", "-an", str(saida)]


def cmd_vertical(ffmpeg: str, entrada: Path, saida: Path, modo: str, qualidade: str, audio: bool,
                 inicio: float | None = None, fim: float | None = None) -> list[str]:
    """9:16 (1080x1920). ``corte``: recorta o centro; ``fundo``: o vídeo inteiro sobre ele mesmo desfocado."""
    cmd = _base(ffmpeg)
    if inicio is not None and fim is not None:
        cmd += ["-ss", _num(inicio), "-t", _num(fim - inicio)]
    cmd += ["-i", str(entrada)]
    if modo == "fundo":
        filtro = ("[0:v]split=2[a][b];"
                  "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:2[f];"
                  "[b]scale=1080:1920:force_original_aspect_ratio=decrease[c];"
                  "[f][c]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
    else:
        filtro = "[0:v]crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)',scale=1080:1920,setsar=1[v]"
    cmd += ["-filter_complex", filtro, "-map", "[v]"]
    if audio:
        cmd += ["-map", "0:a:0?"]
    return cmd + _codificar(qualidade, audio) + [str(saida)]


def cmd_audio_para_transcrever(ffmpeg: str, entrada: Path, saida: Path) -> list[str]:
    return _base(ffmpeg) + ["-i", str(entrada), "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "16000",
                            "-c:a", "pcm_s16le", str(saida)]


ESTILO_LEGENDA = "FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=28"


def cmd_queimar_legenda(ffmpeg: str, entrada: Path, nome_srt: str, saida: Path, qualidade: str, audio: bool) -> list[str]:
    """Legenda dentro da imagem. ``nome_srt`` é relativo à pasta de trabalho (``cwd``): caminhos do Windows
    ("C:\\...") quebram a sintaxe do filtro ``subtitles``."""
    if not re.fullmatch(r"[\w.-]+", nome_srt):
        raise ValueError("nome de legenda inválido para o filtro")
    filtro = f"subtitles={nome_srt}:charenc=UTF-8:force_style='{ESTILO_LEGENDA}'"
    return (_base(ffmpeg) + ["-i", str(entrada), "-vf", filtro, "-map", "0:v:0", "-map", "0:a:0?"]
            + _codificar(qualidade, audio) + [str(saida)])


# -- legendas ----------------------------------------------------------------------------------------

def _tempo_srt(segundos: float) -> str:
    ms = int(round(max(0.0, segundos) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def blocos_legenda(segmentos: list[tuple[float, float, str]], max_linha: int = 42, max_linhas: int = 2
                   ) -> list[tuple[float, float, str]]:
    """Fala longa vira vários blocos de até 2 linhas de 42 caracteres (o tempo é dividido pelo tamanho)."""
    blocos = []
    limite = max_linha * max_linhas
    for inicio, fim, texto in segmentos:
        texto = " ".join(texto.split())
        if not texto or fim <= inicio:
            continue
        pedacos, atual = [], ""
        for palavra in texto.split():
            if atual and len(atual) + 1 + len(palavra) > limite:
                pedacos.append(atual)
                atual = palavra
            else:
                atual = f"{atual} {palavra}".strip()
        pedacos.append(atual)
        total = sum(len(p) for p in pedacos)
        t = inicio
        for p in pedacos:
            duracao = (fim - inicio) * len(p) / total
            linhas = textwrap.wrap(p, max_linha) or [p]
            blocos.append((t, t + duracao, "\n".join(linhas[:max_linhas])))
            t += duracao
    return blocos


def gerar_srt(blocos: list[tuple[float, float, str]]) -> str:
    return "\n".join(f"{i}\n{_tempo_srt(a)} --> {_tempo_srt(b)}\n{texto}\n" for i, (a, b, texto) in enumerate(blocos, 1))


def _alucinacao(texto: str) -> bool:
    try:
        from ..voz.transcricao import ALUCINACOES
    except Exception:  # noqa: BLE001
        return False
    baixo = texto.lower()
    return any(a in baixo for a in ALUCINACOES)


# -- HyperFrames ---------------------------------------------------------------------------------------

SISTEMA_HYPERFRAMES = """Você escreve composições do HyperFrames: um único arquivo index.html que o HyperFrames \
renderiza quadro a quadro num vídeo MP4 (Chrome sem interface + GSAP pausado e "seekado"). Responda SÓ com o \
HTML completo dentro de um bloco ```html, sem explicações.

Regras obrigatórias (o `npx hyperframes lint` reprova o que fugir delas):
1. Documento completo: <!doctype html>, <html lang="pt-BR">, <meta charset="UTF-8">, \
<meta name="viewport" content="width={largura}, height={altura}">.
2. Scripts externos: somente o GSAP, exatamente <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>. \
Nada mais vindo da internet: sem imagens, vídeos, áudios, fontes ou CSS externos. Desenhe com HTML, CSS, SVG e gradientes.
3. Fontes: só famílias genéricas (font-family: system-ui, sans-serif / serif / monospace). Nunca um nome de \
fonte sem @font-face (erro font_family_without_font_face).
4. Raiz direto no <body>, sem <template>: <div id="root" data-composition-id="main" data-start="0" \
data-width="{largura}" data-height="{altura}" data-duration="{duracao}">. No CSS: #root {{ position: relative; \
width: 100%; height: 100%; overflow: hidden; }} (nunca largura/altura fixas em px no #root). body {{ margin: 0; }} com fundo.
5. Cenas: filhos da raiz com class="clip", data-start e data-duration em segundos (ex.: data-start="0" \
data-duration="4"), position: absolute; inset: 0; todas terminando até {duracao} s. Ids únicos.
6. Animação: um único `const tl = gsap.timeline({{ paused: true }});`, todas as animações nele com posição \
absoluta em segundos (tl.from(..., 0.3), tl.to(..., 4.2)), e no FIM do script `window.__timelines["main"] = tl;`. \
Nunca tl.play(), nunca outra timeline.
7. Nunca anime um elemento .clip com autoAlpha, visibility ou display (erro gsap_animates_clip_element): anime \
os filhos (opacity, x, y, scale, rotation). O framework mostra e esconde as cenas sozinho; não esconda nada no fim.
8. Nunca combine transform no CSS com animação GSAP de transform no mesmo elemento (erro \
gsap_css_transform_conflict): defina o estado inicial no próprio tween (gsap fromTo/from). Centralize com \
flex/grid, nunca com translate(-50%,-50%).
9. Determinismo: proibido Date.now, performance.now, Math.random, fetch, setTimeout, setInterval, \
requestAnimationFrame, eventos de mouse/teclado. repeat: -1 é proibido; use repeat com número finito.
10. Sem <br> em texto corrido (use max-width e deixe quebrar); elementos animados com transform precisam ser \
display: block ou inline-block e ter tamanho. Sem <video> e sem <audio>.
11. Visual: texto em português do Brasil, grande e legível (títulos de {titulo_px}px ou mais), bom contraste, \
margem de segurança de 6% nas bordas, uma ideia por cena (uma cena a cada 3–5 s), entradas com easing \
(power3.out, back.out) e movimento contínuo em cada cena (algo sempre se mexendo, nada parado por mais de 2 s)."""

CORRIGIR_HYPERFRAMES = """O `npx hyperframes lint` reprovou a composição com estes problemas:
{problemas}

HTML atual:
```html
{html}
```
Corrija todos os problemas mantendo a ideia do vídeo e devolva o HTML completo."""


def extrair_html(resposta: str) -> str:
    """Tira o HTML da resposta do modelo (bloco ```html ou o documento solto)."""
    if m := re.search(r"```(?:html)?\s*\n(.*?)```", resposta or "", re.S | re.I):
        html = m.group(1)
    elif m := re.search(r"(<!doctype html.*?</html>|<html.*?</html>)", resposta or "", re.S | re.I):
        html = m.group(1)
    else:
        html = resposta or ""
    html = html.strip()
    if "data-composition-id" not in html or "</html>" not in html.lower():
        raise ErroVideo("O modelo não devolveu uma composição válida do HyperFrames.")
    return html + "\n"


def ler_lint(saida: str) -> tuple[bool, list[dict]]:
    """Saída do ``hyperframes lint --json`` -> (ok, problemas com severidade error/warning)."""
    inicio, fim = saida.find("{"), saida.rfind("}")
    if inicio < 0 or fim < inicio:
        raise ErroVideo("O hyperframes lint não respondeu em JSON.")
    try:
        dados = json.loads(saida[inicio:fim + 1])
    except json.JSONDecodeError as erro:
        raise ErroVideo(f"Não entendi a resposta do hyperframes lint: {erro}") from None
    if dados.get("error"):
        raise ErroVideo(f"O hyperframes lint falhou: {dados['error']}")
    problemas = [f for f in dados.get("findings") or [] if f.get("severity") in ("error", "warning")]
    erros = int(dados.get("errorCount") or sum(1 for f in problemas if f.get("severity") == "error"))
    return bool(dados.get("ok", erros == 0)) and erros == 0, problemas


def descrever_problemas(problemas: list[dict]) -> str:
    linhas = []
    for f in problemas[:25]:
        linha = f"- [{f.get('severity')}] {f.get('code')}: {f.get('message')}"
        if f.get("selector") or f.get("elementId"):
            linha += f" (em {f.get('selector') or '#' + str(f.get('elementId'))})"
        if f.get("fixHint"):
            linha += f" — dica: {f['fixHint']}"
        linhas.append(linha)
    return "\n".join(linhas)


def ler_progresso_render(linha: str) -> float | None:
    """``@hf-progress {"pct": 42, ...}`` (o render imprime isso quando a saída não é um terminal)."""
    linha = linha.strip()
    if linha.startswith("@hf-progress "):
        try:
            return max(0.0, min(1.0, float(json.loads(linha[len("@hf-progress "):]).get("pct", 0)) / 100))
        except (ValueError, TypeError, AttributeError):
            return None
    return None


def nome_projeto(briefing: str) -> str:
    palavras = [p for p in normalizar(briefing).split() if len(p) > 2][:5]
    base = "-".join(palavras)[:40].strip("-") or "video"
    return f"{datetime.now():%Y%m%d-%H%M%S}-{base}"


# -- programas externos --------------------------------------------------------------------------------

def localizar(programa: str) -> str | None:
    """Caminho do programa (ffmpeg, ffprobe, node, npx), também nas pastas onde o winget costuma instalar."""
    achado = shutil.which(programa)
    if achado:
        return achado
    if windows.WINDOWS:
        locais = os.environ.get("LOCALAPPDATA", "")
        candidatos = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / f"{programa}.cmd",
                      Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / f"{programa}.exe"]
        if locais:
            candidatos += list((Path(locais) / "Microsoft" / "WinGet" / "Links").glob(f"{programa}.exe"))
        for c in candidatos:
            if c.is_file():
                return str(c)
    return None


def versao_node(node: str | None) -> tuple[int, str] | None:
    if not node:
        return None
    try:
        r = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10,
                           creationflags=windows.SEM_JANELA)
    except (OSError, subprocess.SubprocessError):
        return None
    texto = (r.stdout or "").strip()
    m = re.match(r"v?(\d+)", texto)
    return (int(m.group(1)), texto) if m else None


def _ambiente_node() -> dict:
    env = dict(os.environ)
    env.update({"HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1", "FORCE_COLOR": "0", "NO_COLOR": "1",
                "npm_config_update_notifier": "false"})
    return env


# -- pastas, nomes e busca de vídeos -------------------------------------------------------------------

def _tamanho(n: float) -> str:
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unidade}" if unidade in ("B", "KB") else f"{n:.1f} {unidade}".replace(".", ",")
        n /= 1024
    return f"{n:.1f} TB".replace(".", ",")


def pasta_videos(app) -> Path:
    escolhida = str(app.prefs.get("videos_pasta") or "").strip() or os.environ.get("VIDEOS_PASTA", "").strip()
    if escolhida:
        return Path(os.path.expandvars(escolhida)).expanduser()
    return windows.pasta_conhecida("videos")


def pasta_saida(app) -> Path:
    return pasta_videos(app) / SUBPASTA_SAIDA


def _limpar_nome(nome: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", nome).strip(" .") or "video"


def saida_para(pasta: Path, base: str, sufixo: str, extensao: str) -> Path:
    """Nome novo e livre: "viagem (cortado).mp4", "viagem (cortado 2).mp4"..."""
    base = _limpar_nome(base)[:80]
    extensao = extensao if extensao.startswith(".") else f".{extensao}"
    candidato = pasta / (f"{base} ({sufixo}){extensao}" if sufixo else f"{base}{extensao}")
    n = 2
    while candidato.exists():
        candidato = pasta / (f"{base} ({sufixo} {n}){extensao}" if sufixo else f"{base} ({n}){extensao}")
        n += 1
    return candidato


def _varrer_videos(raiz: Path, limite: int = MAX_VARRER) -> list[tuple[float, Path]]:
    achados: list[tuple[float, Path]] = []
    pilha = [(raiz, 0)]
    while pilha and len(achados) < limite:
        pasta, nivel = pilha.pop()
        try:
            with os.scandir(pasta) as entradas:
                for e in entradas:
                    if e.name.startswith((".", "~$")):
                        continue
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if nivel < 4:
                                pilha.append((Path(e.path), nivel + 1))
                        elif os.path.splitext(e.name)[1].lower() in EXTENSOES_VIDEO:
                            achados.append((e.stat().st_mtime, Path(e.path)))
                    except OSError:
                        continue
        except OSError:
            continue
    return achados


_ULTIMO = re.compile(r"^(?:(?:o|a|um|meu|minha|esse|este|esta|essa)\s+)?(?:(?:ultim[oa]|mais recente)\s+)?"
                     r"(?:video|gravacao|clipe)?(?:\s+(?:mais recente|que eu gravei|que gravei|gravado))?$")
_GERADO = re.compile(r"^(?:o |a )?(?:ultim[oa] )?(?:video )?(?:que (?:voce|vc) (?:fez|gerou|criou|editou)|gerado|editado|criado)$")


def ultimos_videos(app, limite: int = 8) -> list[Path]:
    achados = {p: t for t, p in _varrer_videos(pasta_videos(app))}
    try:
        for a in app.arquivos.recentes(limite * 2, tipo="video"):
            achados.setdefault(Path(a.caminho), a.modificado)
    except Exception:  # noqa: BLE001 - o índice de arquivos é um extra
        pass
    return [p for p, _ in sorted(achados.items(), key=lambda par: par[1], reverse=True)[:limite]]


def resolver_video(app, alvo: str | None) -> Path:
    """Caminho, "o último vídeo", "o que você gerou" ou um nome para procurar (na pasta de vídeos e no índice)."""
    texto = (alvo or "").strip().strip('"')
    t = normalizar(texto)
    if _ULTIMO.match(t):
        recentes = ultimos_videos(app, 1)
        if not recentes:
            raise ErroVideo(f"Não achei nenhum vídeo em {pasta_videos(app)}.")
        return recentes[0]
    if _GERADO.match(t):
        for g in reversed(app.videos.gerados()):
            if g["tipo"] == "video" and Path(g["caminho"]).is_file():
                return Path(g["caminho"])
        raise ErroVideo("Ainda não gerei nenhum vídeo.")
    caminho = Path(texto).expanduser()
    if caminho.is_absolute():
        if caminho.is_file():
            return caminho
        raise ErroVideo(f"O arquivo {caminho} não existe.")
    from ..habilidades.arquivos import interpretar_consulta

    termos = [p for p in interpretar_consulta(texto).termos if p not in ("gravacao", "clipe")]
    if termos:
        from rapidfuzz import fuzz

        alvo_n = " ".join(termos)
        melhores = []
        for mtime, p in _varrer_videos(pasta_videos(app)):
            nome = normalizar(p.stem)
            nota = max(fuzz.token_set_ratio(alvo_n, nome), fuzz.partial_ratio(alvo_n, nome) - 5)
            if all(x in nome for x in termos):
                nota += 15
            if nota >= 70:
                melhores.append((nota, mtime, p))
        if melhores:
            return max(melhores)[2]
    try:
        achados = app.arquivos.buscar(texto, tipo="video", limite=1)
    except Exception:  # noqa: BLE001
        achados = []
    if achados:
        return Path(achados[0].caminho)
    raise ErroVideo(f"Não achei nenhum vídeo parecido com '{texto}'.")


# -- trabalhos em segundo plano ------------------------------------------------------------------------

@dataclass
class Trabalho:
    id: int
    tipo: str
    rotulo: str                      # "Cortando viagem.mp4"
    executar: Callable[["Trabalho"], list[Path]]
    canal: str = "voz"
    estado: str = "fila"             # fila | rodando | ok | erro | cancelado
    etapa: str = ""
    progresso: float = 0.0
    erro: str = ""
    saidas: list[Path] = field(default_factory=list)
    criado: float = field(default_factory=time.time)
    fim: float = 0.0
    faixa: tuple[float, float] = (0.0, 1.0)  # parte da barra que a etapa atual ocupa
    cancelar_pedido: bool = False
    processo: subprocess.Popen | None = None

    def para_dict(self) -> dict:
        return {"id": self.id, "tipo": self.tipo, "rotulo": self.rotulo, "estado": self.estado, "etapa": self.etapa,
                "progresso": round(self.progresso, 3), "erro": self.erro, "criado": self.criado,
                "saidas": [p.name for p in self.saidas]}


class GerenteVideos:
    """Fila de trabalhos de vídeo (um por vez), progresso ao vivo e os arquivos gerados."""

    def __init__(self, app, pasta_dados: Path) -> None:
        self.app = app
        self.pasta = pasta_dados
        self.arquivo_gerados = pasta_dados / "gerados.json"
        self._trabalhos: list[Trabalho] = []
        self._ids = itertools.count(1)
        self._lock = threading.RLock()
        self._tem_trabalho = threading.Condition(self._lock)
        self._rodando = False
        self._fio: threading.Thread | None = None
        self._ultimo_evento = 0.0
        self._gerados: list[dict] | None = None
        self._diag: tuple[float, list[dict]] | None = None

    # -- programas (substituíveis nos testes) --------------------------------------------------------
    def programa(self, nome: str) -> str:
        caminho = localizar(nome)
        if not caminho:
            raise ErroVideo(INSTALAR_FFMPEG if nome in ("ffmpeg", "ffprobe") else INSTALAR_NODE)
        return caminho

    def sondar(self, caminho: Path) -> InfoVideo:
        ffprobe = self.programa("ffprobe")
        try:
            r = subprocess.run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                                str(caminho)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=30, creationflags=windows.SEM_JANELA)
        except subprocess.TimeoutExpired:
            raise ErroVideo(f"O ffprobe demorou demais para ler {caminho.name}.") from None
        if r.returncode != 0:
            raise ErroVideo(f"Não consegui ler {caminho.name}: {(r.stderr or '').strip()[:200] or 'arquivo inválido'}.")
        info = ler_sonda(json.loads(r.stdout or "{}"))
        if not info.tem_video and not info.tem_audio:
            raise ErroVideo(f"{caminho.name} não tem vídeo nem áudio.")
        return info

    def rodar_processo(self, trabalho: Trabalho, cmd: list[str], *, cwd: Path | None = None,
                       ao_linha: Callable[[str], None] | None = None, env: dict | None = None) -> tuple[int, str, str]:
        """Roda e devolve (código, saída padrão, últimas linhas de erro). Cancelar mata o processo."""
        self._checar_cancelado(trabalho)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                cwd=str(cwd) if cwd else None, env=env, text=True, encoding="utf-8",
                                errors="replace", creationflags=windows.SEM_JANELA)
        trabalho.processo = proc
        erros: deque[str] = deque(maxlen=40)
        leitor = threading.Thread(target=lambda: erros.extend(proc.stderr), daemon=True)  # type: ignore[arg-type]
        leitor.start()
        saida: deque[str] = deque(maxlen=4000)
        try:
            for linha in proc.stdout:  # type: ignore[union-attr]
                saida.append(linha)
                if ao_linha:
                    ao_linha(linha)
            proc.wait()
        finally:
            leitor.join(timeout=5)
            trabalho.processo = None
        self._checar_cancelado(trabalho)
        return proc.returncode, "".join(saida), "".join(erros).strip()

    def transcrever(self, trabalho: Trabalho, wav: Path, idioma: str | None, duracao: float
                    ) -> list[tuple[float, float, str]]:
        """Whisper do próprio PC, 30 s por vez (entre um trecho e outro, os comandos de voz continuam passando)."""
        import wave

        import numpy as np

        transcritor = getattr(self.app, "transcritor", None)
        if transcritor is None:
            raise ErroVideo("O Whisper não está disponível nesta instalação.")
        try:
            transcritor.carregar()
        except Exception as erro:  # noqa: BLE001
            raise ErroVideo(f"Não consegui carregar o Whisper: {erro}") from None
        with wave.open(str(wav), "rb") as arquivo:
            audio = np.frombuffer(arquivo.readframes(arquivo.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        passo = 16000 * TRECHO_LEGENDA_S
        segmentos: list[tuple[float, float, str]] = []
        total = max(1, len(audio))
        modelo, trava = transcritor._modelo, transcritor._lock
        for inicio in range(0, len(audio), passo):
            self._checar_cancelado(trabalho)
            pedaco = audio[inicio:inicio + passo]
            if pedaco.size < 16000 * 0.3:
                break
            deslocamento = inicio / 16000
            with trava:
                partes, _ = modelo.transcribe(pedaco, language=idioma, beam_size=5 if transcritor.dispositivo == "cuda" else 2,
                                              vad_filter=True, condition_on_previous_text=False)
                for s in partes:
                    texto = s.text.strip()
                    if texto and not (s.no_speech_prob > 0.75 and s.avg_logprob < -0.8) and not _alucinacao(texto):
                        segmentos.append((s.start + deslocamento, min(s.end + deslocamento, duracao or s.end + deslocamento), texto))
            self.progresso(trabalho, min(1.0, (inicio + passo) / total))
        return segmentos

    # -- fila ----------------------------------------------------------------------------------------
    def iniciar(self) -> None:
        with self._lock:
            if self._rodando:
                return
            self._rodando = True
        self._fio = threading.Thread(target=self._laco, name="videos", daemon=True)
        self._fio.start()

    def encerrar(self) -> None:
        with self._lock:
            self._rodando = False
            for t in self._trabalhos:
                if t.estado in ("fila", "rodando"):
                    self._cancelar(t)
            self._tem_trabalho.notify_all()

    def enfileirar(self, tipo: str, rotulo: str, executar: Callable[[Trabalho], list[Path]], canal: str = "voz") -> Trabalho:
        trabalho = Trabalho(next(self._ids), tipo, rotulo, executar, canal)
        with self._lock:
            self._trabalhos.append(trabalho)
            self._trabalhos = [t for t in self._trabalhos if t.estado in ("fila", "rodando")] + \
                [t for t in self._trabalhos if t.estado not in ("fila", "rodando")][-10:]
            self._tem_trabalho.notify_all()
        self._publicar(forcar=True)
        return trabalho

    def ocupado(self) -> bool:
        with self._lock:
            return any(t.estado in ("fila", "rodando") for t in self._trabalhos)

    def _laco(self) -> None:
        while True:
            with self._lock:
                while self._rodando and not any(t.estado == "fila" for t in self._trabalhos):
                    self._tem_trabalho.wait(timeout=5)
                if not self._rodando:
                    return
                trabalho = next(t for t in self._trabalhos if t.estado == "fila")
                trabalho.estado = "rodando"
            self.executar(trabalho)

    def executar(self, trabalho: Trabalho) -> None:
        """Roda um trabalho até o fim (a fila chama; os testes chamam direto)."""
        trabalho.estado = "rodando"
        self._publicar(forcar=True)
        try:
            saidas = trabalho.executar(trabalho)
            trabalho.saidas = [s for s in saidas if s.is_file()]
            if not trabalho.saidas:
                raise ErroVideo("O arquivo de saída não foi criado.")
            trabalho.estado, trabalho.progresso, trabalho.etapa = "ok", 1.0, ""
            for s in trabalho.saidas:
                self.registrar_gerado(s, trabalho.tipo)
        except Cancelado:
            trabalho.estado, trabalho.etapa = "cancelado", ""
        except Exception as erro:  # noqa: BLE001 - erro vira aviso, a fila continua
            if not isinstance(erro, ErroVideo):
                log.exception("Erro no trabalho de vídeo %s", trabalho.rotulo)
            trabalho.estado, trabalho.erro, trabalho.etapa = "erro", str(erro) or erro.__class__.__name__, ""
        trabalho.fim = time.time()
        self._publicar(forcar=True)
        self._avisar(trabalho)

    def _avisar(self, trabalho: Trabalho) -> None:
        app = self.app
        if trabalho.estado == "ok":
            nome = trabalho.saidas[-1].name
            texto = f"Pronto: {nome} está na pasta {pasta_saida(app).name} dos seus vídeos."
            nivel = "sucesso"
        elif trabalho.estado == "erro":
            texto = f"Não consegui terminar: {trabalho.rotulo.lower()}. {trabalho.erro}"
            nivel = "erro"
        else:
            return
        try:
            app.barramento.publicar("aviso", nivel=nivel, texto=texto)
            if trabalho.canal == "celular":
                from ..habilidades.notificacoes import notificar

                notificar(app, texto, titulo="Vídeos")
            else:
                app.fala.falar(texto if trabalho.estado == "ok" else f"Não consegui terminar o vídeo. {trabalho.erro}")
        except Exception:  # noqa: BLE001
            log.exception("Não consegui avisar o fim do trabalho de vídeo")

    def cancelar(self, id_: int | None = None) -> Trabalho | None:
        with self._lock:
            ativos = [t for t in self._trabalhos if t.estado in ("fila", "rodando")]
            alvo = next((t for t in ativos if t.id == id_), None) if id_ else (ativos[-1] if ativos else None)
            if alvo is None:
                return None
            self._cancelar(alvo)
        self._publicar(forcar=True)
        return alvo

    def _cancelar(self, trabalho: Trabalho) -> None:
        trabalho.cancelar_pedido = True
        if trabalho.estado == "fila":
            trabalho.estado = "cancelado"
        proc = trabalho.processo
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    @staticmethod
    def _checar_cancelado(trabalho: Trabalho) -> None:
        if trabalho.cancelar_pedido:
            raise Cancelado()

    # -- progresso -----------------------------------------------------------------------------------
    def etapa(self, trabalho: Trabalho, nome: str, de: float, ate: float) -> None:
        trabalho.etapa, trabalho.faixa = nome, (de, ate)
        trabalho.progresso = max(trabalho.progresso, de)
        self._publicar(forcar=True)

    def progresso(self, trabalho: Trabalho, fracao: float) -> None:
        de, ate = trabalho.faixa
        trabalho.progresso = max(trabalho.progresso, de + (ate - de) * max(0.0, min(1.0, fracao)))
        self._publicar()

    def ffmpeg(self, trabalho: Trabalho, cmd: list[str], duracao: float, *, cwd: Path | None = None) -> None:
        def linha(texto: str) -> None:
            fracao = ler_progresso(texto, duracao)
            if fracao is not None:
                self.progresso(trabalho, fracao)

        saida = Path(cmd[-1])
        try:
            codigo, _, erros = self.rodar_processo(trabalho, cmd, cwd=cwd, ao_linha=linha)
        except Cancelado:
            _apagar_parcial(saida)
            raise
        if codigo != 0:
            _apagar_parcial(saida)
            ultima = erros.splitlines()[-1] if erros else f"código {codigo}"
            raise ErroVideo(f"O ffmpeg falhou: {ultima[:300]}")

    def _publicar(self, forcar: bool = False) -> None:
        agora = time.monotonic()
        if not forcar and agora - self._ultimo_evento < ATUALIZAR_S:
            return
        self._ultimo_evento = agora
        trabalhos = self.trabalhos()
        try:
            self.app.barramento.publicar("video.trabalhos", trabalhos=trabalhos)
            if forcar and self.app.hologramas.aberto("videos"):
                self.app.hologramas.atualizar_tipo("videos", self.estado())
        except Exception:  # noqa: BLE001
            log.exception("Não consegui publicar o progresso dos vídeos")

    # -- estado e gerados ----------------------------------------------------------------------------
    def trabalhos(self) -> list[dict]:
        with self._lock:
            return [t.para_dict() for t in self._trabalhos]

    def gerados(self) -> list[dict]:
        with self._lock:
            if self._gerados is None:
                try:
                    dados = json.loads(self.arquivo_gerados.read_text(encoding="utf-8"))
                    self._gerados = [g for g in dados if isinstance(g, dict) and "id" in g and "caminho" in g]
                except (OSError, ValueError):
                    self._gerados = []
            return list(self._gerados)

    def registrar_gerado(self, caminho: Path, origem: str) -> dict:
        tipo = TIPO_POR_EXTENSAO.get(caminho.suffix.lower(), "video")
        with self._lock:
            gerados = self.gerados()
            proximo = max((int(g["id"]) for g in gerados), default=0) + 1
            item = {"id": proximo, "caminho": str(caminho), "nome": caminho.name, "tipo": tipo, "origem": origem,
                    "criado": time.time(), "tamanho": _tamanho(caminho.stat().st_size)}
            self._gerados = (gerados + [item])[-MAX_GERADOS:]
            try:
                self.pasta.mkdir(parents=True, exist_ok=True)
                self.arquivo_gerados.write_text(json.dumps(self._gerados, ensure_ascii=False, indent=1), encoding="utf-8")
            except OSError as erro:
                log.warning("Não consegui salvar a lista de vídeos gerados: %s", erro)
        return item

    def gerado(self, id_: int) -> Path | None:
        for g in self.gerados():
            if int(g["id"]) == id_:
                caminho = Path(g["caminho"])
                return caminho if caminho.is_file() else None
        return None

    def estado(self) -> dict:
        gerados = [{**g, "existe": Path(g["caminho"]).is_file()} for g in reversed(self.gerados())][:12]
        return {"trabalhos": self.trabalhos(), "gerados": gerados, "pasta": str(pasta_saida(self.app))}


def _apagar_parcial(caminho: Path) -> None:
    """Só apaga a saída que o próprio trabalho começou a escrever (nunca um original)."""
    try:
        if caminho.is_file():
            caminho.unlink()
    except OSError:
        pass


# -- os pedidos ----------------------------------------------------------------------------------------

ACOES_EDICAO = ["cortar", "juntar", "extrair_audio", "velocidade", "comprimir", "converter", "gif", "sem_audio",
                "vertical"]
VERBOS = {"cortar": "Cortando", "juntar": "Juntando", "extrair_audio": "Extraindo o áudio de",
          "velocidade": "Mudando a velocidade de", "comprimir": "Comprimindo", "converter": "Convertendo",
          "gif": "Fazendo um GIF de", "sem_audio": "Tirando o áudio de", "vertical": "Fazendo o corte vertical de",
          "legendas": "Legendando", "criar": "Criando"}


def _qualidade(app) -> str:
    q = str(app.prefs.get("videos_qualidade") or "media")
    return q if q in QUALIDADES else "media"


def _intervalo(trecho: str | None, inicio: str | None, fim: str | None) -> Intervalo | None:
    if trecho:
        intervalo = interpretar_intervalo(trecho)
        if intervalo is None:
            raise ErroVideo(f"Não entendi o trecho '{trecho}'. Diga, por exemplo: do 0:30 ao 1:15.")
        return intervalo
    if inicio is None and fim is None:
        return None
    a = interpretar_tempo(inicio) if inicio not in (None, "") else 0.0
    b = interpretar_tempo(fim) if fim not in (None, "") else None
    if a is None or (fim not in (None, "") and b is None):
        raise ErroVideo("Não entendi os tempos. Use, por exemplo, 0:30 e 1:15.")
    return Intervalo(a, b)


def _destino_mb(destino: str | None, tamanho_mb: float | None) -> tuple[float, str]:
    if tamanho_mb:
        if not 1 <= tamanho_mb <= 4000:
            raise ErroVideo("Escolha um tamanho entre 1 e 4000 MB.")
        return float(tamanho_mb), f"{tamanho_mb:g} MB"
    chave = normalizar(destino or "whatsapp").replace(" ", "")
    if m := re.fullmatch(r"(\d+(?:\.\d+)?)mb", chave):
        return float(m.group(1)), f"{m.group(1)} MB"
    for nome, mb in DESTINOS_MB.items():
        if nome in chave:
            return float(mb), {"whatsapp": "WhatsApp", "email": "e-mail"}.get(nome, nome.capitalize())
    raise ErroVideo("Para onde? WhatsApp, Discord, e-mail, Telegram ou um tamanho em MB.")


def editar(app, ctx, acao: str, video: str | None = None, videos: list | None = None, trecho: str | None = None,
           inicio: str | None = None, fim: str | None = None, fator: float | None = None, destino: str | None = None,
           tamanho_mb: float | None = None, formato: str | None = None, modo: str | None = None) -> dict:
    """Valida o pedido, monta a(s) linha(s) do ffmpeg e põe na fila. Devolve na hora (o fim é avisado)."""
    gerente: GerenteVideos = app.videos
    if acao not in ACOES_EDICAO:
        return {"ok": False, "resumo": f"Não sei fazer '{acao}' com vídeos."}
    ffmpeg = gerente.programa("ffmpeg")
    qualidade = _qualidade(app)
    pasta = pasta_saida(app)
    if acao == "juntar":
        nomes = [str(v) for v in (videos or []) if str(v).strip()]
        if len(nomes) < 2:
            return {"ok": False, "resumo": "Quais vídeos eu junto? Diga pelo menos dois."}
        entradas = [(c, gerente.sondar(c)) for c in (resolver_video(app, n) for n in nomes[:20])]
        if any(not info.tem_video for _, info in entradas):
            return {"ok": False, "resumo": "Um dos arquivos não tem imagem; só junto vídeos."}
        saida = saida_para(pasta, entradas[0][0].stem, "juntos", ".mp4")
        duracao = sum(info.duracao for _, info in entradas)
        comandos = [(cmd_juntar(ffmpeg, entradas, saida, qualidade), duracao)]
        rotulo = f"Juntando {len(entradas)} vídeos"
        resposta = f"Vou juntar {len(entradas)} vídeos ({', '.join(c.name for c, _ in entradas)}). Aviso quando terminar."
        return _enfileirar(app, ctx, acao, rotulo, pasta, comandos, resposta)

    origem = resolver_video(app, video)
    info = gerente.sondar(origem)
    if not info.tem_video and acao not in ("extrair_audio", "converter"):
        return {"ok": False, "resumo": f"{origem.name} não tem imagem, só áudio."}
    intervalo = _intervalo(trecho, inicio, fim)
    base = origem.stem
    comandos: list[tuple[list[str], float]]
    detalhe = ""
    if acao == "cortar":
        if intervalo is None:
            return {"ok": False, "resumo": "De que ponto a que ponto? Por exemplo: do 0:30 ao 1:15."}
        a, b = intervalo.resolver(info.duracao)
        saida = saida_para(pasta, base, "cortado", ".mp4")
        comandos = [(cmd_cortar(ffmpeg, origem, saida, a, b, qualidade, info.tem_audio), b - a)]
        detalhe = f" do {formatar_tempo(a)} ao {formatar_tempo(b)}"
    elif acao == "extrair_audio":
        if not info.tem_audio:
            return {"ok": False, "resumo": f"{origem.name} não tem áudio."}
        ext = (formato or "mp3").lower().lstrip(".")
        ext = ext if ext in FORMATOS_AUDIO else "mp3"
        saida = saida_para(pasta, base, "áudio", f".{ext}")
        comandos = [(cmd_extrair_audio(ffmpeg, origem, saida), info.duracao)]
    elif acao == "velocidade":
        f = float(fator or 2.0)
        if not 0.25 <= f <= 4:
            return {"ok": False, "resumo": "A velocidade precisa ficar entre 0,25x e 4x."}
        if abs(f - 1) < 0.01:
            return {"ok": False, "resumo": "Essa já é a velocidade normal."}
        saida = saida_para(pasta, base, f"{_num(f).replace('.', ',')}x", ".mp4")
        comandos = [(cmd_velocidade(ffmpeg, origem, saida, f, info.tem_audio, qualidade), info.duracao / f)]
        detalhe = f" em {_num(f).replace('.', ',')}x"
    elif acao == "comprimir":
        mb, nome_destino = _destino_mb(destino, tamanho_mb)
        if info.tamanho and info.tamanho <= mb * 1024 * 1024 * 0.95:
            return {"ok": True, "resumo": f"{origem.name} já tem {_tamanho(info.tamanho)} e cabe no {nome_destino}."}
        saida = saida_para(pasta, base, "comprimido", ".mp4")
        comandos = [(cmd_comprimir(ffmpeg, origem, saida, mb, info), info.duracao)]
        detalhe = f" para caber no {nome_destino} ({mb:g} MB)"
    elif acao == "converter":
        ext = (formato or "").lower().lstrip(".")
        if ext == "gif":
            return editar(app, ctx, "gif", video=str(origem), trecho=trecho, inicio=inicio, fim=fim)
        if ext in FORMATOS_AUDIO:
            return editar(app, ctx, "extrair_audio", video=str(origem), formato=ext)
        if ext not in FORMATOS_VIDEO:
            return {"ok": False, "resumo": f"Para qual formato? Sei converter para {', '.join(FORMATOS_VIDEO)}, gif e mp3."}
        if origem.suffix.lower() == f".{ext}":
            return {"ok": False, "resumo": f"{origem.name} já está em {ext.upper()}."}
        saida = saida_para(pasta, base, "", f".{ext}")
        comandos = [(cmd_converter(ffmpeg, origem, saida, qualidade, info.tem_audio), info.duracao)]
        detalhe = f" para {ext.upper()}"
    elif acao == "gif":
        if intervalo is None:
            a, b = 0.0, min(info.duracao or GIF_PADRAO_S, GIF_PADRAO_S)
            detalhe = f" com os primeiros {int(round(b))} segundos" if info.duracao > GIF_PADRAO_S else ""
        else:
            a, b = intervalo.resolver(info.duracao)
            if b - a > 30:
                return {"ok": False, "resumo": "GIF com mais de 30 segundos fica enorme. Escolha um trecho menor."}
            detalhe = f" do {formatar_tempo(a)} ao {formatar_tempo(b)}"
        saida = saida_para(pasta, base, "", ".gif")
        comandos = [(cmd_gif(ffmpeg, origem, saida, a, b), b - a)]
    elif acao == "sem_audio":
        if not info.tem_audio:
            return {"ok": False, "resumo": f"{origem.name} já não tem áudio."}
        saida = saida_para(pasta, base, "sem áudio", origem.suffix.lower() if origem.suffix.lower() in EXTENSOES_VIDEO else ".mp4")
        comandos = [(cmd_sem_audio(ffmpeg, origem, saida), info.duracao)]
    else:  # vertical
        modo = "fundo" if normalizar(modo or "") in ("fundo", "desfocado", "inteiro", "fundo desfocado", "blur") else "corte"
        a = b = None
        duracao = info.duracao
        if intervalo is not None:
            a, b = intervalo.resolver(info.duracao)
            duracao = b - a
            detalhe = f" do {formatar_tempo(a)} ao {formatar_tempo(b)}"
        saida = saida_para(pasta, base, "vertical", ".mp4")
        comandos = [(cmd_vertical(ffmpeg, origem, saida, modo, qualidade, info.tem_audio, a, b), duracao)]
        detalhe += ", com fundo desfocado" if modo == "fundo" else ", recortando o centro"
    rotulo = f"{VERBOS[acao]} {origem.name}"
    resposta = f"{VERBOS[acao]} {origem.name}{detalhe}. Aviso quando terminar."
    return _enfileirar(app, ctx, acao, rotulo, pasta, comandos, resposta)


def _enfileirar(app, ctx, acao: str, rotulo: str, pasta: Path, comandos: list[tuple[list[str], float]],
                resposta: str) -> dict:
    gerente: GerenteVideos = app.videos
    pasta.mkdir(parents=True, exist_ok=True)

    def executar(trabalho: Trabalho) -> list[Path]:
        saidas = []
        for i, (cmd, duracao) in enumerate(comandos):
            gerente.etapa(trabalho, "Processando", i / len(comandos), (i + 1) / len(comandos))
            gerente.ffmpeg(trabalho, cmd, duracao)
            saidas.append(Path(cmd[-1]))
        return saidas

    if gerente.ocupado():
        resposta = resposta.replace(" Aviso quando", " Está na fila; aviso quando")
    trabalho = gerente.enfileirar(acao, rotulo, executar, ctx.canal)
    return {"ok": True, "resumo": resposta, "trabalho": trabalho.id, "saida": comandos[-1][0][-1]}


def legendar(app, ctx, video: str | None = None, queimar: bool = False, idioma: str | None = None) -> dict:
    gerente: GerenteVideos = app.videos
    ffmpeg = gerente.programa("ffmpeg")
    origem = resolver_video(app, video)
    info = gerente.sondar(origem)
    if not info.tem_audio:
        return {"ok": False, "resumo": f"{origem.name} não tem áudio para legendar."}
    if queimar and not info.tem_video:
        queimar = False
    idioma = (idioma or "pt").lower()[:2] if idioma != "auto" else None
    pasta = pasta_saida(app)
    pasta.mkdir(parents=True, exist_ok=True)
    srt = saida_para(pasta, origem.stem, "", ".srt")
    saida_video = saida_para(pasta, origem.stem, "legendado", ".mp4") if queimar else None
    qualidade = _qualidade(app)
    temporaria = gerente.pasta / "tmp"

    def executar(trabalho: Trabalho) -> list[Path]:
        temporaria.mkdir(parents=True, exist_ok=True)
        wav = temporaria / f"audio_{trabalho.id}.wav"
        _apagar_parcial(wav)
        try:
            gerente.etapa(trabalho, "Separando o áudio", 0.0, 0.1)
            gerente.ffmpeg(trabalho, cmd_audio_para_transcrever(ffmpeg, origem, wav), info.duracao)
            gerente.etapa(trabalho, "Transcrevendo com o Whisper", 0.1, 0.7 if queimar else 1.0)
            segmentos = gerente.transcrever(trabalho, wav, idioma, info.duracao)
        finally:
            _apagar_parcial(wav)
        if not segmentos:
            raise ErroVideo("Não ouvi fala nenhuma no vídeo.")
        srt.write_text(gerar_srt(blocos_legenda(segmentos)), encoding="utf-8")
        if not queimar:
            return [srt]
        nome = f"legenda_{trabalho.id}.srt"
        copia = temporaria / nome
        shutil.copyfile(srt, copia)
        try:
            gerente.etapa(trabalho, "Colocando a legenda no vídeo", 0.7, 1.0)
            gerente.ffmpeg(trabalho, cmd_queimar_legenda(ffmpeg, origem, nome, saida_video, qualidade, info.tem_audio),
                           info.duracao, cwd=temporaria)
        finally:
            _apagar_parcial(copia)
        return [srt, saida_video]

    trabalho = gerente.enfileirar("legendas", f"Legendando {origem.name}", executar, ctx.canal)
    como = "e coloco a legenda no vídeo" if queimar else "e gero o arquivo de legenda .srt"
    resposta = f"Vou transcrever {origem.name} ({formatar_tempo(info.duracao)}) com o Whisper {como}. Aviso quando terminar."
    return {"ok": True, "resumo": resposta, "trabalho": trabalho.id, "saida": str(saida_video or srt)}


def criar(app, ctx, briefing: str, duracao: float | None = None, formato: str | None = None, nome: str | None = None) -> dict:
    """Cria um vídeo novo com o HyperFrames: o cérebro escreve o HTML, o lint confere e o render gera o MP4."""
    gerente: GerenteVideos = app.videos
    briefing = (briefing or "").strip()
    if len(briefing) < 3:
        return {"ok": False, "resumo": "Sobre o que é o vídeo? Me dê o texto ou a ideia."}
    npx = gerente.programa("npx")
    gerente.programa("ffmpeg")  # o render do HyperFrames também usa o FFmpeg
    segundos = float(duracao or 0) or (interpretar_tempo(_duracao_no_texto(briefing) or "") or 15.0)
    segundos = max(3.0, min(120.0, round(segundos)))
    proporcao = formato if formato in PROPORCOES else _proporcao_no_texto(briefing)
    largura, altura = PROPORCOES[proporcao]
    projeto = gerente.pasta / _limpar_nome(nome or nome_projeto(briefing))
    pasta = pasta_saida(app)
    pasta.mkdir(parents=True, exist_ok=True)
    saida = saida_para(pasta, nome or _titulo_arquivo(briefing), "", ".mp4")
    qualidade_render = QUALIDADES[_qualidade(app)][2]
    sistema = SISTEMA_HYPERFRAMES.format(largura=largura, altura=altura, duracao=_num(segundos),
                                         titulo_px=110 if altura >= 1080 else 80)
    pedido = (f"Briefing do usuário: {briefing}\n\nDuração total: {_num(segundos)} segundos.\n"
              f"Formato: {largura}x{altura} ({proporcao}).")

    def executar(trabalho: Trabalho) -> list[Path]:
        projeto.mkdir(parents=True, exist_ok=True)
        indice = projeto / "index.html"
        (projeto / "briefing.txt").write_text(pedido, encoding="utf-8")
        gerente.etapa(trabalho, "Escrevendo a composição", 0.0, 0.15)
        html = extrair_html(app.agente.completar(sistema, pedido, rapido=False))
        env = _ambiente_node()
        for tentativa in range(TENTATIVAS_LINT + 1):
            indice.write_text(html, encoding="utf-8")
            gerente.etapa(trabalho, "Conferindo (hyperframes lint)", 0.15 + 0.05 * tentativa, 0.2 + 0.05 * tentativa)
            _, texto, erros = gerente.rodar_processo(trabalho, [npx, "--yes", "hyperframes", "lint", "--json", str(projeto)],
                                                     cwd=projeto, env=env)
            try:
                ok, problemas = ler_lint(texto)
            except ErroVideo:
                raise ErroVideo(f"O hyperframes lint falhou: {(erros or texto).strip()[-300:] or 'sem resposta'}") from None
            if ok:
                break
            if tentativa == TENTATIVAS_LINT:
                raise ErroVideo("A composição continuou com erros depois de 2 correções: "
                                + "; ".join(str(p.get("code")) for p in problemas if p.get("severity") == "error")[:300])
            gerente.etapa(trabalho, "Corrigindo a composição", 0.2 + 0.05 * tentativa, 0.25 + 0.05 * tentativa)
            html = extrair_html(app.agente.completar(
                sistema, CORRIGIR_HYPERFRAMES.format(problemas=descrever_problemas(problemas), html=html), rapido=False))
        gerente.etapa(trabalho, "Renderizando (hyperframes render)", 0.3, 1.0)

        def linha(texto: str) -> None:
            fracao = ler_progresso_render(texto)
            if fracao is not None:
                gerente.progresso(trabalho, fracao)

        try:
            codigo, texto, erros = gerente.rodar_processo(
                trabalho, [npx, "--yes", "hyperframes", "render", str(projeto), "--output", str(saida),
                           "--quality", qualidade_render, "--fps", "30"], cwd=projeto, ao_linha=linha, env=env)
        except Cancelado:
            _apagar_parcial(saida)
            raise
        if codigo != 0 or not saida.is_file():
            detalhe = (erros or texto).strip().splitlines()
            raise ErroVideo(f"O hyperframes render falhou: {detalhe[-1][:300] if detalhe else f'código {codigo}'}")
        return [saida]

    rotulo = f"Criando {saida.name}"
    trabalho = gerente.enfileirar("criar", rotulo, executar, ctx.canal)
    resposta = (f"Vou criar um vídeo de {int(segundos)} segundos em {proporcao} com o HyperFrames. "
                "Escrevo a animação, confiro e renderizo; aviso quando terminar.")
    return {"ok": True, "resumo": resposta, "trabalho": trabalho.id, "projeto": str(projeto), "saida": str(saida)}


def _duracao_no_texto(texto: str) -> str | None:
    m = re.search(rf"\b(?:de|com|em)\s+(\d+(?:\.\d+)?\s*(?:{_RE_UNIDADE}))\b", _norm(texto))
    if m:
        return m.group(1)
    t = _preparar_tempo(texto)
    m = re.search(rf"\b(\d+(?:\.\d+)?\s*(?:segundos?|minutos?|s))\b", t)
    return m.group(1) if m else None


def _proporcao_no_texto(texto: str) -> str:
    t = normalizar(texto)
    if re.search(r"\b(vertical|9:16|9 16|tiktok|reels?|shorts?|stories|story)\b", t):
        return "9:16"
    if re.search(r"\b(quadrado|1:1|feed do instagram)\b", t):
        return "1:1"
    return "16:9"


def _titulo_arquivo(briefing: str) -> str:
    palavras = re.sub(r"[^\w\s-]", " ", briefing).split()
    return " ".join(palavras[:6])[:60] or "vídeo"


def descrever_trabalhos(app) -> str:
    trabalhos = app.videos.trabalhos()
    ativos = [t for t in trabalhos if t["estado"] in ("fila", "rodando")]
    if not ativos:
        ultimos = [t for t in trabalhos if t["estado"] in ("ok", "erro")]
        if not ultimos:
            return "Nenhum trabalho de vídeo agora."
        t = ultimos[-1]
        return (f"Nada rodando. O último ({t['rotulo'].lower()}) terminou "
                + ("bem." if t["estado"] == "ok" else f"com erro: {t['erro']}"))
    partes = []
    for t in ativos:
        if t["estado"] == "rodando":
            partes.append(f"{t['rotulo']}: {int(t['progresso'] * 100)}%" + (f" ({t['etapa'].lower()})" if t["etapa"] else ""))
        else:
            partes.append(f"{t['rotulo']}: na fila")
    return ". ".join(partes) + "."


# -- ganchos da extensão -------------------------------------------------------------------------------

def instalar(app) -> None:
    app.videos = GerenteVideos(app, app.cfg.dados / "videos")


def _seguro(funcao: Callable[[], dict]) -> dict:
    try:
        return funcao()
    except ErroVideo as erro:
        return {"ok": False, "resumo": str(erro)}


def registrar(app, registro) -> None:
    @registro.ferramenta(
        "video_editar",
        "Edita um vídeo do usuário com o ffmpeg, em segundo plano, gerando SEMPRE um arquivo novo (o original fica "
        "intacto) na pasta Vídeos/Sexta-Feira. Ações: cortar (trecho), juntar (videos), extrair_audio (formato mp3/m4a/"
        "wav), velocidade (fator 0.25–4: 2 = 2x mais rápido, 0.5 = câmera lenta), comprimir (destino whatsapp/discord/"
        "email/telegram ou tamanho_mb), converter (formato mp4/webm/mkv/mov/avi/gif/mp3), gif (trecho opcional), "
        "sem_audio, vertical (9:16 para Shorts/Reels; modo corte ou fundo desfocado; trecho opcional). O vídeo pode "
        "ser um nome ('viagem'), um caminho, 'o último vídeo' ou 'o que você gerou'. Responde na hora; o fim é avisado.",
        direta=True, nivel=LIVRE,
        acao=P("string", "O que fazer.", enum=ACOES_EDICAO, obrigatorio=True),
        video=P("string", "Nome, caminho ou 'o último vídeo'."),
        videos=P("array", "Para juntar: os vídeos na ordem.", itens={"type": "string"}),
        trecho=P("string", "Trecho em linguagem natural: 'do 0:30 ao 1:15', 'do minuto 2 ao 3', 'primeiros 10 segundos'."),
        inicio=P("string", "Alternativa ao trecho: início ('0:30', '30 segundos')."),
        fim=P("string", "Alternativa ao trecho: fim ('1:15')."),
        fator=P("number", "Velocidade: 2 = duas vezes mais rápido, 0.5 = metade."),
        destino=P("string", "Comprimir para: whatsapp, discord, email ou telegram."),
        tamanho_mb=P("number", "Comprimir para este tamanho em MB."),
        formato=P("string", "converter/extrair_audio: formato de saída."),
        modo=P("string", "vertical: 'corte' (centro) ou 'fundo' (vídeo inteiro com fundo desfocado)."),
    )
    def video_editar(ctx, acao: str, **kwargs):
        return _seguro(lambda: editar(app, ctx, acao, **kwargs))

    @registro.ferramenta(
        "video_legendas",
        "Legendas automáticas: transcreve a fala do vídeo no próprio PC (Whisper), gera o arquivo .srt e, com "
        "queimar=true, também um vídeo novo com a legenda na imagem. Em segundo plano; o fim é avisado.",
        direta=True, nivel=LIVRE,
        video=P("string", "Nome, caminho ou 'o último vídeo'.", obrigatorio=True),
        queimar=P("boolean", "true = legenda dentro da imagem (vídeo novo); false = só o .srt."),
        idioma=P("string", "Idioma da fala (pt, en, es...) ou 'auto'. Padrão: pt."),
    )
    def video_legendas(ctx, video: str, queimar: bool = False, idioma: str | None = None):
        return _seguro(lambda: legendar(app, ctx, video, queimar, idioma))

    @registro.ferramenta(
        "video_criar",
        "Cria um vídeo animado novo do zero (intro, vinheta, anúncio, título animado, texto animado) com o HyperFrames "
        "(HTML + GSAP renderizado em MP4). Passe o briefing completo com os textos que devem aparecer. Em segundo "
        "plano; o MP4 vai para Vídeos/Sexta-Feira e o fim é avisado.",
        direta=True, nivel=LIVRE,
        briefing=P("string", "O que o vídeo deve mostrar: textos, estilo, cores, clima.", obrigatorio=True),
        duracao=P("number", "Duração em segundos (3–120). Padrão: 15."),
        formato=P("string", "Proporção.", enum=list(PROPORCOES)),
        nome=P("string", "Nome do arquivo (opcional)."),
    )
    def video_criar(ctx, briefing: str, duracao: float | None = None, formato: str | None = None, nome: str | None = None):
        return _seguro(lambda: criar(app, ctx, briefing, duracao, formato, nome))

    @registro.ferramenta(
        "video_trabalhos",
        "Trabalhos de vídeo: status (o que está rodando e quanto falta), cancelar (o trabalho em andamento), "
        "mostrar (abre o holograma Vídeos), abrir_ultimo (abre o último arquivo gerado), pasta (mostra a pasta).",
        direta=True, nivel=LIVRE,
        acao=P("string", "Ação.", enum=["status", "cancelar", "mostrar", "abrir_ultimo", "pasta"], obrigatorio=True),
    )
    def video_trabalhos(ctx, acao: str):
        gerente: GerenteVideos = app.videos
        if acao == "status":
            return {"ok": True, "resumo": descrever_trabalhos(app), "trabalhos": gerente.trabalhos()}
        if acao == "cancelar":
            alvo = gerente.cancelar()
            return {"ok": alvo is not None,
                    "resumo": f"Cancelei: {alvo.rotulo.lower()}." if alvo else "Não há trabalho de vídeo rodando."}
        if acao == "mostrar":
            app.hologramas.mostrar("videos", gerente.estado())
            return {"ok": True, "resumo": "Aqui estão seus vídeos."}
        try:
            if acao == "abrir_ultimo":
                gerados = [g for g in gerente.gerados() if Path(g["caminho"]).is_file()]
                if not gerados:
                    return {"ok": False, "resumo": "Ainda não gerei nenhum arquivo de vídeo."}
                windows.abrir_no_sistema(gerados[-1]["caminho"])
                return {"ok": True, "resumo": f"Abrindo {gerados[-1]['nome']}."}
            pasta = pasta_saida(app)
            pasta.mkdir(parents=True, exist_ok=True)
            windows.abrir_no_sistema(str(pasta))
            return {"ok": True, "resumo": "Abrindo a pasta dos vídeos gerados."}
        except (OSError, windows.NaoSuportado) as erro:
            return {"ok": False, "resumo": f"Não consegui abrir: {erro}"}

    @registro.ferramenta(
        "video_info",
        "Informações de vídeos: info (duração, resolução, áudio e tamanho de um vídeo) ou listar (os vídeos mais "
        "recentes da pasta Vídeos).",
        direta=True, nivel=LIVRE,
        acao=P("string", "Ação.", enum=["info", "listar"], obrigatorio=True),
        video=P("string", "Para info: nome, caminho ou 'o último vídeo'."),
    )
    def video_info(ctx, acao: str, video: str | None = None):
        def fazer() -> dict:
            if acao == "listar":
                recentes = ultimos_videos(app, 8)
                if not recentes:
                    return {"ok": True, "resumo": f"Não achei vídeos em {pasta_videos(app)}."}
                nomes = [p.name for p in recentes]
                return {"ok": True, "resumo": f"Seus vídeos mais recentes: {', '.join(nomes[:5])}.",
                        "videos": [str(p) for p in recentes]}
            caminho = resolver_video(app, video)
            info = app.videos.sondar(caminho)
            return {"ok": True, "resumo": f"{caminho.name}: {info.descricao()}.", "caminho": str(caminho)}
        return _seguro(fazer)


# -- atalhos sem IA ------------------------------------------------------------------------------------

_V = r"(?:o |um |meu |esse |este )?(?:ultimo |mais recente )?(?:video|arquivo|clipe)"
_ALVO = r"(?P<alvo>.*?)"
_CORTAR = re.compile(rf"^(?:corta|corte|cortar|recorta|recorte|apara)\s+{_V}\b\s*(?P<resto>.+)$")
_INICIO_TRECHO = re.compile(r"\b(?:do|de|da|dos|desde|entre|a partir|so|somente|apenas|deixando|"
                            r"os primeiros|os ultimos|primeiros|ultimos|ate)\b")
_CORTAR_TRECHO = re.compile(rf"^(?:corta|corte|recorta|pega|separa|extrai)\s+(?:o trecho|um trecho|so o trecho|a parte)\s+"
                            rf"(?P<trecho>.+?)\s+d[oa]\s+(?:video|arquivo|clipe)\s*{_ALVO}$")
_EXTRAIR_AUDIO = re.compile(rf"^(?:extrai|extraia|extrair|separa|separe|salva|salve|pega|exporta)\s+(?:o |so o )?(?:audio|som)"
                            rf"\s+d[oa]\s+(?:video\s+)?{_ALVO}(?:\s+(?:em|para|pra|como)\s+(?P<formato>mp3|m4a|wav))?$")
_SEM_AUDIO = re.compile(rf"^(?:tira|tire|remove|remova|apaga|corta)\s+(?:o |todo o )?(?:audio|som)\s+d[oa]\s+(?:video\s+)?{_ALVO}$")
_SEM_AUDIO_2 = re.compile(rf"^(?:deixa|deixe|coloca|poe)\s+{_V}\s*{_ALVO}\s+(?:sem (?:audio|som)|mudo)$")
_COMPRIMIR = re.compile(rf"^(?:comprime|comprima|comprimir|compacta|compacte|diminui|diminua|reduz|reduza|encolhe)\s+"
                        rf"(?:o tamanho d[oa]\s+)?{_V}\s*{_ALVO}"
                        r"(?:\s+(?:para|pra|pro|ate)\s+(?:o |a |mandar no |enviar no |caber no |mandar pelo |o tamanho do )?"
                        r"(?P<destino>whatsapp|zap|discord|email|e mail|telegram|\d+(?:[.,]\d+)?\s*(?:mb|mega|megas)))?$")
_CONVERTER = re.compile(rf"^(?:converte|converta|converter|transforma|transforme|passa|salva)\s+{_V}\s*{_ALVO}\s+"
                        r"(?:para|pra|em)\s+(?:o formato\s+|um\s+|uma\s+)?(?P<formato>mp4|webm|mkv|mov|avi|gif|mp3|m4a|wav)$")
_GIF = re.compile(r"^(?:faz|faca|fazer|cria|crie|gera|gere|monta)\s+(?:um |uma )?gif\s+d[oa]\s+(?:video\s+)?(?P<resto>.+)$")
_VELOCIDADE = re.compile(rf"^(?P<verbo>acelera|acelere|desacelera|desacelere)\s+{_V}\s*{_ALVO}"
                         r"(?:\s+(?:em|para|pra|ate)\s+(?P<fator>\d+(?:[., ]\d+)?)\s*(?:x|vezes))?$")
_LENTA = re.compile(rf"^(?:deixa|deixe|coloca|poe|faz|faca)\s+{_V}\s*{_ALVO}\s+(?:em )?(?:camera lenta|slow motion|mais lento)$")
_LEGENDAS = re.compile(rf"^(?P<verbo>coloca|coloque|poe|ponha|bota|adiciona|adicione|queima|gera|gere|cria|crie|faz|faca|transcreve)\s+"
                       rf"(?:a |as |uma )?(?:legendas?|legendagem)(?:\s+automaticas?)?\s+(?:n[oa]|para o|pro|do|da|em)\s+"
                       rf"(?:video\s+)?{_ALVO}(?:\s+em\s+(?P<idioma>ingles|espanhol|portugues))?$")
_LEGENDAR = re.compile(rf"^legenda\s+{_V}\s*{_ALVO}$")
_VERTICAL = re.compile(rf"^(?:faz|faca|fazer|cria|crie|gera|gere|transforma|transforme|deixa|deixe|corta|recorta|converte|passa)\s+"
                       r"(?:um |uma |o |a )?(?:corte |versao |video |recorte )?(?:em |no formato |para o formato |pra )?"
                       r"(?:vertical|9:16|9 16|para (?:o )?(?:tiktok|reels|shorts)|pro (?:tiktok|reels|shorts))\s+"
                       r"(?:d[oa]\s+)?(?:video\s+)?(?P<resto>.+?)"
                       r"(?:\s+(?P<fundo>com (?:o )?fundo(?: desfocado)?|inteiro|sem cortar))?$")
_VERTICAL_2 = re.compile(rf"^(?:deixa|deixe|transforma|transforme|converte|passa)\s+{_V}\s*{_ALVO}\s+"
                         r"(?:em |para |pra )?(?:vertical|9:16|9 16)$")
_JUNTAR = re.compile(r"^(?:junta|junte|juntar|une|una|unir|emenda|emende|concatena)\s+(?:os |esses |estes )?(?:videos?|arquivos)\s+(?P<lista>.+)$")
_CRIAR = re.compile(r"^(?:cria|crie|criar|faz|faca|fazer|gera|gere|monta|monte|produz)\s+(?:pra mim |para mim )?(?:um|uma)\s+"
                    r"(?:(?:pequeno|pequena|curto|curta|rapido|rapida|novo|nova)\s+)?"
                    r"(?:video|intro|vinheta|abertura|animacao|introducao)\b(?P<resto>.*)$")
_MOSTRAR = re.compile(r"^(?:mostra|mostre|abre|abra|exibe)\s+(?:o |os |a |as )?(?:holograma |painel |tela )?(?:de |dos |das )?"
                      r"(?:meus )?(?:videos(?: gerados| editados)?|trabalhos de video|edicoes de video|renderizacoes)$")
_STATUS = re.compile(r"^(?:como (?:esta|estao|ta|tao)|qual (?:e )?o (?:status|progresso) d[oa]s?|quanto falta (?:pr[oa]|para o|para a)?)\s*"
                     r"(?:o |a |os |as )?(?:meu |minha )?(?:video|videos|renderizacao|edicao|legenda|legendas|corte|gif|trabalho de video)$")
_CANCELAR = re.compile(r"^(?:(?:cancela|cancele|interrompe|aborta)\s+(?:o |a )?(?:video|renderizacao|edicao|"
                       r"trabalho de video|corte|legendagem|render)|para (?:de )?(?:renderizar|a renderizacao|a edicao))$")
_ABRIR_ULTIMO = re.compile(r"^(?:abre|abra|toca|mostra|reproduz)\s+(?:o )?(?:ultimo )?(?:video|arquivo) (?:que voce (?:gerou|fez|editou|criou)|gerado)$")

_ALVO_VAZIO = {"", "o", "a", "ele", "isso", "esse", "este"}
_IDIOMAS = {"ingles": "en", "espanhol": "es", "portugues": "pt"}


def _video_do_alvo(alvo: str) -> str:
    alvo = re.sub(r"^(?:chamado|chamada|com nome|de nome|do|da|de)\s+", "", (alvo or "").strip())
    return "o último vídeo" if alvo in _ALVO_VAZIO else alvo


def _separar_lista(texto: str) -> list[str]:
    partes = re.split(r"\s*,\s*|\s+e\s+(?:o\s+|depois o\s+)?|\s+com\s+(?:o\s+)?", texto)
    return [_video_do_alvo(re.sub(r"^(?:o |a |video )+", "", p).strip()) for p in partes if p.strip()]


def separar_trecho(resto: str) -> tuple[str, str | None]:
    """ "casamento do 0:30 ao 1:15" -> ("casamento", "do 0:30 ao 1:15"): o trecho é o primeiro sufixo que vira
    um intervalo de tempo (assim "do casamento" continua sendo parte do nome)."""
    for m in _INICIO_TRECHO.finditer(resto):
        trecho = resto[m.start():]
        if interpretar_intervalo(trecho) is not None:
            return resto[:m.start()].strip(), trecho
    return resto.strip(), None


def atalho(t: str, ctx, rodar, original: str | None):
    editar_ = lambda args: rodar("video_editar", args)  # noqa: E731
    if m := _CORTAR_TRECHO.match(t):
        if interpretar_intervalo(m.group("trecho")) is not None:
            return editar_({"acao": "cortar", "video": _video_do_alvo(m.group("alvo")), "trecho": m.group("trecho")})
    if m := _CORTAR.match(t):
        alvo, trecho = separar_trecho(m.group("resto"))
        if trecho is not None:
            return editar_({"acao": "cortar", "video": _video_do_alvo(alvo), "trecho": trecho})
    if m := _EXTRAIR_AUDIO.match(t):
        return editar_({"acao": "extrair_audio", "video": _video_do_alvo(m.group("alvo")),
                        "formato": m.group("formato") or "mp3"})
    if m := _SEM_AUDIO.match(t) or _SEM_AUDIO_2.match(t):
        return editar_({"acao": "sem_audio", "video": _video_do_alvo(m.group("alvo"))})
    if m := _COMPRIMIR.match(t):
        destino = (m.group("destino") or "whatsapp").replace("zap", "whatsapp")
        destino = re.sub(r"\s*(?:mega|megas)$", "mb", destino)
        return editar_({"acao": "comprimir", "video": _video_do_alvo(m.group("alvo")), "destino": destino})
    if m := _CONVERTER.match(t):
        return editar_({"acao": "converter", "video": _video_do_alvo(m.group("alvo")), "formato": m.group("formato")})
    if m := _GIF.match(t):
        alvo, trecho = separar_trecho(m.group("resto"))
        args = {"acao": "gif", "video": _video_do_alvo(alvo)}
        if trecho:
            args["trecho"] = trecho
        return editar_(args)
    if m := _VELOCIDADE.match(t):
        desacelera = m.group("verbo").startswith("desacel")
        fator = float(re.sub(r"[, ]", ".", m.group("fator"))) if m.group("fator") else 2.0
        if desacelera and fator > 1:
            fator = 1 / fator
        return editar_({"acao": "velocidade", "video": _video_do_alvo(m.group("alvo")), "fator": fator})
    if m := _LENTA.match(t):
        return editar_({"acao": "velocidade", "video": _video_do_alvo(m.group("alvo")), "fator": 0.5})
    if m := _LEGENDAS.match(t):
        queimar = m.group("verbo") in ("coloca", "coloque", "poe", "ponha", "bota", "adiciona", "adicione", "queima")
        args = {"video": _video_do_alvo(m.group("alvo")), "queimar": queimar}
        if m.group("idioma"):
            args["idioma"] = _IDIOMAS[m.group("idioma")]
        return rodar("video_legendas", args)
    if m := _LEGENDAR.match(t):
        return rodar("video_legendas", {"video": _video_do_alvo(m.group("alvo")), "queimar": True})
    if m := _VERTICAL.match(t):
        alvo, trecho = separar_trecho(m.group("resto"))
        fundo = m.group("fundo")
        if trecho and (f := re.search(r"\s+(com (?:o )?fundo(?: desfocado)?|inteiro|sem cortar)$", trecho)):
            trecho, fundo = trecho[:f.start()], f.group(1)
        args = {"acao": "vertical", "video": _video_do_alvo(alvo), "modo": "fundo" if fundo else "corte"}
        if trecho:
            args["trecho"] = trecho
        return editar_(args)
    if m := _VERTICAL_2.match(t):
        return editar_({"acao": "vertical", "video": _video_do_alvo(m.group("alvo")), "modo": "corte"})
    if m := _JUNTAR.match(t):
        lista = _separar_lista(m.group("lista"))
        if len(lista) >= 2:
            return editar_({"acao": "juntar", "videos": lista})
    if m := _CRIAR.match(t):
        resto = m.group("resto").strip()
        if not re.match(r"^(?:vertical|9 16|9:16)?\s*(?:d[oa]s?|com o video|a partir d[oa])\b", resto) and len(resto) > 3:
            briefing = remover_ativacao(original) if original else t
            return rodar("video_criar", {"briefing": briefing or t})
    if _MOSTRAR.match(t):
        return rodar("video_trabalhos", {"acao": "mostrar"})
    if _STATUS.match(t):
        return rodar("video_trabalhos", {"acao": "status"})
    if _CANCELAR.match(t):
        return rodar("video_trabalhos", {"acao": "cancelar"})
    if _ABRIR_ULTIMO.match(t):
        return rodar("video_trabalhos", {"acao": "abrir_ultimo"})
    return None


# -- HUD -----------------------------------------------------------------------------------------------

def rotas(api, app, autenticado, so_pc) -> None:
    import asyncio

    from fastapi import Body, Depends, HTTPException
    from fastapi.responses import FileResponse

    gerente: GerenteVideos = app.videos

    @api.get("/api/videos/estado")
    async def estado_videos(_=Depends(autenticado)):
        return await asyncio.to_thread(gerente.estado)

    @api.get("/api/videos/arquivo/{id_}")
    async def arquivo_video(id_: int, cliente=Depends(autenticado)):
        """Serve só os arquivos que a própria Sexta-Feira gerou (prévia no holograma)."""
        if cliente.tipo == "pc" and app.sessao.bloqueada:
            raise HTTPException(423, "A Sexta-Feira está bloqueada.")
        caminho = await asyncio.to_thread(gerente.gerado, id_)
        if caminho is None:
            raise HTTPException(404, "Arquivo não encontrado.")
        return FileResponse(caminho, media_type=MIDIA.get(caminho.suffix.lower(), "application/octet-stream"),
                            filename=caminho.name, content_disposition_type="inline")

    @api.post("/api/videos/abrir")
    async def abrir_video(corpo: dict = Body(...), _=Depends(so_pc)):
        if app.sessao.bloqueada:
            raise HTTPException(423, "A Sexta-Feira está bloqueada. Olhe para a câmera ou use o PIN.")
        try:
            id_ = int(corpo.get("id"))
        except (TypeError, ValueError):
            raise HTTPException(400, "Arquivo inválido.") from None
        caminho = await asyncio.to_thread(gerente.gerado, id_)
        if caminho is None:
            raise HTTPException(404, "Esse arquivo não existe mais.")
        try:
            if corpo.get("pasta"):
                await asyncio.to_thread(app.arquivos.mostrar_na_pasta, str(caminho))
                return {"texto": f"Mostrando {caminho.name} na pasta."}
            await asyncio.to_thread(windows.abrir_no_sistema, str(caminho))
        except windows.NaoSuportado as erro:
            raise HTTPException(501, str(erro)) from None
        except Exception as erro:  # noqa: BLE001
            raise HTTPException(500, f"Não consegui abrir: {erro}") from None
        return {"texto": f"Abrindo {caminho.name}."}

    @api.post("/api/videos/cancelar")
    async def cancelar_video(corpo: dict = Body(default={}), _=Depends(autenticado)):
        try:
            id_ = int(corpo.get("id")) if corpo.get("id") is not None else None
        except (TypeError, ValueError):
            id_ = None
        alvo = gerente.cancelar(id_)
        return {"texto": f"Cancelado: {alvo.rotulo}." if alvo else "Nada para cancelar.", "estado": gerente.estado()}

    @api.get("/api/videos/diagnostico")
    async def diagnostico_videos(_=Depends(so_pc)):
        return await asyncio.to_thread(diagnostico, app, True)


def dados_holograma(app, tipo: str) -> dict | None:
    return app.videos.estado() if tipo == "videos" else None


def diagnostico(app, forcar: bool = False) -> list[dict]:
    gerente: GerenteVideos = app.videos
    if not forcar and gerente._diag and time.monotonic() - gerente._diag[0] < 600:
        return gerente._diag[1]
    itens = []
    for nome in ("ffmpeg", "ffprobe"):
        caminho = localizar(nome)
        itens.append({"nome": f"Vídeos: {nome}", "ok": bool(caminho), "detalhe": caminho or "não encontrado",
                      "dica": "" if caminho else INSTALAR_FFMPEG})
    node = localizar("node")
    versao = versao_node(node)
    ok_node = bool(versao and versao[0] >= NODE_MINIMO)
    itens.append({"nome": "Vídeos: Node.js (HyperFrames)", "ok": ok_node,
                  "detalhe": versao[1] if versao else "não encontrado",
                  "dica": "" if ok_node else INSTALAR_NODE})
    npx = localizar("npx")
    if npx and ok_node:
        try:
            r = subprocess.run([npx, "--no-install", "hyperframes", "--version"], capture_output=True, text=True,
                               timeout=30, env=_ambiente_node(), creationflags=windows.SEM_JANELA)
            instalado = r.returncode == 0
            detalhe = (r.stdout or "").strip().splitlines()[-1] if instalado and r.stdout.strip() else ""
        except (OSError, subprocess.SubprocessError):
            instalado, detalhe = False, ""
        itens.append({"nome": "Vídeos: npx hyperframes", "ok": True,
                      "detalhe": f"instalado {detalhe}".strip() if instalado else "baixa sozinho no primeiro vídeo criado",
                      "dica": "" if instalado else "Para deixar pronto: npm install -g hyperframes"})
    else:
        itens.append({"nome": "Vídeos: npx hyperframes", "ok": False, "detalhe": "precisa do Node.js 22+",
                      "dica": INSTALAR_NODE})
    try:
        import faster_whisper  # noqa: F401

        whisper = True
    except Exception:  # noqa: BLE001
        whisper = False
    itens.append({"nome": "Vídeos: legendas (Whisper)", "ok": whisper,
                  "detalhe": "faster-whisper instalado" if whisper else "faster-whisper ausente",
                  "dica": "" if whisper else "pip install faster-whisper"})
    pasta = pasta_videos(app)
    itens.append({"nome": "Vídeos: pasta", "ok": pasta.is_dir(), "detalhe": str(pasta),
                  "dica": "" if pasta.is_dir() else "Escolha a pasta em Ajustes → Vídeos (ou VIDEOS_PASTA no .env)"})
    gerente._diag = (time.monotonic(), itens)
    return itens


def iniciar(app) -> None:
    app.videos.iniciar()


def encerrar(app) -> None:
    app.videos.encerrar()
