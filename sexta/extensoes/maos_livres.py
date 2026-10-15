"""Celular mãos livres e comandos remotos pelo celular.

Mãos livres: com o botão "Mãos livres" ligado na página do celular, o microfone do aparelho manda
quadros binários (int16, 16 kHz, mono, ~100 ms) pelo WebSocket de sempre. Para cada celular roda uma
linha própria numa thread: o detector da palavra de ativação ("Sexta-Feira", Vosk), uma pré-rolagem,
a gravação até o fim da fala, a transcrição e o pedido ao agente (canal "celular"). A resposta volta
só para AQUELE celular, em texto e áudio. Dizer o nome enquanto o celular toca a resposta interrompe.

Comandos remotos (digitados ou falados): "tira um print do PC e me manda", "o que está rodando aí",
"trava o PC". Com o mãos livres ligado, o celular também anuncia em voz os agentes que pedem aprovação
("Sexta-Feira, aprova o agente") e os alertas de segurança.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
import uuid
from collections import deque
from typing import Any

import numpy as np

from ..cerebro.ferramentas import LIVRE
from ..util.texto import normalizar, remover_ativacao, so_ativacao

log = logging.getLogger(__name__)

TAXA = 16000
AMOSTRAS_BLOCO = 512                 # o mesmo bloco do microfone do PC (32 ms)
BYTES_BLOCO = AMOSTRAS_BLOCO * 2
DURACAO_BLOCO = AMOSTRAS_BLOCO / TAXA
PRE_ROLAGEM_S = 1.0
MAX_QUADRO = 16000                   # 0,5 s de int16 a 16 kHz: um quadro maior é descartado
MAX_BYTES_POR_S = 48000              # ~1,5x o fluxo normal (32 kB/s): o excesso é descartado
MAX_QUADROS_POR_S = 30
ESPERA_COMANDO_S = 6.0
MAXIMO_COMANDO_S = 15.0
AUDIO_VALIDADE_S = 600
CARENCIA_INTERRUPCAO_S = 0.8         # ignora o comecinho da própria resposta tocando no celular

PREFERENCIAS = {
    "maos_livres_anuncios": True,    # no mãos livres, o celular anuncia agentes e alertas de segurança
}


class LimiteTaxa:
    """Balde de fichas por celular: limita bytes e quadros por segundo."""

    def __init__(self, bytes_por_s: int = MAX_BYTES_POR_S, quadros_por_s: int = MAX_QUADROS_POR_S) -> None:
        self.bytes_por_s, self.quadros_por_s = bytes_por_s, quadros_por_s
        self._bytes = float(bytes_por_s)
        self._quadros = float(quadros_por_s)
        self._ultimo = time.monotonic()

    def permitir(self, tamanho: int, agora: float | None = None) -> bool:
        agora = time.monotonic() if agora is None else agora
        passou = max(0.0, agora - self._ultimo)
        self._ultimo = agora
        self._bytes = min(float(self.bytes_por_s), self._bytes + passou * self.bytes_por_s)
        self._quadros = min(float(self.quadros_por_s), self._quadros + passou * self.quadros_por_s)
        if self._quadros < 1 or self._bytes < tamanho:
            return False
        self._quadros -= 1
        self._bytes -= tamanho
        return True


def rms(bloco: bytes) -> float:
    amostras = np.frombuffer(bloco, dtype=np.int16)
    if amostras.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(amostras.astype(np.float32) ** 2)))


class SessaoCelular:
    """A linha de escuta de um celular: detector -> gravação -> transcrição -> agente -> resposta."""

    def __init__(self, gerente: "GerenteMaosLivres", registrado, cliente, detector) -> None:
        self.gerente = gerente
        self.app = gerente.app
        self.registrado = registrado
        self.cliente = cliente
        self.detector = detector
        self.fila: queue.Queue[bytes] = queue.Queue(maxsize=150)  # ~15 s de quadros
        self.limite = LimiteTaxa()
        self.estado = "ouvindo"
        self.tocando = False           # o celular está tocando uma resposta
        self._tocando_desde = 0.0
        self._sobra = b""
        self._anel: deque[bytes] = deque(maxlen=int(PRE_ROLAGEM_S / DURACAO_BLOCO))
        self._ruido = 300.0
        self._rodando = True
        self.descartados = 0
        self.thread = threading.Thread(target=self._laco, name=f"maos-livres-{registrado.id}", daemon=True)

    # -- entrada ---------------------------------------------------------------------
    def receber(self, quadro: bytes) -> bool:
        if not self._rodando or not quadro or len(quadro) > MAX_QUADRO or len(quadro) % 2:
            return False
        if not self.limite.permitir(len(quadro)):
            self.descartados += 1
            return False
        try:
            self.fila.put_nowait(bytes(quadro))
        except queue.Full:
            try:  # cliente mais rápido que a escuta: descarta o mais antigo
                self.fila.get_nowait()
                self.fila.put_nowait(bytes(quadro))
            except (queue.Empty, queue.Full):
                return False
        return True

    def definir_tocando(self, tocando: bool) -> None:
        if tocando and not self.tocando:
            self._tocando_desde = time.monotonic()
        self.tocando = tocando
        if not tocando and self.estado == "falando":
            self._mudar("ouvindo")

    def parar(self) -> None:
        self._rodando = False
        try:
            self.fila.put_nowait(b"")
        except queue.Full:
            pass

    # -- saída -----------------------------------------------------------------------
    def enviar(self, tipo: str, **dados: Any) -> None:
        self.app.barramento.publicar(tipo, para=self.registrado.id, **dados)

    def _mudar(self, estado: str, **extra: Any) -> None:
        self.estado = estado
        self.enviar("maos_livres.estado", ligado=self._rodando, estado=estado, **extra)

    def responder(self, texto: str, **extra: Any) -> None:
        """Manda a resposta (texto + áudio) só para este celular."""
        audio = self.gerente.gerar_audio(texto) if texto else None
        if audio:
            self.tocando = True
            self._tocando_desde = time.monotonic()
        self.enviar("maos_livres.resposta", texto=texto, audio=audio, **extra)
        self._mudar("falando" if texto else "ouvindo")

    # -- blocos ----------------------------------------------------------------------
    def _proximo_bloco(self, timeout: float = 0.5) -> bytes | None:
        while len(self._sobra) < BYTES_BLOCO:
            try:
                quadro = self.fila.get(timeout=timeout)
            except queue.Empty:
                return None
            if not self._rodando:
                return None
            self._sobra += quadro
        bloco, self._sobra = self._sobra[:BYTES_BLOCO], self._sobra[BYTES_BLOCO:]
        return bloco

    def _esvaziar(self) -> None:
        self._sobra = b""
        while True:
            try:
                self.fila.get_nowait()
            except queue.Empty:
                break
        self._anel.clear()
        if self.detector is not None:
            self.detector.reiniciar()

    # -- laço ------------------------------------------------------------------------
    def _laco(self) -> None:
        self._mudar("ouvindo")
        while self._rodando:
            bloco = self._proximo_bloco()
            if bloco is None:
                continue
            nivel = rms(bloco)
            if self.estado in ("ouvindo", "falando") and not self.tocando:
                self._ruido = 0.95 * self._ruido + 0.05 * min(nivel, 3000.0)
            self._anel.append(bloco)
            if self.tocando and time.monotonic() - self._tocando_desde < CARENCIA_INTERRUPCAO_S:
                continue
            if not self.detector.processar(bloco):
                continue
            pre = list(self._anel)
            self._anel.clear()
            if self.tocando:  # disse o nome enquanto o celular falava: para a resposta
                self.tocando = False
                self.enviar("maos_livres.parar_audio")
            try:
                self._atender(pre)
            except Exception:  # noqa: BLE001 - a escuta não pode morrer
                log.exception("Erro no mãos livres do celular")
                self.enviar("maos_livres.resposta", texto="Tive um problema ao processar isso.", audio=None)
            finally:
                if self._rodando and self.estado != "falando":
                    self._mudar("ouvindo")
                self.detector.reiniciar()
        log.info("Mãos livres encerrado para %s", getattr(self.cliente, "nome", "?"))

    def _atender(self, pre: list[bytes]) -> None:
        self.enviar("maos_livres.ativado")  # o celular toca o bipe
        texto = self._ouvir(pre)
        if texto == "":  # só disse "Sexta-Feira"
            from ..cerebro import personalidade

            self.responder(personalidade.resposta(self.app.prefs, "chamada"))
            texto = self._ouvir([], esperar_resposta=True)
        if not texto:
            return
        app = self.app
        if app.sessao.bloqueada:
            dica = "Desbloqueie com o PIN aqui no celular" if app.acesso.tem_pin() else "Desbloqueie no computador"
            self.responder(f"Estou bloqueada. {dica} e peça de novo.", transcricao=texto)
            return
        self._mudar("pensando")
        resposta = app.agente.processar(texto, canal="celular", cliente=self.cliente, falar=False) or {}
        final = resposta.get("texto") or ""
        imagem = imagem_da_resposta(app, resposta)
        self._esvaziar()  # o que chegou enquanto ela pensava não é pedido
        self.responder(final, transcricao=texto, id=resposta.get("id"), imagem=imagem)

    def _ouvir(self, pre: list[bytes], esperar_resposta: bool = False) -> str | None:
        """Grava e transcreve. ``None`` = ninguém falou; ``""`` = só falou o nome."""
        if esperar_resposta:  # espera o "Pois não?" tocar no celular
            limite = time.monotonic() + 6
            while self.tocando and self._rodando and time.monotonic() < limite:
                time.sleep(0.05)
            self._esvaziar()
        self._mudar("gravando")
        audio = self.gravar(pre, ESPERA_COMANDO_S)
        if audio is None:
            return None
        self._mudar("pensando")
        try:
            bruto = self.app.transcritor.transcrever(audio)
        except Exception as erro:  # noqa: BLE001
            log.error("Falha na transcrição (celular): %s", erro)
            self.enviar("maos_livres.resposta", texto=f"Não consegui transcrever: {erro}", audio=None)
            return None
        log.info("Ouvi (celular): %s", bruto)
        if not bruto:
            return None
        if so_ativacao(bruto):
            return ""
        return remover_ativacao(bruto) or ""

    def gravar(self, pre: list[bytes], espera: float, maximo: float = MAXIMO_COMANDO_S) -> np.ndarray | None:
        """Grava até o fim da fala (mesma lógica de volume do microfone do PC); ``None`` se ninguém falou."""
        blocos = list(pre)
        limiar = max(self._ruido * 3.0, 350.0)
        ignorar = int(0.3 / DURACAO_BLOCO)  # o bipe de ativação toca no celular
        novos = 0
        falou = False
        silencio = 0.0
        fim = (getattr(self.app.cfg, "fim_de_fala_ms", 850) or 850) / 1000
        gravado = 0.0
        sem_audio = 0.0
        while self._rodando:
            bloco = self._proximo_bloco(0.5)
            if bloco is None:
                sem_audio += 0.5
                if sem_audio > espera:  # o celular parou de mandar áudio
                    break
                continue
            blocos.append(bloco)
            novos += 1
            gravado += DURACAO_BLOCO
            if novos <= ignorar:
                continue
            if rms(bloco) > limiar:
                falou = True
                silencio = 0.0
            elif falou:
                silencio += DURACAO_BLOCO
            if not falou and gravado > espera:
                return None
            if falou and silencio >= fim:
                break
            if gravado > maximo:
                break
        if not falou:
            return None
        return np.frombuffer(b"".join(blocos), dtype=np.int16).astype(np.float32) / 32768.0


def imagem_da_resposta(app, resposta: dict) -> dict | None:
    """Se o pedido tirou um print, devolve ``{"url", "legenda"}`` para o celular mostrar na conversa."""
    if not any(r.get("ferramenta") == "computador" and r.get("ok") for r in resposta.get("resultados") or []):
        return None
    try:
        for holo in reversed(app.hologramas.lista()):
            if holo.get("tipo") == "imagem" and str((holo.get("dados") or {}).get("url", "")).startswith("/api/prints/"):
                return {"url": holo["dados"]["url"], "legenda": holo["dados"].get("legenda", "Print da tela")}
    except Exception:  # noqa: BLE001
        log.debug("Sem holograma de imagem", exc_info=True)
    return None


class GerenteMaosLivres:
    """As sessões de mãos livres por celular conectado, os áudios gerados e os anúncios."""

    def __init__(self, app) -> None:
        self.app = app
        self.sessoes: dict[int, SessaoCelular] = {}
        self.audios: dict[str, tuple[bytes, str, float]] = {}
        self._lock = threading.Lock()
        self._anunciados: set[tuple] = set()
        self._status_agentes: dict[str, str] = {}
        self.criar_detector = self._criar_detector_padrao

    def _criar_detector_padrao(self):
        from ..voz.ativacao import criar_detector

        return criar_detector(self.app.cfg)

    # -- liga/desliga -----------------------------------------------------------------
    def ligar(self, registrado, cliente) -> tuple[bool, str]:
        if getattr(registrado, "tipo", "") != "celular":
            return False, "O mãos livres é só para o celular."
        with self._lock:
            if registrado.id in self.sessoes:
                return True, ""
        try:
            detector = self.criar_detector()
        except Exception as erro:  # noqa: BLE001 - Vosk/Porcupine ausente
            log.warning("Mãos livres sem detector: %s", erro)
            return False, (f"Não consegui ligar a palavra de ativação: {erro}. No PC, rode "
                           "pip install vosk e python -m sexta baixar.")
        if detector is None:
            return False, "A palavra de ativação está desligada (ATIVACAO_MOTOR). Ligue no .env para usar o mãos livres."
        sessao = SessaoCelular(self, registrado, cliente, detector)
        with self._lock:
            self.sessoes[registrado.id] = sessao
        sessao.thread.start()
        log.info("Mãos livres ligado no celular %s", getattr(cliente, "nome", "?"))
        return True, ""

    def desligar(self, id_cliente: int) -> None:
        with self._lock:
            sessao = self.sessoes.pop(id_cliente, None)
        if sessao is not None:
            sessao.parar()
            self.app.barramento.publicar("maos_livres.estado", para=id_cliente, ligado=False, estado="desligado")

    def sessao(self, id_cliente: int) -> SessaoCelular | None:
        with self._lock:
            return self.sessoes.get(id_cliente)

    def receber_audio(self, registrado, dados: bytes) -> bool:
        sessao = self.sessao(registrado.id)  # mãos livres desligado: ignora
        return sessao.receber(dados) if sessao is not None else False

    def encerrar(self) -> None:
        for id_cliente in list(self.sessoes):
            self.desligar(id_cliente)

    # -- áudio ------------------------------------------------------------------------
    def gerar_audio(self, texto: str) -> str | None:
        try:
            gerado = self.app.fala.gerar_audio(texto)
        except Exception as erro:  # noqa: BLE001
            log.warning("Áudio para o celular falhou: %s", erro)
            gerado = None
        if not gerado:
            return None  # o celular fala com a voz do próprio navegador
        agora = time.time()
        with self._lock:
            for chave in [k for k, v in self.audios.items() if agora - v[2] > AUDIO_VALIDADE_S]:
                self.audios.pop(chave, None)
            id_audio = uuid.uuid4().hex
            self.audios[id_audio] = (gerado[0], gerado[1], agora)
        return f"/api/maos_livres/audio/{id_audio}"

    # -- anúncios (agentes e segurança) ------------------------------------------------
    def anunciar(self, texto: str, nivel: str = "info") -> None:
        """Fala o aviso nos celulares com mãos livres ligado."""
        if not self.app.prefs.get("maos_livres_anuncios", True):
            return
        sessoes = list(self.sessoes.values())
        if not sessoes:
            return
        audio = self.gerar_audio(texto)
        for sessao in sessoes:
            if audio:
                sessao.tocando = True
                sessao._tocando_desde = time.monotonic()
            sessao.enviar("maos_livres.anuncio", texto=texto, audio=audio, nivel=nivel)

    def ao_evento(self, evento: dict) -> None:
        """Ouvinte do barramento: transforma eventos de agentes e de segurança em anúncios."""
        tipo = evento.get("tipo")
        frases: list[tuple[str, str]] = []
        if tipo == "agentes":
            for agente in evento.get("agentes") or []:
                frases.extend(self._frases_agente(agente))
        elif tipo == "aviso" and evento.get("nivel") == "erro" and "seguranca" in normalizar(str(evento.get("texto", ""))):
            chave = ("aviso", evento.get("texto"))
            if chave not in self._anunciados:
                self._anunciados.add(chave)
                texto = str(evento.get("texto"))
                frases.append((f"Alerta de segurança. {texto}", "alerta"))
                # todo celular (mesmo sem mãos livres) vibra e mostra a notificação do sistema
                self.app.barramento.publicar("maos_livres.alerta", para="celular", titulo="Alerta de segurança", texto=texto)
        if frases and self.sessoes:
            threading.Thread(target=lambda: [self.anunciar(t, n) for t, n in frases],
                             name="maos-livres-anuncio", daemon=True).start()

    def _frases_agente(self, agente: dict) -> list[tuple[str, str]]:
        frases = []
        id_ = str(agente.get("id"))
        rotulo = agente.get("rotulo") or "agente"
        status = agente.get("status") or ""
        anterior = self._status_agentes.get(id_)
        self._status_agentes[id_] = status
        pendente = agente.get("pendente")
        if status == "aguardando" and pendente:
            chave = ("aprovacao", id_, pendente.get("descricao"))
            if chave not in self._anunciados:
                self._anunciados.add(chave)
                numero = agente.get("numero")
                frases.append((f"O agente {rotulo} quer {pendente.get('descricao')}. Diga: Sexta-Feira, aprova o agente"
                               f"{' ' + str(numero) if numero else ''}. Ou: nega o agente.", "aprovacao"))
        elif anterior and anterior != status and status in ("concluido", "parcial", "falhou"):
            fim = {"concluido": "terminou", "parcial": "terminou em parte"}.get(status, "não conseguiu")
            frases.append((f"O agente {rotulo} {fim}. Detalhes na tela.", "info"))
        return frases


# ---------------------------------------------------------------------------- comandos remotos
_PRINT_REMOTO = re.compile(
    r"^(?:(?:me )?(?:tira|tirar|faz|fazer|da|manda|mandar|envia|enviar|mostra|mostrar)(?: ai| pra mim| para mim)?)"
    r"(?: um| uma| o)? (?:print|printscreen|captura(?: de tela)?|foto da tela)"
    r"(?: da tela| do (?:pc|computador)| da tela do (?:pc|computador))?"
    r"(?: e (?:me )?(?:manda|envia|mostra|passa)(?: aqui| pra mim| para mim| no celular)?)?"
    r"(?: aqui| pra mim| para mim| no celular)?$")
_O_QUE_RODA = re.compile(
    r"^(?:o )?que (?:(?:e )?que )?(?:esta|ta|tem) (?:rodando|aberto|abertos|ligado|executando)"
    r"(?: ai| la)?(?: no (?:pc|computador))?(?: agora)?$|"
    r"^o que (?:esta|ta) (?:rodando|aberto) (?:ai|no (?:pc|computador))(?: agora)?$|"
    r"^(?:quais|que) (?:programas|apps|aplicativos|janelas) (?:estao|tao) (?:abert[oa]s|rodando)"
    r"(?: ai| no (?:pc|computador))?(?: agora)?$")
_TRAVAR_REMOTO = re.compile(
    r"^(?:trava|travar|bloqueia|bloquear|tranca|trancar)(?: o| a)? (?:pc|computador|tela|tela do (?:pc|computador))"
    r"(?: ai| la)?(?: pra mim| para mim)?(?: agora)?$")


def _lista(nomes: list[str]) -> str:
    if len(nomes) <= 1:
        return "".join(nomes)
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]


def resumo_pc(app, canal: str = "voz") -> dict:
    """Janelas abertas + apps que mais usam CPU, curto para a voz e em linhas para o celular."""
    from ..habilidades import janelas, processos, windows

    apps_abertos: list[str] = []
    titulos: list[str] = []
    try:
        for janela in janelas.listar():
            nome = (janela.exe or "").strip()
            if nome and nome not in apps_abertos and nome not in ("sexta", "python", "pythonw"):
                apps_abertos.append(nome)
                titulos.append(janela.titulo)
    except (windows.NaoSuportado, OSError, AttributeError) as erro:
        log.debug("Janelas indisponíveis: %s", erro)
    try:
        pesados = [p for p in processos.top("cpu", limite=3, amostra=0.5) if p.get("cpu", 0) >= 1]
    except Exception as erro:  # noqa: BLE001
        log.debug("Processos indisponíveis: %s", erro)
        pesados = []
    if not apps_abertos and not pesados:
        return {"ok": False, "resumo": "Não consegui ver o que está rodando no PC agora."}
    if canal == "celular":
        linhas = []
        if apps_abertos:
            linhas.append(f"Abertos ({len(apps_abertos)}):")
            linhas += [f"• {a} — {t[:48]}" for a, t in zip(apps_abertos[:8], titulos[:8])]
            if len(apps_abertos) > 8:
                linhas.append(f"• e mais {len(apps_abertos) - 8}")
        if pesados:
            linhas.append("Mais pesados agora: " + ", ".join(f"{p['nome']} {p['cpu']:.0f}%" for p in pesados) + " de CPU.")
        texto = "\n".join(linhas)
    else:
        partes = []
        if apps_abertos:
            extra = f" e mais {len(apps_abertos) - 5}" if len(apps_abertos) > 5 else ""
            partes.append(f"Abertos no PC: {_lista(apps_abertos[:5])}{extra}.")
        if pesados:
            partes.append("O que mais usa CPU agora: " + _lista([f"{p['nome']} com {p['cpu']:.0f}%" for p in pesados]) + ".")
        texto = " ".join(partes)
    return {"ok": True, "resumo": texto, "abertos": apps_abertos, "pesados": pesados}


def atalho(t: str, ctx, rodar, original: str | None):
    if _PRINT_REMOTO.match(t):
        executar = rodar("computador", {"acao": "print"})

        def print_remoto() -> str:
            resposta = executar()
            if ctx.canal != "celular" or not any(r.get("ferramenta") == "computador" and r.get("ok") for r in ctx.resultados):
                return resposta
            return "Pronto, aqui está o print da tela do PC."
        return print_remoto
    if _O_QUE_RODA.match(t):
        return rodar("o_que_esta_rodando", {})
    if _TRAVAR_REMOTO.match(t):
        executar = rodar("computador", {"acao": "bloquear"})

        def travar() -> str:
            resposta = executar()
            ok = any(r.get("ferramenta") == "computador" and r.get("ok") for r in ctx.resultados)
            if ok and ctx.canal == "celular":
                if ctx.app.sessao.bloqueada:
                    return "PC bloqueado. Para me usar de novo, desbloqueie com o PIN ou no computador."
                return "PC bloqueado."
            return resposta
        return travar
    return None


# ---------------------------------------------------------------------------- ganchos
def instalar(app) -> None:
    app.maos_livres = GerenteMaosLivres(app)
    app.barramento.ouvir(app.maos_livres.ao_evento)


def registrar(app, registro) -> None:
    @registro.ferramenta(
        "o_que_esta_rodando",
        "Resumo do que está aberto e rodando no PC agora: janelas abertas e os apps que mais usam CPU. "
        "Use para 'o que está rodando aí', 'o que tá aberto no PC'.",
        direta=True, nivel=LIVRE,
    )
    def o_que_esta_rodando(ctx):
        return resumo_pc(app, ctx.canal)


def receber_audio(app, registrado, dados: bytes) -> bool:
    """Chamado pelo WebSocket do servidor com cada quadro binário (só clientes do tipo "celular")."""
    gerente: GerenteMaosLivres | None = getattr(app, "maos_livres", None)
    if gerente is None or getattr(registrado, "tipo", "") != "celular":
        return False
    return gerente.receber_audio(registrado, dados)


def desconectar(app, registrado) -> None:
    gerente: GerenteMaosLivres | None = getattr(app, "maos_livres", None)
    if gerente is not None:
        gerente.desligar(registrado.id)


async def mensagem_ws(app, cliente, registrado, mensagem: dict, websocket) -> bool:
    tipo = mensagem.get("tipo")
    if tipo not in ("maos_livres", "maos_livres.tocando"):
        return False
    gerente: GerenteMaosLivres | None = getattr(app, "maos_livres", None)
    if gerente is None or cliente.tipo != "celular":
        return True
    if tipo == "maos_livres.tocando":
        sessao = gerente.sessao(registrado.id)
        if sessao is not None:
            sessao.definir_tocando(bool(mensagem.get("tocando")))
        return True
    if mensagem.get("ligar"):
        import asyncio

        ok, motivo = await asyncio.to_thread(gerente.ligar, registrado, cliente)
        if not ok:
            await websocket.send_json({"tipo": "maos_livres.estado", "ligado": False, "estado": "desligado", "erro": motivo})
    else:
        gerente.desligar(registrado.id)
    return True


def rotas(api, app, autenticado, so_pc) -> None:
    from fastapi import Depends, HTTPException, Response

    @api.get("/api/maos_livres/audio/{id_audio}")
    def audio_maos_livres(id_audio: str, _=Depends(autenticado)):
        item = app.maos_livres.audios.get(id_audio)
        if not item:
            raise HTTPException(404, "Áudio expirado")
        return Response(item[0], media_type=item[1], headers={"Cache-Control": "no-store"})

    @api.get("/api/maos_livres/estado")
    def estado_maos_livres(_=Depends(autenticado)):
        return {"sessoes": [{"id": s.registrado.id, "nome": getattr(s.cliente, "nome", ""), "estado": s.estado}
                            for s in list(app.maos_livres.sessoes.values())]}


def diagnostico(app) -> list[dict]:
    motor = getattr(app.cfg, "ativacao_motor", "vosk")
    if motor in {"nenhum", "desligado", "off"}:
        return [{"nome": "Celular mãos livres", "ok": False, "detalhe": "Palavra de ativação desligada.",
                 "dica": "Ligue ATIVACAO_MOTOR=vosk no .env para usar o mãos livres no celular."}]
    if motor == "porcupine":
        return [{"nome": "Celular mãos livres", "ok": True, "detalhe": "Ativação pelo Porcupine.", "dica": ""}]
    try:
        import vosk  # noqa: F401
    except ImportError:
        return [{"nome": "Celular mãos livres", "ok": False, "detalhe": "Vosk não instalado.",
                 "dica": "pip install vosk e depois python -m sexta baixar."}]
    modelo = app.cfg.modelos / "vosk-model-small-pt-0.3"
    return [{"nome": "Celular mãos livres", "ok": modelo.exists(),
             "detalhe": "Palavra de ativação pronta para o celular." if modelo.exists() else "Modelo do Vosk ausente.",
             "dica": "" if modelo.exists() else "Rode python -m sexta baixar."}]


def encerrar(app) -> None:
    gerente = getattr(app, "maos_livres", None)
    if gerente is not None:
        gerente.encerrar()
