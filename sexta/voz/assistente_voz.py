"""Laço de voz: espera "Sexta-Feira", grava o comando, transcreve e manda para o cérebro."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

import numpy as np

from ..util.texto import remover_ativacao, so_ativacao
from .ativacao import criar_detector
from .audio import AMOSTRAS_BLOCO, SOM_ATIVACAO, SOM_ERRO, TAXA_MIC, Microfone, rms

log = logging.getLogger(__name__)

DURACAO_BLOCO = AMOSTRAS_BLOCO / TAXA_MIC
PRE_ROLAGEM_S = 1.2


class AssistenteVoz:
    def __init__(self, app) -> None:
        self.app = app
        self.mic = Microfone(app.cfg.microfone)
        self.detector = None
        self._ptt = threading.Event()
        self._rodando = False
        self._anel: deque[bytes] = deque(maxlen=int(PRE_ROLAGEM_S / DURACAO_BLOCO))
        self._ruido = 250.0
        self._ultimo_nivel = 0.0
        self.mic_ok = False

    # ------------------------------------------------------------------
    def iniciar(self) -> None:
        estado = self.app.estado
        try:
            self.detector = criar_detector(self.app.cfg)
            estado.aviso("ativacao", None)
        except Exception as erro:  # noqa: BLE001
            log.error("Ativação por voz indisponível: %s", erro)
            estado.aviso("ativacao", f"Ativação por voz desligada: {erro}")
        try:
            self.mic.iniciar()
            self.mic_ok = True
            estado.aviso("microfone", None)
        except Exception as erro:  # noqa: BLE001
            log.error("Microfone indisponível: %s", erro)
            estado.aviso("microfone", f"Microfone indisponível: {erro}")
            return
        self._rodando = True
        threading.Thread(target=self._laco, name="voz", daemon=True).start()

    def parar(self) -> None:
        self._rodando = False
        self.mic.parar()

    def ativar(self) -> None:
        """Equivale a dizer "Sexta-Feira" (botão de falar no HUD)."""
        self._ptt.set()

    # ------------------------------------------------------------------
    def _laco(self) -> None:
        while self._rodando:
            if not self.app.estado.microfone_ligado:
                self.mic.esvaziar()
                self._ptt.clear()
                time.sleep(0.2)
                continue
            bloco = self.mic.ler(0.3)
            disparou = self._ptt.is_set()
            if bloco is not None:
                self._anel.append(bloco)
                nivel = rms(bloco)
                if not self.app.fala.falando() and nivel < self._ruido * 2.5:
                    self._ruido = max(80.0, 0.995 * self._ruido + 0.005 * nivel)
                if not disparou and self.detector is not None:
                    pode = self.app.cfg.interromper_com_ativacao or not self.app.fala.falando()
                    if pode and self.detector.processar(bloco):
                        log.info("Ativação detectada")
                        disparou = True
            if disparou:
                self._ptt.clear()
                pre = list(self._anel)
                self._anel.clear()
                try:
                    self._atender(pre)
                except Exception:  # noqa: BLE001
                    log.exception("Erro ao atender comando de voz")
                    self.app.estado.definir("inativa")
                finally:
                    if self.detector is not None:
                        self.detector.reiniciar()
                    self.mic.esvaziar()

    def _atender(self, pre_rolagem: list[bytes]) -> None:
        app = self.app
        if app.lembretes.alarme_ativo():  # "Sexta-Feira!" com o alarme tocando = desligar o alarme
            app.lembretes.parar_alarme()
            app.fala.falar("Alarme desligado.")
            return
        if app.fala.falando_ou_na_fila():
            app.fala.parar()
        if app.agente.ocupado():
            app.agente.cancelar()

        texto = self._ouvir_comando(pre_rolagem)
        for _ in range(8):  # comando + continuações e interrupções, sem precisar repetir o nome
            if not texto:
                app.estado.definir("inativa")
                return
            if not app.garantir_identidade("voz"):
                app.estado.definir("inativa")
                return
            app.agente.processar(texto, canal="voz")
            if self._esperar_fala_ou_interrupcao():
                # disse "Sexta-Feira" enquanto ela falava: ela para e escuta o novo pedido
                pre = list(self._anel)
                self._anel.clear()
                texto = self._ouvir_comando(pre)
                continue
            if not app.prefs.get("modo_continuacao"):
                return
            self._limpar_eco()
            texto = self._ouvir([], espera=float(app.prefs.get("continuacao_segundos") or 6), bip=False, continuacao=True)
        app.estado.definir("inativa")

    def _ouvir_comando(self, pre_rolagem: list[bytes]) -> str | None:
        """Escuta o pedido depois do nome; se a pessoa só disse "Sexta-Feira", pergunta "Pois não?"."""
        texto = self._ouvir(pre_rolagem, espera=6.0, bip=True)
        if texto == "":
            self.app.fala.falar_e_esperar("Pois não?", timeout=8)
            self._limpar_eco()
            texto = self._ouvir([], espera=6.0, bip=False)
        return texto or None

    def _limpar_eco(self) -> None:
        """Descarta o áudio captado enquanto ela mesma falava."""
        time.sleep(0.25)
        self.mic.esvaziar()
        if self.detector is not None:
            self.detector.reiniciar()

    def _esperar_fala_ou_interrupcao(self) -> bool:
        """Espera ela terminar de falar. Retorna True se o usuário disse "Sexta-Feira" no meio."""
        fala = self.app.fala
        pode_interromper = self.detector is not None and self.app.cfg.interromper_com_ativacao
        inicio = time.monotonic()
        lidos = 0
        carencia = int(0.8 / DURACAO_BLOCO)  # ignora o comecinho da própria fala dela
        while fala.falando_ou_na_fila() and self._rodando and time.monotonic() - inicio < 180:
            bloco = self.mic.ler(0.2)
            if bloco is None:
                continue
            lidos += 1
            self._anel.append(bloco)
            if pode_interromper and lidos > carencia and self.detector.processar(bloco):
                log.info("Interrompida pelo usuário")
                fala.parar()
                self.detector.reiniciar()
                return True
            if self._ptt.is_set():  # botão de falar no HUD
                self._ptt.clear()
                fala.parar()
                return True
        return False

    def _ouvir(self, pre_rolagem: list[bytes], espera: float, bip: bool, continuacao: bool = False) -> str | None:
        """Grava e transcreve. ``None`` = ninguém falou; ``""`` = só falou o nome."""
        app = self.app
        app.estado.definir("ouvindo")
        app.barramento.publicar("escuta", continuacao=continuacao)
        if bip:
            app.fala.tocar_som(SOM_ATIVACAO)
        audio = self._gravar(pre_rolagem, espera)
        if audio is None:
            return None
        app.estado.definir("pensando")
        try:
            bruto = app.transcritor.transcrever(audio)
        except Exception as erro:  # noqa: BLE001
            log.error("Falha na transcrição: %s", erro)
            app.fala.tocar_som(SOM_ERRO)
            app.estado.aviso("whisper", f"Transcrição indisponível: {erro}")
            return None
        log.info("Ouvi: %s", bruto)
        app.barramento.publicar("transcricao", texto=bruto)
        if not bruto:
            return None
        if so_ativacao(bruto):
            return ""
        texto = remover_ativacao(bruto)
        return texto or ""

    def _gravar(self, pre_rolagem: list[bytes], espera: float, maximo: float = 15.0) -> np.ndarray | None:
        blocos = list(pre_rolagem)
        limiar = max(self._ruido * 3.0, 350.0)
        inicio = time.monotonic()
        ignorar = int(0.3 / DURACAO_BLOCO)  # os primeiros ~300 ms de áudio novo têm o bipe de ativação
        novos = 0
        falou = False
        silencio = 0.0
        fim = self.app.cfg.fim_de_fala_ms / 1000
        while self._rodando:
            bloco = self.mic.ler(0.5)
            decorrido = time.monotonic() - inicio
            if bloco is None:
                if not falou and decorrido > espera:
                    return None
                continue
            blocos.append(bloco)
            novos += 1
            nivel = rms(bloco)
            self._publicar_nivel(nivel, limiar)
            if novos <= ignorar:
                continue
            if nivel > limiar:
                falou = True
                silencio = 0.0
            elif falou:
                silencio += DURACAO_BLOCO
            if not falou and decorrido > espera:
                return None
            if falou and silencio >= fim:
                break
            if decorrido > maximo:
                break
        if not falou:
            return None
        return np.frombuffer(b"".join(blocos), dtype=np.int16).astype(np.float32) / 32768.0

    def _publicar_nivel(self, nivel: float, limiar: float) -> None:
        agora = time.monotonic()
        if agora - self._ultimo_nivel > 0.05:
            self._ultimo_nivel = agora
            self.app.barramento.publicar("mic.nivel", nivel=round(min(1.0, nivel / (limiar * 4)), 3))
