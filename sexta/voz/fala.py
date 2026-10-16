"""Voz da Sexta-Feira.

- Voz neural da Microsoft via ``edge-tts`` (precisa de internet, gratuita).
- Sem internet, cai automaticamente para as vozes do Windows (``pyttsx3``/SAPI).
- Fala em pipeline: enquanto uma frase toca, a próxima já está sendo sintetizada.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np

from ..util.texto import limpar_para_fala
from . import efeitos
from .audio import Reprodutor, decodificar, tom

# Perfil "sexta": voz jovem e calma, um pouco mais grave, com o efeito de IA do traje
PERFIS = {"sexta": {"voz": "pt-BR-ThalitaMultilingualNeural", "velocidade": "+4%", "tom": "-3Hz"}}

# Como cada idioma aparece no nome das vozes instaladas no Windows (voz offline)
NOMES_IDIOMA_WINDOWS = {"pt": "portugu|maria", "en": "english", "es": "spanish", "fr": "french", "de": "german",
                        "it": "italian", "ja": "japanese", "zh": "chinese", "ko": "korean", "ru": "russian"}

log = logging.getLogger(__name__)


RECONHECIMENTOS = ["Deixa eu ver.", "Um instante.", "Só um momento.", "Vou pensar nisso.", "Deixa comigo.",
                   "Analisando."]


class Fala:
    def __init__(self, app) -> None:
        self.app = app
        cfg = app.cfg
        self._ultimo_nivel = 0.0
        self.reprodutor = Reprodutor(cfg.alto_falante, ao_nivel=self._nivel)
        self._textos: queue.Queue = queue.Queue()
        self._audios: queue.Queue = queue.Queue(maxsize=3)
        self._geracao = 0
        self._tocando = False
        self._pendentes = 0  # itens ainda não tocados (na fila, sintetizando ou tocando)
        self._lock = threading.Lock()
        self._ocioso = threading.Event()
        self._ocioso.set()
        self._cache: OrderedDict[tuple, tuple[np.ndarray, int]] = OrderedDict()
        self._fixas: dict[tuple, tuple[np.ndarray, int]] = {}  # frases curtas pré-geradas (não saem do cache)
        self._ultimo_reconhecimento = ""
        self._preaquecendo = False
        self._edge_falhas = 0
        self._edge_pausado_ate = 0.0
        self._ultima_foi_windows = False
        self._loop = asyncio.new_event_loop()
        self._pyttsx3 = None
        self._voz_sistema: str | None = None
        self._vozes_windows: dict[str, str | None] = {}
        self._rodando = True
        threading.Thread(target=self._loop_sintese, name="sintese", daemon=True).start()
        threading.Thread(target=self._loop_reproducao, name="reproducao", daemon=True).start()

    # -- API ------------------------------------------------------------
    @property
    def voz(self) -> str:
        escolha = self.app.prefs.get("voz") or self.app.cfg.voz
        return PERFIS.get(escolha, {}).get("voz", escolha)

    def _prosodia(self) -> tuple[str, str]:
        perfil = PERFIS.get(self.app.prefs.get("voz") or self.app.cfg.voz)
        if perfil:
            return perfil["velocidade"], perfil["tom"]
        return self.app.cfg.voz_velocidade, self.app.cfg.voz_tom

    def _perfil(self, voz: str | None) -> tuple[str, str, str]:
        """(voz, velocidade, tom) de uma frase: a voz pedida para ela (ex.: a do idioma no modo tradutor),
        sem ajustes de prosódia, ou a da Sexta-Feira."""
        if voz:
            return voz, "+0%", "+0Hz"
        return (self.voz, *self._prosodia())

    def _com_efeito(self) -> bool:
        return bool(self.app.prefs.get("voz_efeito"))

    def falar(self, texto: str, voz: str | None = None) -> None:
        """Fala o texto. ``voz``: outra voz do edge-tts só para esta frase (o efeito de voz continua valendo)."""
        texto = limpar_para_fala(texto or "")
        if texto:
            self._enfileirar((texto, voz))

    def _enfileirar(self, item) -> None:
        with self._lock:
            self._pendentes += 1
            self._ocioso.clear()
            geracao = self._geracao
        self._textos.put((geracao, item))

    def _concluir(self, quantidade: int = 1) -> None:
        with self._lock:
            self._pendentes = max(0, self._pendentes - quantidade)
            terminou = self._pendentes == 0
            if terminou:
                self._ocioso.set()
        if terminou and self.app.estado.atual == "falando":
            agente = getattr(self.app, "agente", None)
            self.app.estado.definir("pensando" if agente and agente.ocupado() else "inativa")

    def preaquecer(self, frases: list[str]) -> None:
        """Gera o áudio de frases curtas de antemão: depois elas tocam em milissegundos."""
        for frase in frases:  # quem sintetiza é a thread da síntese (o loop asyncio é dela)
            texto = limpar_para_fala(frase)
            if texto and (*self._perfil(None), self._com_efeito(), texto) not in self._fixas:
                self._textos.put((None, ("__fixa__", texto)))

    def reconhecer(self) -> None:
        """Um "deixa eu ver" na hora, enquanto o cérebro pensa (só frases já pré-geradas)."""
        alvos = {limpar_para_fala(f) for f in RECONHECIMENTOS}
        prontas = [c[-1] for c in self._fixas if c[:4] == (*self._perfil(None), self._com_efeito()) and c[-1] in alvos]
        opcoes = [f for f in prontas if f != self._ultimo_reconhecimento] or prontas
        if not prontas and not self._preaquecendo:
            # voz trocada (ou ainda não pré-gerou): prepara para as próximas vezes, depois desta resposta
            self._preaquecendo = True
            temporizador = threading.Timer(20, lambda: (self.preaquecer(RECONHECIMENTOS),
                                                        setattr(self, "_preaquecendo", False)))
            temporizador.daemon = True
            temporizador.start()
        if opcoes:
            import random

            self._ultimo_reconhecimento = random.choice(opcoes)
            self.falar(self._ultimo_reconhecimento)

    def falar_e_esperar(self, texto: str, timeout: float = 60.0) -> None:
        self.falar(texto)
        self.aguardar(timeout)

    def tocar_som(self, notas, esperar: bool = False) -> None:
        """Toca um efeito sonoro curto (bipes) pela mesma fila da voz."""
        self._enfileirar(("__som__", tom(notas), 24000))
        if esperar:
            self.aguardar(5)

    def parar(self) -> None:
        with self._lock:
            self._geracao += 1
        descartados = 0
        for fila in (self._textos, self._audios):
            while True:
                try:
                    fila.get_nowait()
                    descartados += 1
                except queue.Empty:
                    break
        if descartados:
            self._concluir(descartados)
        self.reprodutor.parar()

    def falando(self) -> bool:
        return self._tocando

    def falando_ou_na_fila(self) -> bool:
        return not self._ocioso.is_set()

    def aguardar(self, timeout: float = 60.0) -> bool:
        return self._ocioso.wait(timeout)

    def gerar_audio(self, texto: str) -> tuple[bytes, str] | None:
        """Sintetiza um MP3 para tocar em outro aparelho (celular). ``None`` se a voz online falhar.

        Roda num loop asyncio próprio, então pode ser chamada de qualquer thread.
        """
        texto = limpar_para_fala(texto)
        if not texto or self.app.cfg.voz_motor == "windows":
            return None
        try:
            mp3 = asyncio.run(asyncio.wait_for(self._edge_bytes(texto), timeout=20))
        except Exception as erro:  # noqa: BLE001
            log.warning("Não consegui gerar o áudio para o celular: %s", erro)
            return None
        if not self._com_efeito():
            return mp3, "audio/mpeg"
        try:  # o celular ouve a mesma voz do PC, com o efeito
            audio, taxa = decodificar(mp3)
            return efeitos.para_wav(efeitos.traje(audio, taxa), taxa), "audio/wav"
        except Exception as erro:  # noqa: BLE001
            log.warning("Efeito de voz falhou no áudio do celular: %s", erro)
            return mp3, "audio/mpeg"

    def encerrar(self) -> None:
        self._rodando = False
        self.parar()

    # -- internos ---------------------------------------------------------
    def _nivel(self, valor: float) -> None:
        agora = time.monotonic()
        if agora - self._ultimo_nivel >= 0.033 or valor == 0.0:
            self._ultimo_nivel = agora
            self.app.barramento.publicar("fala.nivel", nivel=round(min(1.0, valor * 4.0), 3))

    def _executar(self, coro):
        return self._loop.run_until_complete(asyncio.wait_for(coro, timeout=20))

    async def _edge_bytes(self, texto: str, perfil: tuple[str, str, str] | None = None) -> bytes:
        """MP3 do edge-tts. ``perfil``: (voz, velocidade, tom); sem ele, a voz da Sexta-Feira."""
        import edge_tts

        voz, velocidade, tom_voz = perfil or self._perfil(None)
        comunicacao = edge_tts.Communicate(texto, voz, rate=velocidade, pitch=tom_voz,
                                           connect_timeout=4, receive_timeout=15)
        dados = bytearray()
        async for pedaco in comunicacao.stream():
            if pedaco.get("type") == "audio":
                dados += pedaco["data"]
        if not dados:
            raise RuntimeError("edge-tts não devolveu áudio")
        return bytes(dados)

    def _sintetizar(self, texto: str, voz: str | None = None) -> tuple[np.ndarray, int]:
        efeito = self._com_efeito()
        perfil = self._perfil(voz)
        chave = (*perfil, efeito, texto)
        if chave in self._fixas:
            return self._fixas[chave]
        if chave in self._cache:
            self._cache.move_to_end(chave)
            return self._cache[chave]
        resultado = None
        if self.app.cfg.voz_motor != "windows" and time.time() >= self._edge_pausado_ate:
            # algumas vozes online (ex.: as "Multilingual") falham à toa: antes da voz do Windows, tenta a voz
            # online padrão do .env, que é estável
            tentativas = [perfil]
            reserva = (self.app.cfg.voz, self.app.cfg.voz_velocidade, self.app.cfg.voz_tom)
            if voz is None and reserva[0] != perfil[0] and reserva[0] not in PERFIS:
                tentativas.append(reserva)
            ultimo_erro: Exception | None = None
            for i, tentativa in enumerate(tentativas):
                try:
                    resultado = decodificar(self._executar(self._edge_bytes(texto, tentativa)))
                    self._edge_falhas = 0
                    if i:
                        log.info("Voz %s falhou; falei com %s", perfil[0], tentativa[0])
                    break
                except Exception as erro:  # noqa: BLE001
                    ultimo_erro = erro
            if resultado is None:
                self._edge_falhas += 1
                log.warning("Voz online indisponível (%s); usando voz do Windows", ultimo_erro)
                if self._edge_falhas >= 2:
                    self._edge_pausado_ate = time.time() + 300
        if resultado is None:  # a voz do Windows fala português, ou o idioma da voz pedida ("en-US-..." -> "en")
            resultado = self._sintetizar_windows(texto, voz.split("-", 1)[0].lower() if voz else "pt")
            self._ultima_foi_windows = True
        if efeito:
            try:
                resultado = (efeitos.traje(resultado[0], resultado[1]), resultado[1])
            except Exception:  # noqa: BLE001 - sem efeito é melhor que sem voz
                log.exception("Efeito de voz falhou")
        if len(texto) <= 80:
            self._cache[chave] = resultado
            while len(self._cache) > 60:
                self._cache.popitem(last=False)
        return resultado

    def _sintetizar_windows(self, texto: str, idioma: str = "pt") -> tuple[np.ndarray, int]:
        import pyttsx3

        if self._pyttsx3 is None:
            try:  # o SAPI do Windows usa COM: inicializa nesta thread
                import comtypes

                comtypes.CoInitialize()
            except Exception:  # noqa: BLE001
                pass
            motor = pyttsx3.init()
            motor.setProperty("rate", 185)
            self._voz_sistema = motor.getProperty("voice")
            self._pyttsx3 = motor
        id_voz = self._voz_windows(idioma) or self._voz_sistema
        if id_voz:
            self._pyttsx3.setProperty("voice", id_voz)
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "fala.wav"
            self._pyttsx3.save_to_file(texto, str(arquivo))
            self._pyttsx3.runAndWait()
            return decodificar(arquivo.read_bytes())

    def _voz_windows(self, idioma: str) -> str | None:
        """Id da voz instalada no Windows para o idioma ("pt", "en"...), ou ``None`` se não houver."""
        if idioma not in self._vozes_windows:
            padrao = re.compile(rf"(?<![a-z]){re.escape(idioma)}[-_]|{NOMES_IDIOMA_WINDOWS.get(idioma, '$^')}")
            vozes = self._pyttsx3.getProperty("voices")
            self._vozes_windows[idioma] = next(
                (v.id for v in vozes if padrao.search(f"{v.name} {v.id} {getattr(v, 'languages', '')}".lower())), None)
        return self._vozes_windows[idioma]

    def _loop_sintese(self) -> None:
        asyncio.set_event_loop(self._loop)
        while self._rodando:
            try:
                geracao, item = self._textos.get(timeout=0.5)
            except queue.Empty:
                continue
            if geracao is None and item[0] == "__fixa__":
                try:
                    chave = (*self._perfil(None), self._com_efeito(), item[1])
                    self._ultima_foi_windows = False
                    audio = self._sintetizar(item[1])
                    if self._ultima_foi_windows:  # a voz do Windows é só um tapa-buraco: não fica fixa
                        self._cache.pop(chave, None)
                    else:
                        self._fixas[chave] = audio
                except Exception as erro:  # noqa: BLE001
                    log.info("Não consegui pré-gerar '%s': %s", item[1], erro)
                continue
            if geracao != self._geracao:
                self._concluir()
                continue
            try:
                if item[0] == "__som__":
                    audio, taxa, texto = item[1], item[2], ""
                else:
                    texto, voz = item
                    audio, taxa = self._sintetizar(texto, voz)
            except Exception:  # noqa: BLE001
                log.exception("Falha ao sintetizar fala")
                self._concluir()
                continue
            if geracao != self._geracao:
                self._concluir()
                continue
            self._audios.put((geracao, audio, taxa, texto))

    def _loop_reproducao(self) -> None:
        while self._rodando:
            try:
                geracao, audio, taxa, texto = self._audios.get(timeout=0.5)
            except queue.Empty:
                continue
            if geracao != self._geracao:
                self._concluir()
                continue
            self._tocando = True
            if texto:
                self.app.estado.definir("falando")
                self.app.barramento.publicar("fala.inicio", texto=texto)
            try:
                self.reprodutor.tocar(audio, taxa)
            except Exception:  # noqa: BLE001
                log.exception("Falha ao tocar áudio")
            finally:
                self._tocando = False
                if texto:
                    self.app.barramento.publicar("fala.fim", texto=texto)
                self._concluir()

