"""Oficina holográfica 3D e visualizador de música.

Oficina: "abre o modelo do capacete na oficina", "abre o capacete.stl", "mostra o modelo 3d da turbina".
O arquivo (.stl, .obj, .glb, .gltf, .fbx, .3mf) é achado no índice de arquivos e servido ao HUD por
``/api/oficina/arquivo/<id>``, onde ``id`` é um código opaco gerado aqui (o HUD nunca manda caminhos).
O HUD desenha o modelo como holograma; "explode as peças", "junta as peças", "gira o modelo",
"para de girar" e "fecha a oficina" viram o evento ``oficina.comando``.

Visualizador de música: "liga o visualizador". Enquanto o holograma "visualizador" está aberto, o som
que sai do PC é captado (loopback WASAPI, biblioteca ``soundcard``, só no Windows) e vira ~32 faixas
de frequência publicadas a ~25 quadros por segundo no evento ``musica.espectro``.
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from collections import OrderedDict
from pathlib import Path

from ..cerebro.ferramentas import P
from ..habilidades import windows
from ..util.texto import normalizar

log = logging.getLogger(__name__)

HOLOGRAMAS = {"oficina": "Oficina", "visualizador": "Visualizador de música"}
EVENTOS_ALTA_FREQUENCIA = {"musica.espectro"}

FORMATOS = {".stl": "stl", ".obj": "obj", ".glb": "glb", ".gltf": "gltf", ".fbx": "fbx", ".3mf": "3mf"}
TIPOS_CONTEUDO = {
    "stl": "model/stl", "obj": "model/obj", "glb": "model/gltf-binary", "gltf": "model/gltf+json",
    "fbx": "application/octet-stream", "3mf": "model/3mf",
}
# arquivos ao lado de um .gltf que ele pode referenciar (buffers e texturas)
RECURSOS_GLTF = {".bin": "application/octet-stream", ".png": "image/png", ".jpg": "image/jpeg",
                 ".jpeg": "image/jpeg", ".webp": "image/webp", ".ktx2": "image/ktx2"}
MAX_BYTES = 200 * 1024 * 1024
MAX_CODIGOS = 64

COMANDOS = {"explodir", "juntar", "girar", "parar"}
RESPOSTAS = {
    "explodir": "Explodindo as peças.",
    "juntar": "Juntando as peças.",
    "girar": "Girando o modelo.",
    "parar": "Rotação parada.",
}
UMA_PECA = "Esse modelo tem uma peça só."
SEM_OFICINA = "A oficina não está aberta. Diga, por exemplo: abre o modelo do capacete na oficina."


class ErroOficina(Exception):
    pass


def _tamanho(n: int) -> str:
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidade == "GB":
            return f"{n:.0f} {unidade}" if unidade == "B" else f"{n:.1f} {unidade}".replace(".", ",")
        n /= 1024
    return ""


# -- oficina ---------------------------------------------------------------------------------------

class Oficina:
    """Guarda os modelos liberados para o HUD (código opaco -> caminho) e o modelo aberto."""

    def __init__(self, app) -> None:
        self.app = app
        self._codigos: OrderedDict[str, Path] = OrderedDict()
        self._lock = threading.Lock()
        self.atual: dict | None = None
        self.pecas: dict[str, int] = {}  # código -> número de peças que o HUD contou
        self._lembrados: set[str] = set()

    def liberar(self, caminho: Path) -> str:
        with self._lock:
            for codigo, existente in self._codigos.items():
                if existente == caminho:
                    self._codigos.move_to_end(codigo)
                    return codigo
            codigo = secrets.token_urlsafe(16)
            self._codigos[codigo] = caminho
            while len(self._codigos) > MAX_CODIGOS:
                antigo, _ = self._codigos.popitem(last=False)
                self.pecas.pop(antigo, None)
            return codigo

    def caminho(self, codigo: str) -> Path | None:
        with self._lock:
            return self._codigos.get(codigo)

    def arquivo(self, codigo: str) -> tuple[Path, str] | None:
        """Caminho e content-type de um modelo liberado, se ainda for válido."""
        caminho = self.caminho(codigo)
        if caminho is None:
            return None
        formato = FORMATOS.get(caminho.suffix.lower())
        try:
            if formato is None or not caminho.is_file() or caminho.stat().st_size > MAX_BYTES:
                return None
        except OSError:
            return None
        return caminho, TIPOS_CONTEUDO[formato]

    def recurso(self, codigo: str, nome: str) -> tuple[Path, str] | None:
        """Arquivo vizinho de um .gltf liberado (buffers, texturas), sem sair da pasta dele."""
        caminho = self.caminho(codigo)
        if caminho is None or caminho.suffix.lower() != ".gltf":
            return None
        alvo_nome = nome.replace("\\", "/")
        tipo = RECURSOS_GLTF.get(Path(alvo_nome).suffix.lower())
        if tipo is None or ":" in alvo_nome or alvo_nome.startswith("/"):
            return None
        pasta = caminho.parent.resolve()
        try:
            alvo = (pasta / alvo_nome).resolve()
            if not alvo.is_relative_to(pasta) or not alvo.is_file() or alvo.stat().st_size > MAX_BYTES:
                return None
        except OSError:
            return None
        return alvo, tipo

    # -- resolver o pedido --------------------------------------------------------------------------
    def resolver(self, consulta: str) -> Path:
        consulta = (consulta or "").strip().strip('"')
        if not consulta:
            raise ErroOficina("Qual modelo? Diga o nome do arquivo.")
        caminho = Path(consulta).expanduser()
        if caminho.is_absolute():
            if not caminho.is_file():
                raise ErroOficina(f"Não achei o arquivo {caminho.name}.")
        else:
            termos, extensao = limpar_consulta(consulta)
            achados = buscar_modelos(self.app, termos or consulta)
            if not achados:
                raise ErroOficina(f"Não encontrei nenhum modelo 3D parecido com {termos or consulta}.")
            if extensao:  # "capacete glb": prefere o arquivo com essa extensão
                achados.sort(key=lambda a: Path(a.caminho).suffix.lower() != f".{extensao}")
            caminho = Path(achados[0].caminho)
        if caminho.suffix.lower() not in FORMATOS:
            raise ErroOficina("Esse arquivo não é um modelo 3D que eu saiba abrir (STL, OBJ, GLB, GLTF, FBX ou 3MF).")
        try:
            tamanho = caminho.stat().st_size
        except OSError as erro:
            raise ErroOficina(f"Não consegui ler {caminho.name}: {erro}") from None
        if tamanho > MAX_BYTES:
            raise ErroOficina(f"{caminho.name} tem {_tamanho(tamanho)}; o limite da oficina é 200 MB.")
        return caminho

    def abrir(self, consulta: str) -> dict:
        caminho = self.resolver(consulta)
        codigo = self.liberar(caminho)
        tamanho = caminho.stat().st_size
        dados = {"id": codigo, "nome": caminho.name, "formato": FORMATOS[caminho.suffix.lower()],
                 "url": f"/api/oficina/arquivo/{codigo}", "tamanho": _tamanho(tamanho), "bytes": tamanho}
        self.atual = dados
        self.app.hologramas.mostrar("oficina", dados, titulo=f"Oficina · {caminho.name}")
        self._lembrar(caminho)
        return dados

    def _lembrar(self, caminho: Path) -> None:
        if str(caminho) in self._lembrados:
            return
        self._lembrados.add(str(caminho))
        memoria = getattr(self.app, "memoria", None)
        aprender = getattr(memoria, "aprender", None)
        if aprender is None:
            return
        try:
            aprender("fato", f"O usuário abriu o modelo 3D {caminho.name} na oficina (pasta {caminho.parent}).",
                     ["oficina", "modelo 3d"], origem="oficina")
        except Exception:  # noqa: BLE001 - memória é opcional
            log.debug("Memória indisponível para a oficina", exc_info=True)

    def comando(self, acao: str) -> str:
        if not self.app.hologramas.aberto("oficina") or not self.atual:
            return SEM_OFICINA
        if acao in ("explodir", "juntar") and self.pecas.get(self.atual["id"]) == 1:
            return UMA_PECA
        self.app.barramento.publicar("oficina.comando", acao=acao, id=self.atual["id"])
        return RESPOSTAS[acao]

    def fechar(self) -> str:
        n = self.app.hologramas.fechar(tipo="oficina")
        return "Oficina fechada." if n else "A oficina não estava aberta."


_VAZIAS = {"o", "a", "os", "as", "do", "da", "de", "dos", "das", "meu", "minha", "um", "uma", "modelo", "modelos",
           "3d", "tridimensional", "arquivo", "na", "no", "oficina", "holograma", "em"}


def limpar_consulta(consulta: str) -> tuple[str, str]:
    """'o modelo 3d do capacete' -> ('capacete', ''); 'capacete.glb' -> ('capacete', 'glb')."""
    palavras = [p for p in normalizar(consulta).split() if p not in _VAZIAS]
    extensao = ""
    if len(palavras) > 1 and f".{palavras[-1]}" in FORMATOS:
        extensao = palavras.pop()
    return " ".join(palavras), extensao


def buscar_modelos(app, termos: str, limite: int = 5) -> list:
    arquivos = getattr(app, "arquivos", None)
    if arquivos is None:
        raise ErroOficina("A busca de arquivos não está disponível.")
    return list(arquivos.buscar(termos, tipo="modelo 3d", limite=limite))


# -- analisador de espectro -------------------------------------------------------------------------

class Analisador:
    """Transforma blocos de áudio em faixas de frequência 0..1 (FFT com janela de Hann, ganho automático)."""

    FAIXA_DB = 48.0
    PISO_DB = -58.0  # abaixo disso é silêncio: o ganho automático não amplifica ruído

    def __init__(self, taxa: int = 44100, n_fft: int = 2048, n_bandas: int = 32,
                 fmin: float = 40.0, fmax: float = 16000.0) -> None:
        import numpy as np

        self.np = np
        self.taxa, self.n_fft, self.n_bandas = taxa, n_fft, n_bandas
        self.janela = np.hanning(n_fft).astype(np.float32)
        self.escala = 2.0 / float(self.janela.sum())
        self.buffer = np.zeros(n_fft, dtype=np.float32)
        freqs = np.fft.rfftfreq(n_fft, 1.0 / taxa)
        bordas = np.geomspace(fmin, min(fmax, taxa / 2), n_bandas + 1)
        indices = np.searchsorted(freqs, bordas)
        limites = []
        anterior = 1
        for i in range(n_bandas):
            ini = max(int(indices[i]), anterior)
            fim = max(int(indices[i + 1]), ini + 1)
            fim = min(fim, len(freqs))
            ini = min(ini, fim - 1)
            limites.append((ini, fim))
            anterior = fim
        self.limites = limites
        centros = np.sqrt(bordas[:-1] * bordas[1:])
        self.graves = max(1, int(np.sum(centros < 160)))
        self.pico = self.PISO_DB + self.FAIXA_DB * 0.6
        self.bandas = np.zeros(n_bandas, dtype=np.float32)
        self.nivel = 0.0
        self.grave = 0.0

    def processar(self, amostras) -> dict:
        np = self.np
        dados = np.asarray(amostras, dtype=np.float32)
        if dados.ndim > 1:
            dados = dados.mean(axis=1)
        dados = np.nan_to_num(dados[-self.n_fft:])
        self.buffer = np.concatenate([self.buffer[len(dados):], dados])
        espectro = np.abs(np.fft.rfft(self.buffer * self.janela)) * self.escala
        energia = np.array([np.sqrt(np.mean(espectro[a:b] ** 2)) for a, b in self.limites], dtype=np.float32)
        db = 20.0 * np.log10(energia + 1e-9)
        maximo = float(db.max())
        # ganho automático: o pico desce devagar e sobe na hora
        self.pico = max(self.pico - 0.04, maximo, self.PISO_DB + self.FAIXA_DB * 0.6)
        alvo = np.clip((db - (self.pico - self.FAIXA_DB)) / self.FAIXA_DB, 0.0, 1.0)
        if maximo < self.PISO_DB:
            alvo[:] = 0.0
        # suavização: sobe rápido, cai devagar
        subindo = alvo > self.bandas
        self.bandas = np.where(subindo, self.bandas + (alvo - self.bandas) * 0.65, self.bandas * 0.82 + alvo * 0.18)
        rms = float(np.sqrt(np.mean(dados ** 2))) if len(dados) else 0.0
        nivel = 0.0 if rms <= 0 else float(np.clip((20 * np.log10(rms + 1e-9) + 50) / 44, 0, 1))
        grave = float(self.bandas[: self.graves].mean())
        self.nivel = self.nivel * 0.6 + nivel * 0.4
        self.grave = max(grave, self.grave * 0.85)
        return {"bandas": [round(float(v), 3) for v in self.bandas], "nivel": round(self.nivel, 3),
                "grave": round(self.grave, 3)}


# -- captura do som do PC --------------------------------------------------------------------------

class Visualizador:
    """Capta o som que sai do PC só enquanto o holograma "visualizador" estiver aberto."""

    TAXA = 44100
    QUADROS_POR_S = 25

    def __init__(self, app) -> None:
        self.app = app
        self.ativo = False
        self.motivo = ""
        self._rodando = False
        self._captar = threading.Event()
        self._thread: threading.Thread | None = None
        self._avisado = False

    def motivo_indisponivel(self) -> str:
        """Por que a captura não funciona aqui ('' se pode funcionar)."""
        if not windows.WINDOWS:
            return "O visualizador capta o som do PC só no Windows."
        try:
            import numpy  # noqa: F401
            import soundcard  # noqa: F401
        except ImportError:
            return "Falta a biblioteca soundcard. Rode: pip install soundcard"
        except Exception as erro:  # noqa: BLE001
            return f"A biblioteca soundcard não carregou: {erro}"
        return ""

    def estado(self) -> dict:
        return {"ativo": self.ativo, "motivo": self.motivo}

    def _publicar_estado(self, ativo: bool, motivo: str = "") -> None:
        mudou = (ativo, motivo) != (self.ativo, self.motivo)
        self.ativo, self.motivo = ativo, motivo
        if mudou:
            self.app.barramento.publicar("musica.estado", **self.estado())

    def iniciar(self) -> None:
        self._rodando = True
        threading.Thread(target=self._vigiar, name="visualizador-vigia", daemon=True).start()

    def encerrar(self) -> None:
        self._rodando = False
        self._captar.clear()

    def _vigiar(self) -> None:
        while self._rodando:
            try:
                aberto = self.app.hologramas.aberto("visualizador")
            except Exception:  # noqa: BLE001
                aberto = False
            if aberto and not self._captar.is_set():
                self._captar.set()
                if self._thread is None or not self._thread.is_alive():
                    self._thread = threading.Thread(target=self._capturar, name="visualizador", daemon=True)
                    self._thread.start()
            elif not aberto and self._captar.is_set():
                self._captar.clear()
            time.sleep(0.5)

    def _capturar(self) -> None:
        motivo = self.motivo_indisponivel()
        if motivo:
            if not self._avisado:
                log.info("Visualizador sem captura: %s", motivo)
                self._avisado = True
            self._publicar_estado(False, motivo)
            return
        com = _iniciar_com()
        falhas = 0
        try:
            while self._captar.is_set() and self._rodando:
                try:
                    self._gravar()
                    falhas = 0
                except Exception as erro:  # noqa: BLE001 - troca de dispositivo, fone desconectado...
                    falhas += 1
                    log.info("Visualizador: captura falhou (%s)", erro)
                    self._publicar_estado(False, f"Não consegui captar o som do PC: {erro}")
                    if falhas >= 5:
                        return
                    time.sleep(2)
        finally:
            if self.ativo:
                self._publicar_estado(False, "")
            _encerrar_com(com)

    def _gravar(self) -> None:
        import warnings

        import soundcard

        warnings.filterwarnings("ignore", category=getattr(soundcard, "SoundcardRuntimeWarning", RuntimeWarning))
        alto_falante = soundcard.default_speaker()
        if alto_falante is None:
            raise RuntimeError("nenhuma saída de som encontrada")
        microfone = soundcard.get_microphone(id=str(alto_falante.name), include_loopback=True)
        bloco = self.TAXA // self.QUADROS_POR_S
        analisador = Analisador(taxa=self.TAXA)
        with microfone.recorder(samplerate=self.TAXA, blocksize=bloco) as gravador:
            self._publicar_estado(True, "")
            while self._captar.is_set() and self._rodando:
                dados = gravador.record(numframes=bloco)
                self.app.barramento.publicar("musica.espectro", **analisador.processar(dados))


def _iniciar_com() -> bool:
    """O WASAPI precisa do COM iniciado em cada thread que o usa."""
    if not windows.WINDOWS:
        return False
    try:
        import ctypes

        return ctypes.windll.ole32.CoInitializeEx(None, 0) in (0, 1)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


def _encerrar_com(iniciado: bool) -> None:
    if iniciado:
        try:
            import ctypes

            ctypes.windll.ole32.CoUninitialize()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def ligar_visualizador(app, ligar: bool) -> str:
    if not ligar:
        n = app.hologramas.fechar(tipo="visualizador")
        return "Visualizador desligado." if n else "O visualizador não estava ligado."
    app.hologramas.mostrar("visualizador", app.visualizador.estado())
    motivo = app.visualizador.motivo_indisponivel()
    if motivo:
        return f"Visualizador na tela, mas sem som: {motivo}"
    return "Visualizador ligado. Solta o som!"


def _quer_ligar(valor) -> bool:
    if isinstance(valor, bool):
        return valor
    return normalizar(str(valor)) not in ("desligar", "desliga", "false", "nao", "off", "fechar", "0")


def _acao_visualizador(app, valor, ctx, variaveis) -> None:
    ligar_visualizador(app, _quer_ligar(valor))


ACOES_PROTOCOLO = {
    "visualizador": {"rotulo": "Visualizador de música", "entrada": "opcoes", "opcoes": ["ligar", "desligar"],
                     "dica": "Abre ou fecha o visualizador que reage ao som do PC.", "executar": _acao_visualizador},
}


# -- ganchos da extensão ----------------------------------------------------------------------------

def instalar(app) -> None:
    app.oficina = Oficina(app)
    app.visualizador = Visualizador(app)


def registrar(app, registro) -> None:
    @registro.ferramenta(
        "oficina",
        "Oficina holográfica 3D: abre modelos 3D do usuário (STL, OBJ, GLB, GLTF, FBX, 3MF) como holograma no HUD. "
        "abrir: modelo = nome do arquivo ('capacete') ou caminho completo; explodir/juntar separam ou montam as peças; "
        "girar/parar ligam ou param a rotação; fechar fecha a oficina.",
        direta=True,
        acao=P("string", "Ação.", enum=["abrir", "explodir", "juntar", "girar", "parar", "fechar"], obrigatorio=True),
        modelo=P("string", "Para abrir: nome do modelo ou caminho completo do arquivo."),
    )
    def oficina(ctx, acao: str, modelo: str | None = None):
        if acao == "abrir":
            if not modelo:
                app.hologramas.mostrar("oficina", app.oficina.atual or {})
                return {"ok": True, "resumo": "Oficina aberta. Qual modelo você quer ver?"}
            try:
                dados = app.oficina.abrir(modelo)
            except ErroOficina as erro:
                return {"ok": False, "resumo": str(erro)}
            return {"ok": True, "resumo": f"Abrindo {dados['nome']} na oficina."}
        if acao == "fechar":
            return {"ok": True, "resumo": app.oficina.fechar()}
        if acao in COMANDOS:
            resposta = app.oficina.comando(acao)
            return {"ok": resposta in RESPOSTAS.values(), "resumo": resposta}
        return {"ok": False, "resumo": "Ação desconhecida."}

    @registro.ferramenta(
        "visualizador",
        "Visualizador de música holográfico que reage ao som que sai do PC. ligar abre, desligar fecha.",
        direta=True,
        acao=P("string", "Ação.", enum=["ligar", "desligar"], obrigatorio=True),
    )
    def visualizador(ctx, acao: str):
        return {"ok": True, "resumo": ligar_visualizador(app, acao != "desligar")}


_EXT = "|".join(f[1:] for f in FORMATOS)
_ABRIR = re.compile(r"^(?:abre|abrir|abra|mostra|mostrar|mostre|carrega|carregar|projeta|projetar|exibe|coloca|bota)"
                    r"(?: pra mim| para mim)? (.+)$")
_SO_OFICINA = re.compile(r"^(?:a )?oficina( 3d| holografica)?$")
_NA_OFICINA = re.compile(r" (?:na oficina|no holograma|em 3d|em holograma)$")
_MODELO = re.compile(r"^(?:o |a |os |meu |minha |um )?modelo( 3d| tridimensional)?(?: do| da| de| dos| das)? (.+)$")
_COM_EXTENSAO = re.compile(rf"^(?:o |a |meu |minha )?(.+?) ({_EXT})$")
_EXPLODIR = re.compile(r"^(?:explode|explodir|exploda|separa|separar|separe|abre)(?: as| todas as)? (?:pecas|partes)"
                       r"(?: do modelo)?$|^(?:explode|explodir|exploda) o modelo$|^(?:mostra a )?vista explodida$")
_JUNTAR = re.compile(r"^(?:junta|juntar|junte|monta|montar|monte|une|unir|fecha)(?: as| todas as)? (?:pecas|partes)"
                     r"(?: do modelo)?(?: de novo)?$|^(?:junta|monta|remonta) o modelo(?: de novo)?$")
_GIRAR = re.compile(r"^(?:gira|girar|gire|roda|rodar|rode) o modelo$|^(?:liga|ativa) a rotacao(?: do modelo)?$")
_PARAR = re.compile(r"^(?:para|pare|parar) de girar$|^(?:para|pare|parar|trava) (?:o modelo|a rotacao)$|"
                    r"^(?:desliga|desativa) a rotacao(?: do modelo)?$")
_FECHAR = re.compile(r"^(?:fecha|fechar|feche|sai da|sair da) (?:a )?oficina$")
_VIS = r"(?: o)? (?:visualizador|visualizacao)(?: de musica| do som| de audio| musical| de som)?$"
_VIS_LIGAR = re.compile(r"^(?:liga|ligar|ativa|ativar|abre|abrir|mostra|mostrar|coloca|bota|abra|ligue)" + _VIS)
_VIS_DESLIGAR = re.compile(r"^(?:desliga|desligar|desative|desativa|fecha|fechar|tira|esconde|feche|desligue)" + _VIS)


def interpretar_abrir(t: str) -> tuple[str, bool] | None:
    """Texto normalizado -> (consulta do modelo, certeza), ou None se não é com a oficina.

    Consulta '' = só abrir a oficina. Sem certeza ("abre o modelo do capacete": "modelo" também é
    template de documento), quem chama confere se existe um modelo 3D com esse nome.
    """
    m = _ABRIR.match(t)
    if not m:
        return None
    resto = m.group(1)
    if _SO_OFICINA.match(resto):
        return "", True
    marcado = False
    if n := _NA_OFICINA.search(resto):
        resto, marcado = resto[: n.start()], True
    if m3 := _COM_EXTENSAO.match(resto):
        return f"{m3.group(1)} {m3.group(2)}", True
    if m2 := _MODELO.match(resto):
        return m2.group(2), marcado or bool(m2.group(1))
    return (resto, True) if marcado else None


def atalho(t: str, ctx, rodar, original: str | None):
    app = ctx.app
    if _VIS_LIGAR.match(t):
        return rodar("visualizador", {"acao": "ligar"})
    if _VIS_DESLIGAR.match(t):
        return rodar("visualizador", {"acao": "desligar"})
    if _FECHAR.match(t):
        return rodar("oficina", {"acao": "fechar"})
    if _EXPLODIR.match(t):
        return rodar("oficina", {"acao": "explodir"})
    if _JUNTAR.match(t):
        return rodar("oficina", {"acao": "juntar"})
    if _GIRAR.match(t):
        return rodar("oficina", {"acao": "girar"})
    if _PARAR.match(t) and ("modelo" in t or app.hologramas.aberto("oficina")):
        return rodar("oficina", {"acao": "parar"})
    pedido = interpretar_abrir(t)
    if pedido is None:
        return None
    consulta, certeza = pedido
    if not certeza:
        try:
            if not buscar_modelos(app, limpar_consulta(consulta)[0] or consulta, limite=1):
                return None
        except Exception:  # noqa: BLE001
            return None
    if not consulta:
        return rodar("oficina", {"acao": "abrir"})
    caminho = _caminho_no_original(original)
    return rodar("oficina", {"acao": "abrir", "modelo": caminho or consulta})


def _caminho_no_original(original: str | None) -> str | None:
    if not original:
        return None
    m = re.search(rf'([A-Za-z]:\\[^"<>|?*]+?\.(?:{_EXT}))\b', original, flags=re.I)
    return m.group(1) if m else None


def rotas(api, app, autenticado, so_pc) -> None:
    import asyncio

    from fastapi import Body, Depends, HTTPException
    from fastapi.responses import FileResponse

    oficina: Oficina = app.oficina

    def _checar(cliente) -> None:
        if cliente.tipo == "pc" and app.sessao.bloqueada:
            raise HTTPException(423, "A Sexta-Feira está bloqueada.")

    @api.get("/api/oficina/arquivo/{codigo}")
    async def arquivo_oficina(codigo: str, cliente=Depends(autenticado)):
        """Serve só os modelos que a própria Sexta-Feira liberou (código opaco, nunca caminho)."""
        _checar(cliente)
        achado = await asyncio.to_thread(oficina.arquivo, codigo)
        if achado is None:
            raise HTTPException(404, "Modelo não encontrado.")
        caminho, tipo = achado
        return FileResponse(caminho, media_type=tipo, filename=caminho.name, content_disposition_type="inline")

    @api.get("/api/oficina/arquivo/{codigo}/{recurso:path}")
    async def recurso_oficina(codigo: str, recurso: str, cliente=Depends(autenticado)):
        """Buffers e texturas de um .gltf liberado (só na pasta dele)."""
        _checar(cliente)
        achado = await asyncio.to_thread(oficina.recurso, codigo, recurso)
        if achado is None:
            raise HTTPException(404, "Recurso não encontrado.")
        caminho, tipo = achado
        return FileResponse(caminho, media_type=tipo)

    @api.post("/api/oficina/pecas")
    async def pecas_oficina(corpo: dict = Body(...), _=Depends(autenticado)):
        codigo = str(corpo.get("id") or "")
        try:
            pecas = int(corpo.get("pecas"))
        except (TypeError, ValueError):
            raise HTTPException(400, "Número de peças inválido.") from None
        if oficina.caminho(codigo) is None or pecas < 0:
            raise HTTPException(404, "Modelo não encontrado.")
        oficina.pecas[codigo] = pecas
        return {"ok": True}


def dados_holograma(app, tipo: str) -> dict | None:
    if tipo == "oficina":
        return dict(app.oficina.atual or {})
    if tipo == "visualizador":
        estado = app.visualizador.estado()
        if not estado["ativo"] and not estado["motivo"]:
            estado["motivo"] = app.visualizador.motivo_indisponivel()
        return estado
    return None


def diagnostico(app) -> list[dict]:
    motivo = app.visualizador.motivo_indisponivel()
    if not windows.WINDOWS:
        return [{"nome": "Visualizador de música", "ok": True, "detalhe": "só capta o som do PC no Windows", "dica": ""}]
    return [{"nome": "Visualizador de música", "ok": not motivo, "detalhe": motivo or "captura do som do PC disponível",
             "dica": "pip install soundcard" if motivo else ""}]


def iniciar(app) -> None:
    app.visualizador.iniciar()


def encerrar(app) -> None:
    app.visualizador.encerrar()
