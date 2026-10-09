"""Arquivos do usuário: buscar, abrir, mover, renomear, organizar e listar recentes.

A busca usa um índice próprio das pastas pessoais (Área de Trabalho, Documentos,
Downloads, Imagens, Músicas, Vídeos e OneDrive), refeito em segundo plano a cada
15 minutos. Assim "acha o PDF do contrato de março" responde em milissegundos,
sem depender do indexador do Windows.

Por segurança, mover, renomear e apagar só valem dentro da pasta do usuário.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ..util.texto import normalizar
from . import windows

log = logging.getLogger(__name__)

TIPOS: dict[str, set[str]] = {
    "pdf": {".pdf"},
    "documento": {".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pdf"},
    "word": {".doc", ".docx"},
    "planilha": {".xls", ".xlsx", ".xlsm", ".ods", ".csv"},
    "apresentacao": {".ppt", ".pptx", ".odp"},
    "imagem": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".svg"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv"},
    "musica": {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"},
    "compactado": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "instalador": {".exe", ".msi", ".msix", ".appx"},
    "codigo": {".py", ".js", ".ts", ".tsx", ".java", ".c", ".cpp", ".cs", ".html", ".css", ".json", ".sql"},
    "modelo 3d": {".stl", ".obj", ".glb", ".gltf", ".fbx", ".3mf"},
}
# palavras faladas -> tipo
PALAVRAS_TIPO = {
    "pdf": "pdf", "pdfs": "pdf", "documento": "documento", "documentos": "documento", "doc": "word", "word": "word",
    "planilha": "planilha", "planilhas": "planilha", "excel": "planilha", "csv": "planilha",
    "apresentacao": "apresentacao", "apresentacoes": "apresentacao", "slides": "apresentacao", "powerpoint": "apresentacao",
    "foto": "imagem", "fotos": "imagem", "imagem": "imagem", "imagens": "imagem", "print": "imagem", "prints": "imagem",
    "video": "video", "videos": "video", "musica": "musica", "musicas": "musica", "audio": "musica",
    "zip": "compactado", "rar": "compactado", "compactado": "compactado", "instalador": "instalador",
    "instaladores": "instalador", "codigo": "codigo", "modelo 3d": "modelo 3d", "stl": "modelo 3d",
}
# pastas do organizador de Downloads
PASTAS_ORGANIZAR = {
    "imagem": "Imagens", "video": "Vídeos", "musica": "Músicas", "pdf": "PDFs", "word": "Documentos",
    "documento": "Documentos", "planilha": "Planilhas", "apresentacao": "Apresentações", "compactado": "Compactados",
    "instalador": "Instaladores", "codigo": "Código", "modelo 3d": "Modelos 3D",
}
MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
         "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
IGNORAR_PASTAS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "appdata", "$recycle.bin", ".cache",
                  "site-packages", "dist", "build", ".idea", ".vs", "obj", "bin"}
PALAVRAS_VAZIAS = {"o", "a", "os", "as", "de", "do", "da", "dos", "das", "meu", "minha", "meus", "minhas", "um",
                   "uma", "que", "eu", "arquivo", "arquivos", "pasta", "acha", "achar", "encontra", "encontrar",
                   "procura", "procurar", "busca", "buscar", "abre", "abrir", "cade", "onde", "esta", "ta", "e",
                   "no", "na", "em", "com", "sobre", "chamado", "chamada", "ultimo", "ultima", "mais", "recente"}
MAX_ARQUIVOS = 250_000


@dataclass
class Arquivo:
    caminho: str
    nome: str          # normalizado, sem extensão
    ext: str
    modificado: float
    tamanho: int

    def para_dict(self) -> dict:
        return {"caminho": self.caminho, "nome": Path(self.caminho).name, "pasta": str(Path(self.caminho).parent),
                "modificado": datetime.fromtimestamp(self.modificado).strftime("%d/%m/%Y %H:%M"),
                "tamanho": _tamanho(self.tamanho)}


class ErroArquivos(Exception):
    pass


class Arquivos:
    REINDEXAR_S = 15 * 60

    def __init__(self, pastas_extras: list[str] | None = None) -> None:
        self.pastas_extras = [Path(p).expanduser() for p in (pastas_extras or []) if p]
        self._indice: list[Arquivo] = []
        self._indexado_em = 0.0
        self._lock = threading.Lock()
        self._indexando = threading.Lock()
        self.ultima_busca: list[Arquivo] = []

    # -- pastas -------------------------------------------------------------
    def raizes(self) -> list[Path]:
        pastas = []
        for nome in ("area de trabalho", "documentos", "downloads", "imagens", "musicas", "videos"):
            try:
                pastas.append(windows.pasta_conhecida(nome))
            except Exception:  # noqa: BLE001
                continue
        onedrive = os.environ.get("OneDrive")
        if onedrive:
            pastas.append(Path(onedrive))
        pastas += self.pastas_extras
        unicas: list[Path] = []
        for p in pastas:
            if p.is_dir() and not any(_dentro(p, u) for u in unicas):
                unicas = [u for u in unicas if not _dentro(u, p)] + [p]
        return unicas

    def pasta_downloads(self) -> Path:
        return windows.pasta_conhecida("downloads")

    # -- índice -------------------------------------------------------------
    def indexar(self) -> int:
        if not self._indexando.acquire(blocking=False):
            return len(self._indice)
        try:
            inicio = time.monotonic()
            itens: list[Arquivo] = []
            for raiz in self.raizes():
                self._varrer(raiz, itens)
                if len(itens) >= MAX_ARQUIVOS:
                    break
            with self._lock:
                self._indice = itens
                self._indexado_em = time.time()
            log.info("Índice de arquivos: %d itens em %.1fs", len(itens), time.monotonic() - inicio)
            return len(itens)
        finally:
            self._indexando.release()

    def _varrer(self, raiz: Path, itens: list[Arquivo]) -> None:
        pilha = [raiz]
        while pilha and len(itens) < MAX_ARQUIVOS:
            pasta = pilha.pop()
            try:
                with os.scandir(pasta) as entradas:
                    for e in entradas:
                        nome = e.name
                        if nome.startswith((".", "~$")):
                            continue
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if nome.lower() not in IGNORAR_PASTAS:
                                    pilha.append(Path(e.path))
                                continue
                            st = e.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        base, ext = os.path.splitext(nome)
                        itens.append(Arquivo(e.path, normalizar(base), ext.lower(), st.st_mtime, st.st_size))
            except OSError:
                continue

    def garantir_indice(self) -> None:
        if not self._indice:
            self.indexar()
        elif time.time() - self._indexado_em > self.REINDEXAR_S:
            threading.Thread(target=self.indexar, daemon=True).start()

    def iniciar(self) -> None:
        threading.Thread(target=self.indexar, name="indice-arquivos", daemon=True).start()

    # -- busca --------------------------------------------------------------
    def buscar(self, consulta: str, tipo: str | None = None, limite: int = 5) -> list[Arquivo]:
        self.garantir_indice()
        filtro = interpretar_consulta(consulta, tipo)
        with self._lock:
            candidatos = [a for a in self._indice if filtro.aceita(a)]
        termos = filtro.termos
        if not termos:
            achados = sorted(candidatos, key=lambda a: a.modificado, reverse=True)[:limite]
        else:
            from rapidfuzz import fuzz

            alvo = " ".join(termos)
            notas = []
            for a in candidatos:
                nota = max(fuzz.token_set_ratio(alvo, a.nome), fuzz.partial_ratio(alvo, a.nome) - 5)
                if all(t in a.nome for t in termos):
                    nota += 15
                if nota >= 70:
                    notas.append((nota, a.modificado, a))
            notas.sort(key=lambda n: (n[0], n[1]), reverse=True)
            achados = [n[2] for n in notas[:limite]]
        self.ultima_busca = achados
        return achados

    def recentes(self, limite: int = 8, tipo: str | None = None) -> list[Arquivo]:
        self.garantir_indice()
        extensoes = TIPOS.get(tipo or "", None)
        with self._lock:
            itens = [a for a in self._indice if extensoes is None or a.ext in extensoes]
        achados = sorted(itens, key=lambda a: a.modificado, reverse=True)[:limite]
        self.ultima_busca = achados
        return achados

    def resolver(self, alvo: str) -> Path:
        """Aceita caminho, número da última busca ("1", "o segundo") ou um nome para buscar."""
        alvo = (alvo or "").strip().strip('"')
        indice = _ordinal(alvo)
        if indice is not None:
            if indice == -1 and self.ultima_busca:
                indice = len(self.ultima_busca) - 1
            if 0 <= indice < len(self.ultima_busca):
                return Path(self.ultima_busca[indice].caminho)
            raise ErroArquivos("Não há esse item na última busca.")
        caminho = Path(alvo).expanduser()
        if caminho.is_absolute() and caminho.exists():
            return caminho
        achados = self.buscar(alvo, limite=1)
        if not achados:
            raise ErroArquivos(f"Não encontrei nenhum arquivo parecido com '{alvo}'.")
        return Path(achados[0].caminho)

    # -- ações --------------------------------------------------------------
    def abrir(self, alvo: str) -> Path:
        caminho = self.resolver(alvo)
        windows.abrir_no_sistema(str(caminho))
        return caminho

    def mostrar_na_pasta(self, alvo: str) -> Path:
        caminho = self.resolver(alvo)
        if windows.WINDOWS:
            import subprocess

            subprocess.Popen(["explorer.exe", "/select,", str(caminho)], creationflags=windows.SEM_JANELA)
        else:
            windows.abrir_no_sistema(str(caminho.parent))
        return caminho

    def mover(self, alvo: str, destino: str) -> Path:
        origem = self.resolver(alvo)
        pasta = self._pasta_destino(destino)
        _exigir_pasta_usuario(origem)
        _exigir_pasta_usuario(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        final = _sem_conflito(pasta / origem.name)
        shutil.move(str(origem), str(final))
        self._atualizar_no_indice(origem, final)
        return final

    def renomear(self, alvo: str, novo_nome: str) -> Path:
        origem = self.resolver(alvo)
        _exigir_pasta_usuario(origem)
        novo_nome = re.sub(r'[<>:"/\\|?*]', "", novo_nome).strip()
        if not novo_nome:
            raise ErroArquivos("Esse nome não é válido.")
        if not Path(novo_nome).suffix and origem.suffix:
            novo_nome += origem.suffix
        final = origem.with_name(novo_nome)
        if final.exists():
            raise ErroArquivos(f"Já existe um arquivo chamado {novo_nome}.")
        origem.rename(final)
        self._atualizar_no_indice(origem, final)
        return final

    def apagar(self, alvo: str) -> Path:
        """Manda para a Lixeira (dá para recuperar)."""
        caminho = self.resolver(alvo)
        _exigir_pasta_usuario(caminho)
        windows.mandar_para_lixeira(caminho)
        self._atualizar_no_indice(caminho, None)
        return caminho

    def organizar_downloads(self, por_data: bool = False, pasta: Path | None = None) -> dict[str, int]:
        """Separa os arquivos soltos de Downloads em pastas por tipo (e, se pedido, por mês)."""
        pasta = pasta or self.pasta_downloads()
        if not pasta.is_dir():
            raise ErroArquivos("Não encontrei a pasta Downloads.")
        contagem: dict[str, int] = {}
        limite_recente = time.time() - 120  # não mexe no que ainda pode estar baixando
        for item in list(pasta.iterdir()):
            if not item.is_file() or item.name.startswith((".", "~$")) or item.suffix.lower() in (".crdownload", ".part", ".tmp"):
                continue
            try:
                if item.stat().st_mtime > limite_recente:
                    continue
            except OSError:
                continue
            grupo = next((PASTAS_ORGANIZAR[t] for t in PASTAS_ORGANIZAR if item.suffix.lower() in TIPOS[t]), "Outros")
            destino = pasta / grupo
            if por_data:
                destino = destino / datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m")
            destino.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(item), str(_sem_conflito(destino / item.name)))
            except OSError as erro:
                log.warning("Não consegui mover %s: %s", item.name, erro)
                continue
            contagem[grupo] = contagem.get(grupo, 0) + 1
        if contagem:
            threading.Thread(target=self.indexar, daemon=True).start()
        return contagem

    # -- auxiliares -----------------------------------------------------------
    def _pasta_destino(self, destino: str) -> Path:
        destino = (destino or "").strip().strip('"')
        caminho = Path(destino).expanduser()
        if caminho.is_absolute():
            return caminho
        chave = normalizar(destino)
        conhecidas = {"downloads": "downloads", "documentos": "documentos", "imagens": "imagens", "fotos": "imagens",
                      "musicas": "musicas", "videos": "videos", "area de trabalho": "area de trabalho",
                      "desktop": "area de trabalho"}
        if chave in conhecidas:
            return windows.pasta_conhecida(conhecidas[chave])
        # "projetos" -> procura uma pasta com esse nome dentro das pastas pessoais
        for raiz in self.raizes():
            candidata = raiz / destino
            if candidata.is_dir():
                return candidata
        return windows.pasta_conhecida("documentos") / destino

    def _atualizar_no_indice(self, antigo: Path, novo: Path | None) -> None:
        with self._lock:
            self._indice = [a for a in self._indice if a.caminho != str(antigo)]
            if novo is not None and novo.is_file():
                st = novo.stat()
                self._indice.append(Arquivo(str(novo), normalizar(novo.stem), novo.suffix.lower(), st.st_mtime, st.st_size))


@dataclass
class Filtro:
    termos: list[str]
    extensoes: set[str] | None
    desde: float | None
    ate: float | None

    def aceita(self, a: Arquivo) -> bool:
        if self.extensoes is not None and a.ext not in self.extensoes:
            return False
        if self.desde is not None and a.modificado < self.desde:
            return False
        if self.ate is not None and a.modificado >= self.ate:
            return False
        return True


def interpretar_consulta(consulta: str, tipo: str | None = None, agora: datetime | None = None) -> Filtro:
    """ "PDF do contrato de março" -> termos ["contrato"], extensões {.pdf}, março do último ano que já passou."""
    agora = agora or datetime.now()
    texto = normalizar(consulta or "")
    extensoes = TIPOS.get(PALAVRAS_TIPO.get(normalizar(tipo or ""), normalizar(tipo or ""))) if tipo else None
    desde = ate = None

    m = re.search(r"\b(?:de |em )?(" + "|".join(MESES) + r")(?: de (\d{4}))?\b", texto)
    if m:
        mes = MESES[m.group(1)]
        ano = int(m.group(2)) if m.group(2) else (agora.year if mes <= agora.month else agora.year - 1)
        inicio = datetime(ano, mes, 1)
        fim = datetime(ano + (mes == 12), mes % 12 + 1, 1)
        desde, ate = inicio.timestamp(), fim.timestamp()
        texto = texto.replace(m.group(0), " ")
    relativos = {"de hoje": 0, "hoje": 0, "de ontem": 1, "ontem": 1}
    for frase, dias in relativos.items():
        if re.search(rf"\b{frase}\b", texto):
            dia = (agora - timedelta(days=dias)).replace(hour=0, minute=0, second=0, microsecond=0)
            desde, ate = dia.timestamp(), (dia + timedelta(days=1)).timestamp()
            texto = re.sub(rf"\b{frase}\b", " ", texto)
            break
    for frase, dias in (("dessa semana", 7), ("desta semana", 7), ("da semana", 7), ("ultimos dias", 7),
                        ("desse mes", 31), ("deste mes", 31), ("do mes", 31)):
        if frase in texto:
            desde, ate = (agora - timedelta(days=dias)).timestamp(), None
            texto = texto.replace(frase, " ")
            break

    termos = []
    for palavra in texto.split():
        if palavra in PALAVRAS_TIPO and extensoes is None:
            extensoes = TIPOS[PALAVRAS_TIPO[palavra]]
            continue
        if palavra in PALAVRAS_TIPO or palavra in PALAVRAS_VAZIAS:
            continue
        termos.append(palavra)
    return Filtro(termos, extensoes, desde, ate)


def _ordinal(texto: str) -> int | None:
    t = normalizar(texto)
    t = re.sub(r"^(o |a )", "", t)
    if t.isdigit():
        return int(t) - 1
    ordinais = {"primeiro": 0, "primeira": 0, "segundo": 1, "segunda": 1, "terceiro": 2, "terceira": 2,
                "quarto": 3, "quarta": 3, "quinto": 4, "quinta": 4, "ultimo": -1, "ultima": -1}
    return ordinais.get(t)


def _dentro(caminho: Path, pasta: Path) -> bool:
    try:
        caminho.resolve().relative_to(pasta.resolve())
        return True
    except (ValueError, OSError):
        return False


def _exigir_pasta_usuario(caminho: Path) -> None:
    casa = Path.home()
    if not _dentro(caminho, casa) or caminho.resolve() == casa.resolve():
        raise ErroArquivos("Por segurança, só mexo em arquivos dentro da sua pasta de usuário.")
    partes = {p.lower() for p in caminho.resolve().relative_to(casa.resolve()).parts}
    if "appdata" in partes:
        raise ErroArquivos("Por segurança, não mexo na pasta AppData.")


def _sem_conflito(caminho: Path) -> Path:
    if not caminho.exists():
        return caminho
    for n in range(2, 1000):
        candidato = caminho.with_name(f"{caminho.stem} ({n}){caminho.suffix}")
        if not candidato.exists():
            return candidato
    raise ErroArquivos("Já existem arquivos demais com esse nome.")


def _tamanho(n: int) -> str:
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unidade}"
        n /= 1024
    return f"{n:.1f} TB"
