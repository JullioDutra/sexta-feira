"""Traje: sequência de inicialização, diagnóstico do PC, alertas proativos e overlay de jogo.

Inicialização ("sistemas online"): ao ligar, confere cada módulo em ordem (cérebro, microfone, câmera,
Whisper, rosto, gestos, agenda, jornal, protocolos, extensões) e publica o evento "inicializacao" a cada
~250 ms para a animação do HUD; no fim, um som de energia subindo e "Sexta-Feira online. Todos os sistemas
operacionais." (ou o que falhou). Preferência ``sequencia_inicial`` (desligada = a saudação antiga).

Diagnóstico ("status do traje", "relatório do traje", "como está o traje?"): temperaturas de CPU e GPU, uso
e memória da placa de vídeo, discos (espaço e saúde), rede (ping e Wi-Fi), atualizações pendentes, saúde da
bateria e o resumo da última revisão de segurança, no holograma "traje" (leituras em ``traje_sensores``).

Alertas proativos (``alertas_proativos``): CPU/GPU quentes por 5 minutos seguidos, chuva chegando na
próxima hora e pouco espaço no disco do sistema. Falam, aparecem no HUD e vão para o celular; os que não
são urgentes (chuva, disco) esperam o fim do modo foco.

Modo jogo automático e overlay ("liga o overlay", "desliga o overlay", "liga o modo jogo automático"): ver
``traje_jogo``.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import threading
import time
from datetime import date, datetime
from typing import Any, Callable

from ..cerebro.ferramentas import P
from ..util.tempo import saudacao
from .traje_jogo import (JanelaOverlay, LeitorPresentMon, caminho_edge, caminho_presentmon, listar_processos,
                         nome_amigavel, procurar_jogo)
from .traje_sensores import DICA_LHM, Sensores

log = logging.getLogger(__name__)

PREFERENCIAS = {
    "sequencia_inicial": True,      # animação "sistemas online" ao ligar (desligada = saudação simples)
    "alertas_proativos": True,      # chave geral dos alertas abaixo
    "alerta_temperatura": True,
    "alerta_cpu_temp": 95,          # °C, por 5 minutos seguidos
    "alerta_gpu_temp": 90,
    "alerta_chuva": True,
    "alerta_disco": True,
    "modo_jogo_auto": True,         # desempenho máximo + não perturbe quando um jogo abre
    "overlay_jogo": True,           # abre o overlay (FPS, temperaturas) junto com o jogo
    "jogos": [],                    # executáveis extras tratados como jogo (ex.: "minecraft.exe")
}
HOLOGRAMAS = {"traje": "Diagnóstico do traje"}
EVENTOS_ALTA_FREQUENCIA = {"traje.overlay"}

INTERVALO_INICIALIZACAO_S = 0.25
SUSTENTAR_S = 300          # temperatura alta por 5 minutos -> alerta
REARMAR_S = 120            # e só volta a avisar depois de 2 minutos abaixo de (limite - 5)
HISTERESE = 5
CHECAR_TEMPERATURA_S = 30
CHECAR_CHUVA_S = 600
CHECAR_DISCO_S = 1800
CHECAR_JOGO_S = 5
DISCO_MINIMO_PCT = 10
CHUVA_MINIMA_MM = 0.2


# -- alertas (independente do Windows, testável) ------------------------------------------------------
class AlertaSustentado:
    """Dispara uma vez quando o valor fica >= limite por ``sustentar`` segundos; rearma depois de ``rearmar``
    segundos abaixo de (limite - histerese)."""

    def __init__(self, sustentar: float = SUSTENTAR_S, rearmar: float = REARMAR_S, histerese: float = HISTERESE) -> None:
        self.sustentar, self.rearmar, self.histerese = sustentar, rearmar, histerese
        self.acima_desde: float | None = None
        self.abaixo_desde: float | None = None
        self.disparado = False

    def atualizar(self, valor: float | None, limite: float, agora: float) -> bool:
        if valor is None:
            return False
        if valor >= limite:
            self.abaixo_desde = None
            if self.acima_desde is None:
                self.acima_desde = agora
            if not self.disparado and agora - self.acima_desde >= self.sustentar:
                self.disparado = True
                return True
            return False
        self.acima_desde = None
        if self.disparado and valor < limite - self.histerese:
            self.abaixo_desde = self.abaixo_desde if self.abaixo_desde is not None else agora
            if agora - self.abaixo_desde >= self.rearmar:
                self.disparado, self.abaixo_desde = False, None
        else:
            self.abaixo_desde = None
        return False

    def minutos_acima(self, agora: float) -> int:
        return max(1, round((agora - (self.acima_desde or agora)) / 60))


def frase_chuva(minutos: int, tratamento: str) -> str:
    if minutos <= 2:
        return f"{tratamento}, vai começar a chover a qualquer momento."
    aproximado = minutos if minutos < 10 else int(5 * round(minutos / 5))
    return f"{tratamento}, vai chover em uns {aproximado} minutos."


# -- relatório (independente do Windows, testável) ----------------------------------------------------
def resumo_seguranca(historico: list[dict]) -> dict:
    """Defender, firewall e data da última revisão de segurança do PC (extensão ``seguranca``)."""
    revisao = next((h for h in historico if h.get("tipo") == "pc"), None)
    if revisao is None:
        return {"defender": "não verificado", "firewall": "não verificado", "ultima_revisao": None, "risco": None,
                "nivel": "aviso", "dica": "Diga “revisa a segurança do PC”."}
    itens = {i.get("id"): i for i in revisao.get("itens") or []}
    defender = itens.get("defender-tempo-real")
    if defender is None:
        texto_defender, ok_defender = "não verificado", None
    elif defender.get("risco") == "ok":
        texto_defender = "passivo (outro antivírus)" if "passivo" in defender.get("titulo", "").lower() else "ligado"
        ok_defender = True
    else:
        texto_defender, ok_defender = "desligado", False
    firewall = itens.get("firewall")
    if firewall is None:
        texto_firewall, ok_firewall = "não verificado", None
    elif firewall.get("risco") == "ok":
        texto_firewall, ok_firewall = "ligado", True
    else:
        texto_firewall, ok_firewall = "desligado", False
    nivel = "falha" if False in (ok_defender, ok_firewall) else "ok" if revisao.get("risco") == "baixo" else "aviso"
    return {"defender": texto_defender, "firewall": texto_firewall, "ultima_revisao": revisao.get("quando"),
            "risco": revisao.get("risco"), "nivel": nivel, "dica": ""}


def _graus(valor: float | None) -> str:
    return f"{round(valor)} graus" if valor is not None else ""


def montar_relatorio(leituras: dict, seguranca: dict | None, limites: tuple[float, float] = (95, 90)) -> dict:
    """Junta as leituras dos sensores no formato do holograma, com os pontos de atenção."""
    cpu_lim, gpu_lim = limites
    temps = leituras.get("temperaturas") or {}
    uso = leituras.get("uso") or {}
    gpu = leituras.get("gpu") or {}
    espaco = leituras.get("espaco") if isinstance(leituras.get("espaco"), list) else []
    saude = leituras.get("saude_discos") or {}
    rede = leituras.get("rede") or {}
    atualizacoes = leituras.get("atualizacoes") or {}
    bateria = leituras.get("bateria") or {}
    atencao: list[dict] = []  # {"texto": falado, "nivel"}

    cpu_temp = temps.get("cpu")
    if cpu_temp is not None and cpu_temp >= cpu_lim - 10:
        atencao.append({"texto": f"CPU a {_graus(cpu_temp)}", "nivel": "falha" if cpu_temp >= cpu_lim else "aviso"})
    gpu_temp = gpu.get("temp")
    if gpu_temp is not None and gpu_temp >= gpu_lim - 10:
        atencao.append({"texto": f"GPU a {_graus(gpu_temp)}", "nivel": "falha" if gpu_temp >= gpu_lim else "aviso"})
    for u in espaco:
        livre = 100 - u["pct"]
        if livre < 20:
            atencao.append({"texto": f"disco {u['unidade'].rstrip(':')} com só {livre}% livre",
                            "nivel": "falha" if livre < DISCO_MINIMO_PCT else "aviso"})
    for d in saude.get("discos") or []:
        if not d.get("ok"):
            atencao.append({"texto": f"o disco {d['nome']} está {d['saude']}", "nivel": "falha"})
    if rede and rede.get("ping_ms") is None and "ping_ms" in rede:
        atencao.append({"texto": "sem internet", "nivel": "falha"})
    elif (rede.get("ping_ms") or 0) > 150:
        atencao.append({"texto": f"ping alto, {rede['ping_ms']} milissegundos", "nivel": "aviso"})
    pendentes = atualizacoes.get("windows")
    if pendentes:
        atencao.append({"texto": f"{pendentes} atualizaç{'ões' if pendentes > 1 else 'ão'} do Windows pendente{'s' if pendentes > 1 else ''}",
                        "nivel": "aviso"})
    if bateria.get("presente") and (bateria.get("saude_pct") or 100) < 70:
        atencao.append({"texto": f"bateria com {bateria['saude_pct']}% da capacidade original", "nivel": "aviso"})
    if seguranca and seguranca.get("nivel") == "falha":
        desligados = [n for n, v in (("Defender", seguranca["defender"]), ("firewall", seguranca["firewall"])) if v == "desligado"]
        atencao.append({"texto": " e ".join(desligados) + (" desligados" if len(desligados) > 1 else " desligado"), "nivel": "falha"})

    nivel = "falha" if any(a["nivel"] == "falha" for a in atencao) else "aviso" if atencao else "ok"
    return {
        "quando": datetime.now().isoformat(timespec="seconds"),
        "nivel": nivel,
        "atencao": atencao,
        "cpu": {"temp": cpu_temp, "uso": uso.get("cpu"), "fonte": temps.get("fonte", ""),
                "erro": temps.get("erro", "") if cpu_temp is None else "", "limite": cpu_lim},
        "gpu": {**{k: gpu.get(k) for k in ("nome", "temp", "uso", "vram_usada", "vram_total", "fonte")},
                "erro": gpu.get("erro", ""), "limite": gpu_lim},
        "ram": {"pct": uso.get("ram"), "usada": uso.get("ram_usada"), "total": uso.get("ram_total")},
        "discos": espaco,
        "saude_discos": saude.get("discos") or [],
        "saude_erro": saude.get("erro", ""),
        "rede": {"ping_ms": rede.get("ping_ms"), "ssid": rede.get("ssid"), "erro": rede.get("erro", "")},
        "atualizacoes": {k: atualizacoes.get(k) for k in ("windows", "winget", "verificado", "verificando", "erro")},
        "bateria": bateria,
        "seguranca": seguranca,
    }


def resumo_falado(r: dict) -> str:
    """1 a 3 frases curtas para a voz (o detalhe fica no holograma)."""
    atencao = r.get("atencao") or []
    if atencao:
        textos = [a["texto"] for a in sorted(atencao, key=lambda a: a["nivel"] != "falha")[:3]]
        lista = textos[0] if len(textos) == 1 else ", ".join(textos[:-1]) + " e " + textos[-1]
        quantos = "um ponto" if len(atencao) == 1 else f"{len(atencao)} pontos"
        return f"Traje operacional, com {quantos} de atenção: {lista}. Os detalhes estão no holograma."
    partes = []
    if r["cpu"].get("temp") is not None:
        partes.append(f"CPU a {_graus(r['cpu']['temp'])}")
    if r["gpu"].get("temp") is not None:
        partes.append(f"GPU a {_graus(r['gpu']['temp'])}")
    sistema = next((d for d in r.get("discos") or [] if d.get("sistema")), None)
    if sistema:
        partes.append(f"disco {sistema['unidade'].rstrip(':')} com {100 - sistema['pct']}% livre")
    if r["rede"].get("ping_ms") is not None:
        partes.append(f"ping de {r['rede']['ping_ms']} milissegundos")
    if not partes:
        return "Traje em ordem."
    lista = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]
    return f"Traje em ordem: {lista}."


# -- sequência de inicialização -----------------------------------------------------------------------
FALHAS_FALADAS = {"cerebro": "Cérebro offline", "microfone": "Microfone indisponível", "camera": "Câmera indisponível",
                  "whisper": "Transcrição de voz indisponível"}


class Inicializacao:
    """Confere os módulos em paralelo e publica um por vez, em ordem, para a animação do HUD."""

    def __init__(self, app) -> None:
        self.app = app
        self.ultima: dict | None = None
        self._lock = threading.Lock()

    def checagens(self) -> list[tuple[str, str, Callable[[], tuple[str, str]]]]:
        """[(id, rótulo, função -> (nivel "ok"|"aviso"|"falha", detalhe))]."""
        app = self.app
        claude = app.cfg.usa_claude()
        return [
            ("cerebro", "Cérebro (Claude)" if claude else "Cérebro (Ollama)", self._cerebro),
            ("microfone", "Microfone", lambda: ("ok", "capturando") if app.voz.mic_ok else ("falha", "sem microfone")),
            ("camera", "Câmera", self._camera),
            ("whisper", "Transcrição (Whisper)", self._whisper),
            ("rosto", "Reconhecimento facial", self._rosto),
            ("gestos", "Gestos", lambda: ("ok", "modelo pronto") if app.maos.disponivel() else ("aviso", "modelo ausente")),
            ("agenda", "Agenda", lambda: ("ok", f"{len(app.agenda.urls)} calendário(s)") if app.agenda.configurada()
             else ("aviso", "não configurada")),
            ("jornal", "Jornal", self._jornal),
            ("protocolos", "Protocolos", self._protocolos),
            ("extensoes", "Extensões", self._extensoes),
        ]

    def _cerebro(self) -> tuple[str, str]:
        ok, mensagem = self.app.agente.ollama.verificar()
        return ("ok" if ok else "falha"), mensagem

    def _camera(self) -> tuple[str, str]:
        if importlib.util.find_spec("cv2") is None:
            return "falha", "OpenCV não instalado"
        erro = self.app.camera.erro
        return ("falha", erro) if erro else ("ok", "liga quando precisa")

    def _whisper(self) -> tuple[str, str]:
        app = self.app
        limite = time.monotonic() + 8
        while app.transcritor._modelo is None and time.monotonic() < limite:
            if app.estado.avisos.get("whisper"):
                break
            time.sleep(0.2)
        if app.transcritor._modelo is not None:
            return "ok", f"{app.cfg.whisper_modelo} em {app.transcritor.dispositivo}"
        if app.estado.avisos.get("whisper"):
            return "falha", app.estado.avisos["whisper"]
        return "aviso", "carregando em segundo plano"

    def _rosto(self) -> tuple[str, str]:
        rosto = self.app.rosto
        if not rosto.modelos_presentes():
            return "aviso", "modelos ausentes (python -m sexta baixar)"
        return ("ok", "cadastrado") if rosto.cadastrado() else ("aviso", "sem cadastro")

    def _jornal(self) -> tuple[str, str]:
        fontes = sum(len(v) for v in self.app.jornal.fontes.values())
        return ("ok" if fontes else "aviso"), f"{fontes} fonte{'s' if fontes != 1 else ''}"

    def _protocolos(self) -> tuple[str, str]:
        rotinas = self.app.rotinas.listar()
        automaticos = sum(1 for r in rotinas if r.ativo and r.automatico())
        return "ok", f"{len(rotinas)} protocolo{'s' if len(rotinas) != 1 else ''}, {automaticos} automático{'s' if automaticos != 1 else ''}"

    def _extensoes(self) -> tuple[str, str]:
        from . import carregar

        nomes = [m.__name__.rsplit(".", 1)[-1] for m in carregar()]
        return "ok", f"{len(nomes)} carregadas"

    def executar(self, complemento: str = "", esperar_hud: float = 5.0, falar: bool = True) -> dict:
        """Roda a sequência inteira (bloqueia por ~3 s) e fala o resultado. Devolve o resumo."""
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "resumo": "A sequência de inicialização já está rodando."}
        try:
            return self._executar(complemento, esperar_hud, falar)
        finally:
            self._lock.release()

    def _executar(self, complemento: str, esperar_hud: float, falar: bool) -> dict:
        from ..voz.audio import SOM_INICIALIZACAO

        app = self.app
        limite = time.monotonic() + esperar_hud
        while not app.barramento.tem_hud_no_pc() and time.monotonic() < limite:
            time.sleep(0.2)  # o HUD acabou de abrir: espera ele conectar para ver a animação
        checagens = self.checagens()
        total = len(checagens)
        resultados: list[dict | None] = [None] * total
        prontos = [threading.Event() for _ in checagens]

        def rodar(i: int, funcao: Callable[[], tuple[str, str]]) -> None:
            try:
                nivel, detalhe = funcao()
            except Exception as erro:  # noqa: BLE001 - um módulo com erro aparece como falha
                nivel, detalhe = "falha", str(erro)[:160]
            resultados[i] = {"nivel": nivel, "detalhe": detalhe}
            prontos[i].set()

        for i, (_id, _rotulo, funcao) in enumerate(checagens):
            threading.Thread(target=rodar, args=(i, funcao), name=f"inicializacao-{_id}", daemon=True).start()
        itens: list[dict] = []
        for i, (id_, rotulo, _funcao) in enumerate(checagens):
            inicio = time.monotonic()
            if not prontos[i].wait(12):
                resultados[i] = {"nivel": "falha", "detalhe": "sem resposta"}
            r = resultados[i] or {"nivel": "falha", "detalhe": "?"}
            item = {"id": id_, "modulo": rotulo, "ok": r["nivel"] != "falha", "nivel": r["nivel"], "detalhe": r["detalhe"]}
            itens.append(item)
            app.barramento.publicar("inicializacao", fase="checando", indice=i + 1, total=total, modulo=rotulo,
                                    ok=item["ok"], nivel=item["nivel"], detalhe=item["detalhe"], itens=list(itens))
            time.sleep(max(0.0, INTERVALO_INICIALIZACAO_S - (time.monotonic() - inicio)))
        falhas = [i for i in itens if not i["ok"]]
        if falhas:
            texto_falhas = ". ".join(FALHAS_FALADAS.get(f["id"], f"{f['modulo']} com problema") for f in falhas[:3]) + "."
            frase = f"Sexta-Feira online. {texto_falhas}"
        else:
            frase = "Sexta-Feira online. Todos os sistemas operacionais."
        nome = app.prefs.get("nome")
        frase += f" {saudacao()}{', ' + nome if nome else ''}."
        if complemento:
            frase += " " + complemento.strip()
        resumo = {"ok": not falhas, "itens": itens, "falhas": [f["modulo"] for f in falhas], "resumo": frase,
                  "quando": datetime.now().isoformat(timespec="seconds")}
        self.ultima = resumo
        app.barramento.publicar("inicializacao", fase="fim", indice=total, total=total, modulo="",
                                ok=not falhas, detalhe="SISTEMAS ONLINE", itens=itens, falhas=resumo["falhas"])
        if falar:
            app.fala.tocar_som(SOM_INICIALIZACAO)
            app.fala.falar(frase)
        return resumo


# -- modo jogo e overlay ------------------------------------------------------------------------------
class GerenteJogo:
    """Vigia os processos, liga/desliga o modo jogo e mantém o overlay com as métricas."""

    def __init__(self, app, sensores: Sensores, *, listar: Callable[[], list[dict]] = listar_processos,
                 janela: JanelaOverlay | None = None) -> None:
        self.app = app
        self.sensores = sensores
        self.listar = listar
        self.janela = janela or JanelaOverlay(app.cfg.dados)
        self.jogo: dict | None = None
        self.modo_aplicado = False
        self.overlay_aberto = False
        self.presentmon: LeitorPresentMon | None = None
        self._lento: dict[str, Any] = {}
        self._geracao = 0  # cada abertura do overlay tem os seus laços; os antigos param sozinhos
        self._lock = threading.Lock()
        self._parar = threading.Event()

    # -- detecção --------------------------------------------------------------------------------------
    def verificar(self) -> None:
        """Uma passada: confere se um jogo abriu ou fechou."""
        extras = list(self.app.prefs.get("jogos") or [])
        try:
            achado = procurar_jogo(self.listar(), extras)
        except Exception as erro:  # noqa: BLE001
            log.info("Não consegui listar os processos: %s", erro)
            return
        atual = self.jogo
        if achado and (atual is None or atual["pid"] != achado["pid"]):
            if atual is not None:
                self._jogo_fechou(atual, silencioso=True)
            self._jogo_abriu(achado)
        elif achado is None and atual is not None:
            self._jogo_fechou(atual)

    def _ctx(self):
        from ..cerebro.ferramentas import Contexto

        return Contexto(self.app, canal="voz", confiavel=True)

    def _jogo_abriu(self, jogo: dict) -> None:
        app = self.app
        self.jogo = {**jogo, "titulo": nome_amigavel(jogo.get("nome") or "")}
        log.info("Jogo aberto: %s (PID %s)", jogo.get("nome"), jogo.get("pid"))
        app.barramento.publicar("traje.jogo", ativo=True, jogo=self.jogo["titulo"])
        if app.prefs.get("modo_jogo_auto", True):
            ctx = self._ctx()
            app.registro.executar("configuracao", {"item": "plano_energia", "valor": "desempenho maximo"}, ctx)
            app.registro.executar("configuracao", {"item": "nao_perturbe", "valor": "ligar"}, ctx)
            self.modo_aplicado = True
            app.fala.falar(f"Modo jogo: {self.jogo['titulo']}. Desempenho máximo e não perturbe ligados.")
        if app.prefs.get("overlay_jogo", True):
            self.abrir_overlay()

    def _jogo_fechou(self, jogo: dict, silencioso: bool = False) -> None:
        app = self.app
        log.info("Jogo fechado: %s", jogo.get("nome"))
        self.jogo = None
        app.barramento.publicar("traje.jogo", ativo=False, jogo=jogo.get("titulo") or "")
        self.fechar_overlay()
        if self.modo_aplicado and not silencioso:
            self.restaurar()
            app.fala.falar("Jogo fechado. Voltei ao plano equilibrado e às notificações.")

    def restaurar(self) -> None:
        if not self.modo_aplicado:
            return
        ctx = self._ctx()
        self.app.registro.executar("configuracao", {"item": "plano_energia", "valor": "equilibrado"}, ctx)
        self.app.registro.executar("configuracao", {"item": "nao_perturbe", "valor": "desligar"}, ctx)
        self.modo_aplicado = False

    # -- overlay ---------------------------------------------------------------------------------------
    def url_overlay(self) -> str:
        return f"http://127.0.0.1:{self.app.cfg.porta}/overlay#t={self.app.acesso.token_pc}"

    def abrir_overlay(self) -> tuple[bool, str]:
        jogo = self.jogo
        ok, erro = self.janela.abrir(self.url_overlay(), jogo.get("nome") if jogo else None)
        if not ok:
            return False, erro
        with self._lock:
            self.overlay_aberto = True
            self._geracao += 1
            geracao = self._geracao
        self._iniciar_presentmon()
        threading.Thread(target=self._laco_metricas, args=(geracao,), name="traje-overlay", daemon=True).start()
        threading.Thread(target=self._laco_lento, args=(geracao,), name="traje-overlay-lento", daemon=True).start()
        return True, ""

    def fechar_overlay(self) -> bool:
        with self._lock:
            estava, self.overlay_aberto = self.overlay_aberto, False
        if self.presentmon is not None:
            self.presentmon.parar()
            self.presentmon = None
        self.janela.fechar()
        return estava

    def _iniciar_presentmon(self) -> None:
        if self.presentmon is not None:
            self.presentmon.parar()
            self.presentmon = None
        exe = caminho_presentmon(self.app.cfg.dados)
        if exe is None or self.jogo is None:
            return
        self.presentmon = LeitorPresentMon(exe)
        self.presentmon.iniciar(int(self.jogo["pid"]))

    def metricas(self) -> dict:
        try:
            uso = self.sensores.uso()
        except Exception:  # noqa: BLE001
            uso = {}
        leitor = self.presentmon
        if leitor is None:
            fps_dica = "instale o PresentMon" if caminho_presentmon(self.app.cfg.dados) is None else (
                "sem jogo" if self.jogo is None else "iniciando")
            fps = None
        else:
            fps = leitor.fps()
            fps_dica = leitor.erro or ("" if fps is not None else "medindo…")
        lento = dict(self._lento)
        return {"jogo": (self.jogo or {}).get("titulo", ""), "fps": fps, "fps_dica": fps_dica,
                "cpu": uso.get("cpu"), "ram": uso.get("ram"), "cpu_temp": lento.get("cpu_temp"),
                "gpu": lento.get("gpu"), "gpu_temp": lento.get("gpu_temp"), "ping": lento.get("ping")}

    def _vivo(self, geracao: int) -> bool:
        return self.overlay_aberto and geracao == self._geracao and not self._parar.is_set()

    def _laco_metricas(self, geracao: int) -> None:
        voltas = 0
        while self._vivo(geracao):
            self.app.barramento.publicar("traje.overlay", **self.metricas())
            voltas += 1
            if voltas % 5 == 0:  # alguns jogos "sem bordas" se põem por cima: reafirma o "sempre visível"
                self.janela.manter_no_topo()
            if self._parar.wait(1.0):
                return

    def _laco_lento(self, geracao: int) -> None:
        while self._vivo(geracao):
            try:
                temps = self.sensores.temperaturas(idade=4)
                gpu = self.sensores.gpu(idade=2)
                self._lento = {"cpu_temp": temps.get("cpu"), "gpu": gpu.get("uso"),
                               "gpu_temp": gpu.get("temp") if gpu.get("temp") is not None else temps.get("gpu"),
                               "ping": self.sensores.latencia(idade=2)}
            except Exception:  # noqa: BLE001
                log.exception("Erro lendo as métricas do overlay")
            if self._parar.wait(3.0):
                return

    def encerrar(self) -> None:
        self._parar.set()
        self.fechar_overlay()
        self.restaurar()


# -- serviço ------------------------------------------------------------------------------------------
class Traje:
    def __init__(self, app, sensores: Sensores | None = None) -> None:
        self.app = app
        self.sensores = sensores or Sensores(app.cfg.dados)
        self.inicializacao = Inicializacao(app)
        self.jogo = GerenteJogo(app, self.sensores)
        self.ultimo: dict | None = None
        self.alerta_cpu = AlertaSustentado()
        self.alerta_gpu = AlertaSustentado()
        self.chuva_avisada = False
        self.disco_avisado_em: date | None = None
        self._parar = threading.Event()
        self._threads: list[threading.Thread] = []

    # -- inicialização ---------------------------------------------------------------------------------
    def sequencia_inicial(self, complemento: str = "") -> dict:
        return self.inicializacao.executar(complemento)

    # -- relatório -------------------------------------------------------------------------------------
    def limites(self) -> tuple[float, float]:
        prefs = self.app.prefs
        return float(prefs.get("alerta_cpu_temp") or 95), float(prefs.get("alerta_gpu_temp") or 90)

    def seguranca(self) -> dict | None:
        servico = getattr(self.app, "seguranca", None)
        historico = getattr(servico, "historico", None)
        if historico is None:
            return None
        try:
            return resumo_seguranca(historico())
        except Exception:  # noqa: BLE001 - a extensão de segurança nunca derruba o relatório
            log.exception("Não consegui ler a revisão de segurança")
            return None

    def relatorio(self, timeout: float = 8.0) -> dict:
        r = montar_relatorio(self.sensores.coletar(timeout), self.seguranca(), self.limites())
        self.ultimo = r
        return r

    def dados_holograma(self) -> dict:
        if self.ultimo and time.time() - datetime.fromisoformat(self.ultimo["quando"]).timestamp() < 60:
            return self.ultimo
        return self.relatorio(timeout=6.0)

    # -- alertas ---------------------------------------------------------------------------------------
    def tratamento(self) -> str:
        return str(self.app.prefs.get("tratamento") or "chefe").strip().capitalize() or "Chefe"

    def alertar(self, texto: str, urgente: bool, etiqueta: str = "", lembrar: bool = False) -> None:
        from ..habilidades.notificacoes import notificar
        from ..voz.audio import SOM_ALERTA_TRAJE

        app = self.app

        def entregar() -> None:
            app.fala.tocar_som(SOM_ALERTA_TRAJE)
            app.fala.falar(texto)
            app.barramento.publicar("aviso", para="pc", nivel="erro" if urgente else "info", texto=texto)
            notificar(app, texto, titulo="Traje", prioridade="high" if urgente else "default")

        if lembrar:
            aprender = getattr(getattr(app, "memoria", None), "aprender", None)
            if aprender is not None:
                try:
                    aprender("fato", f"Alerta do traje em {datetime.now():%d/%m/%Y %H:%M}: {texto}",
                             ["traje", "alerta", etiqueta], origem="traje")
                except Exception:  # noqa: BLE001
                    log.debug("Memória indisponível para o alerta", exc_info=True)
        if not urgente:
            foco = getattr(app, "foco", None)
            if foco is not None and foco.segurar(entregar):
                return
        entregar()

    def _ativo(self, chave: str) -> bool:
        prefs = self.app.prefs
        return bool(prefs.get("alertas_proativos", True)) and bool(prefs.get(chave, True))

    def checar_temperaturas(self, agora: float | None = None) -> None:
        if not self._ativo("alerta_temperatura"):
            return
        agora = time.monotonic() if agora is None else agora
        temps = self.sensores.temperaturas(idade=10)
        gpu = self.sensores.gpu(idade=10)
        cpu_lim, gpu_lim = self.limites()
        gpu_temp = gpu.get("temp") if gpu.get("temp") is not None else temps.get("gpu")
        for nome, alerta, valor, limite in (("CPU", self.alerta_cpu, temps.get("cpu"), cpu_lim),
                                            ("GPU", self.alerta_gpu, gpu_temp, gpu_lim)):
            if alerta.atualizar(valor, limite, agora):
                minutos = alerta.minutos_acima(agora)
                texto = (f"{self.tratamento()}, a {nome} está a {round(valor)} graus há {minutos} "
                         f"minuto{'s' if minutos != 1 else ''}.")
                self.alertar(texto, urgente=True, etiqueta=nome.lower(), lembrar=True)

    def checar_chuva(self) -> None:
        from ..habilidades.clima import ErroClima, minutos_ate_chuva

        if not self._ativo("alerta_chuva"):
            return
        prefs = self.app.prefs
        lat, lon = prefs.get("cidade_lat"), prefs.get("cidade_lon")
        if lat is None or lon is None:
            return
        try:
            dados = self.app.clima.precipitacao_curta(float(lat), float(lon))
        except (ErroClima, ValueError, KeyError) as erro:
            log.info("Previsão de chuva indisponível: %s", erro)
            return
        minutos = minutos_ate_chuva(dados, CHUVA_MINIMA_MM, 60)
        chovendo = (dados.get("agora") or {}).get("mm", 0) >= CHUVA_MINIMA_MM
        if minutos is not None and not self.chuva_avisada:
            self.chuva_avisada = True
            self.alertar(frase_chuva(minutos, self.tratamento()), urgente=False, etiqueta="chuva")
        elif minutos is None and not chovendo and not any(p["mm"] >= CHUVA_MINIMA_MM for p in dados.get("passos") or []):
            self.chuva_avisada = False  # a chuva passou (ou não veio): o próximo evento avisa de novo

    def checar_disco(self, hoje: date | None = None) -> None:
        if not self._ativo("alerta_disco"):
            return
        hoje = hoje or date.today()
        if self.disco_avisado_em == hoje:
            return
        sistema = next((u for u in self.sensores.espaco() if u.get("sistema")), None)
        if sistema is None:
            return
        livre = 100 - sistema["pct"]
        if livre < DISCO_MINIMO_PCT:
            self.disco_avisado_em = hoje
            texto = (f"{self.tratamento()}, o disco {sistema['unidade'].rstrip(':')} está com só {livre}% livre, "
                     f"{sistema['livre_gb']} gigas.")
            self.alertar(texto, urgente=False, etiqueta="disco", lembrar=True)

    def _laco(self, intervalo: float, funcao: Callable[[], None], espera_inicial: float = 0.0) -> None:
        if self._parar.wait(espera_inicial):
            return
        while not self._parar.is_set():
            try:
                funcao()
            except Exception:  # noqa: BLE001 - a thread não pode morrer
                log.exception("Erro no traje (%s)", getattr(funcao, "__name__", "?"))
            if self._parar.wait(intervalo):
                return

    def iniciar(self) -> None:
        if self._threads:
            return
        laços = [("traje-temperatura", CHECAR_TEMPERATURA_S, self.checar_temperaturas, 60),
                 ("traje-chuva", CHECAR_CHUVA_S, self.checar_chuva, 90),
                 ("traje-disco", CHECAR_DISCO_S, self.checar_disco, 120),
                 ("traje-jogo", CHECAR_JOGO_S, self.jogo.verificar, 15),
                 ("traje-aquecer", 24 * 3600, self.sensores.aquecer, 45)]
        from ..habilidades import windows

        for nome, intervalo, funcao, espera in laços:
            if not windows.WINDOWS and nome in ("traje-temperatura", "traje-jogo", "traje-aquecer"):
                continue  # sem Windows não há o que medir nem jogo para vigiar
            t = threading.Thread(target=self._laco, args=(intervalo, funcao, espera), name=nome, daemon=True)
            t.start()
            self._threads.append(t)

    def encerrar(self) -> None:
        self._parar.set()
        self.jogo.encerrar()

    def estado(self) -> dict:
        from ..habilidades import windows

        temps = self.sensores.ultimo("temperaturas") or {}
        return {"windows": windows.WINDOWS, "presentmon": str(caminho_presentmon(self.app.cfg.dados) or ""),
                "nvidia_smi": bool(self.sensores._nvidia), "edge": bool(caminho_edge()) if windows.WINDOWS else False,
                "temperatura_fonte": temps.get("fonte", ""), "temperatura_erro": temps.get("erro", ""),
                "jogo": (self.jogo.jogo or {}).get("titulo", ""), "overlay": self.jogo.overlay_aberto}


# -- ganchos ------------------------------------------------------------------------------------------
def instalar(app) -> None:
    app.traje = Traje(app)


def registrar(app, registro) -> None:
    traje: Traje = app.traje

    @registro.ferramenta(
        "traje",
        "Diagnóstico e recursos do traje (o PC). relatorio: temperaturas de CPU/GPU, uso da placa de vídeo, discos, "
        "rede, atualizações pendentes, bateria e segurança, num holograma. ligar_overlay/desligar_overlay: o painel de "
        "FPS e temperaturas por cima do jogo. ligar_modo_jogo_auto/desligar_modo_jogo_auto: desempenho máximo e não "
        "perturbe automáticos quando um jogo abre. inicializacao: repete a sequência 'sistemas online'.",
        direta=True,
        acao=P("string", "Ação.", enum=["relatorio", "ligar_overlay", "desligar_overlay", "ligar_modo_jogo_auto",
                                        "desligar_modo_jogo_auto", "inicializacao"], obrigatorio=True),
    )
    def ferramenta_traje(ctx, acao: str):
        if acao == "relatorio":
            app.hologramas.mostrar("traje", {"carregando": True}, titulo="Diagnóstico do traje")
            r = traje.relatorio()
            app.hologramas.mostrar("traje", r, titulo="Diagnóstico do traje")
            return {"ok": True, "resumo": resumo_falado(r)}
        if acao == "ligar_overlay":
            app.prefs.atualizar({"overlay_jogo": True})
            app.barramento.publicar("preferencias", preferencias=app.prefs.tudo())
            ok, erro = traje.jogo.abrir_overlay()
            if not ok:
                return {"ok": False, "resumo": erro}
            return {"ok": True, "resumo": "Overlay ligado." + ("" if traje.jogo.jogo else " Ele também abre sozinho com os jogos.")}
        if acao == "desligar_overlay":
            app.prefs.atualizar({"overlay_jogo": False})
            app.barramento.publicar("preferencias", preferencias=app.prefs.tudo())
            traje.jogo.fechar_overlay()
            return {"ok": True, "resumo": "Overlay desligado. Não abro mais com os jogos até você pedir."}
        if acao in ("ligar_modo_jogo_auto", "desligar_modo_jogo_auto"):
            ligar = acao.startswith("ligar")
            app.prefs.atualizar({"modo_jogo_auto": ligar})
            app.barramento.publicar("preferencias", preferencias=app.prefs.tudo())
            if not ligar:
                traje.jogo.restaurar()
            return {"ok": True, "resumo": "Modo jogo automático ligado: quando um jogo abrir, ponho desempenho máximo e "
                                          "não perturbe." if ligar else "Modo jogo automático desligado."}
        threading.Thread(target=traje.inicializacao.executar, kwargs={"esperar_hud": 0}, daemon=True).start()
        return {"ok": True, "resumo": ""}


_VERBO_LIGAR = r"(?:liga|ligar|ligue|ativa|ativar|ative|abre|abrir|abra|mostra|mostrar|mostre)"
_VERBO_DESLIGAR = r"(?:desliga|desligar|desligue|desativa|desativar|desative|fecha|fechar|feche|esconde|esconder|tira|tirar)"
_RELATORIO = (
    re.compile(r"^(?:(?:me )?(?:mostra|mostre|da|de|faz|faca|abre|roda|rode) (?:o |um )?)?"
               r"(?:status|relatorio|diagnostico|estado|situacao|checagem) do traje$"),
    re.compile(r"^como (?:esta|ta|anda|vai) o traje$"),
)
_OVERLAY = re.compile(rf"^(?P<verbo>{_VERBO_LIGAR}|{_VERBO_DESLIGAR}) (?:o )?overlay(?: d[eo] jogo| dos jogos)?$")
_MODO_AUTO = re.compile(rf"^(?P<verbo>{_VERBO_LIGAR}|{_VERBO_DESLIGAR}) (?:o )?modo (?:de )?jogo automatico$")
_INICIALIZACAO = re.compile(r"^(?:(?:roda|rode|mostra|mostre|faz|faca|repete|repita) (?:a )?)?sequencia de inicializacao$")


def atalho(t: str, ctx, rodar, original: str | None) -> Callable[[], str] | None:
    if any(p.match(t) for p in _RELATORIO):
        return rodar("traje", {"acao": "relatorio"})
    if m := _OVERLAY.match(t):
        ligar = re.match(_VERBO_LIGAR + "$", m.group("verbo")) is not None
        return rodar("traje", {"acao": "ligar_overlay" if ligar else "desligar_overlay"})
    if m := _MODO_AUTO.match(t):
        ligar = re.match(_VERBO_LIGAR + "$", m.group("verbo")) is not None
        return rodar("traje", {"acao": "ligar_modo_jogo_auto" if ligar else "desligar_modo_jogo_auto"})
    if _INICIALIZACAO.match(t):
        return rodar("traje", {"acao": "inicializacao"})
    return None


def dados_holograma(app, tipo: str) -> dict | None:
    return app.traje.dados_holograma() if tipo == "traje" else None


def rotas(api, app, autenticado, so_pc) -> None:
    import asyncio

    from fastapi import Depends

    @api.get("/api/traje/estado")
    async def estado_traje(_=Depends(autenticado)):
        return await asyncio.to_thread(app.traje.estado)

    @api.get("/api/traje/overlay")
    async def metricas_overlay(_=Depends(autenticado)):
        """Primeiro quadro do overlay (depois, só o evento "traje.overlay")."""
        return await asyncio.to_thread(app.traje.jogo.metricas)


async def mensagem_ws(app, cliente, registrado, mensagem, websocket) -> bool:
    """O overlay manda "traje.overlay.fechar" no botão de fechar."""
    if mensagem.get("tipo") != "traje.overlay.fechar":
        return False
    app.traje.jogo.fechar_overlay()
    return True


def diagnostico(app) -> list[dict]:
    from ..habilidades import windows

    if not windows.WINDOWS:
        return [{"nome": "Traje (sensores)", "ok": False, "detalhe": "só no Windows", "dica": ""}]
    traje: Traje = app.traje
    temps = traje.sensores.temperaturas(idade=60)
    itens = [{"nome": "Temperatura da CPU", "ok": temps.get("cpu") is not None,
              "detalhe": f"{temps['cpu']:.0f} °C ({temps['fonte']})" if temps.get("cpu") is not None else DICA_LHM,
              "dica": "" if temps.get("cpu") is not None else
              "Baixe o LibreHardwareMonitor, abra como administrador e deixe aberto (Options > Run On Windows Startup)"}]
    presentmon = caminho_presentmon(app.cfg.dados)
    itens.append({"nome": "FPS do overlay (PresentMon)", "ok": presentmon is not None,
                  "detalhe": str(presentmon) if presentmon else "não instalado",
                  "dica": "" if presentmon else "Baixe o PresentMon (github.com/GameTechDev/PresentMon/releases) "
                                                "para dados/ferramentas/ ou defina PRESENTMON no .env"})
    itens.append({"nome": "Overlay de jogo (Edge)", "ok": caminho_edge() is not None,
                  "detalhe": "Microsoft Edge encontrado" if caminho_edge() else "Edge não encontrado",
                  "dica": "" if caminho_edge() else "Instale o Microsoft Edge"})
    return itens


def iniciar(app) -> None:
    app.traje.iniciar()


def encerrar(app) -> None:
    app.traje.encerrar()
