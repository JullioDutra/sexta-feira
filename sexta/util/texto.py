"""Utilidades de texto: normalização, limpeza para fala e divisão em frases."""

from __future__ import annotations

import re
import unicodedata

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\U00002B00-\U00002BFF️‍]+"
)
_URL = re.compile(r"https?://\S+|www\.\S+")
_LINK_MD = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_ABREVIACOES = {"sr", "sra", "srta", "dr", "dra", "prof", "profa", "etc", "av", "obs", "pág", "pag", "nº", "no", "vs", "ex"}


def sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos, sem pontuação, espaços simples."""
    texto = sem_acentos(texto.lower())
    texto = re.sub(r"[^a-z0-9:/\s]", " ", texto.replace("-", " "))
    return re.sub(r"\s+", " ", texto).strip()


def limpar_para_fala(texto: str) -> str:
    """Remove markdown, emojis e URLs para o texto soar natural na voz."""
    texto = _LINK_MD.sub(r"\1", texto)
    texto = _URL.sub("o link", texto)
    texto = re.sub(r"```.*?```", " ", texto, flags=re.S)
    texto = re.sub(r"[*_`#>|~]+", "", texto)
    texto = re.sub(r"^\s*[-•]\s+", "", texto, flags=re.M)
    texto = re.sub(r"^\s*\d+\.\s+", "", texto, flags=re.M)
    texto = _EMOJI.sub("", texto)
    texto = texto.replace("°C", " graus").replace("ºC", " graus").replace("°", " graus")
    texto = texto.replace("km/h", " quilômetros por hora")
    return re.sub(r"\s+", " ", texto).strip()


def remover_ativacao(texto: str) -> str:
    """Tira o nome da assistente do começo da transcrição.

    "Sexta-feira, que horas são?" -> "que horas são?"
    "Ei, Sexta, abre o Spotify" -> "abre o Spotify"
    """
    padrao = re.compile(
        r"^\s*(?:(?:ei|ok|ol[aá]|oi|e a[ií])[\s,!.]+)?"
        r"(?:sexta[\s\-]*feira|sexta(?=\s*[,!.?:]))[\s,!.?:;\-]*",
        re.IGNORECASE,
    )
    return padrao.sub("", texto, count=1).strip()


def so_ativacao(texto: str) -> bool:
    """Verdadeiro se a transcrição é só o nome (ex.: "Sexta-feira?")."""
    resto = normalizar(texto)
    return resto in {"", "sexta feira", "sexta", "ei sexta feira", "ei sexta", "oi sexta feira", "ok sexta feira"}


class DivisorFrases:
    """Recebe texto em pedaços (streaming) e devolve frases completas para a voz."""

    def __init__(self, minimo: int = 18, maximo: int = 220) -> None:
        self.buffer = ""
        self.minimo = minimo
        self.maximo = maximo

    def alimentar(self, pedaco: str) -> list[str]:
        self.buffer += pedaco
        frases: list[str] = []
        while True:
            corte = self._achar_corte()
            if corte is None:
                break
            frase, self.buffer = self.buffer[:corte].strip(), self.buffer[corte:]
            if frase:
                frases.append(frase)
        return frases

    def finalizar(self) -> list[str]:
        resto, self.buffer = self.buffer.strip(), ""
        return [resto] if resto else []

    def _achar_corte(self) -> int | None:
        buf = self.buffer
        for m in re.finditer(r"([.!?…]+)[\"')\]]?(\s+)|\n+", buf):
            fim = m.end()
            if m.group(0).startswith("\n"):
                if buf[: m.start()].strip():
                    return fim
                continue
            antes = buf[: m.start()]
            ultima_palavra = re.split(r"\s+", antes.strip())[-1].lower() if antes.strip() else ""
            if ultima_palavra.rstrip(".") in _ABREVIACOES:
                continue
            if re.search(r"\d$", antes) and m.group(1) == "." and re.match(r"\d", buf[fim:fim + 1] or ""):
                continue  # número decimal "23. 5" improvável, mas por segurança
            if len(antes.strip()) < self.minimo:
                continue  # frase curta demais: junta com a próxima
            return fim
        if len(buf) > self.maximo:
            virgula = buf.rfind(", ", self.minimo, self.maximo)
            if virgula > 0:
                return virgula + 2
        return None
