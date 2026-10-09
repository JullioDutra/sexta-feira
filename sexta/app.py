"""Monta e liga todas as peças da Sexta-Feira."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from . import __version__
from .atividades import Atividades
from .cerebro.agente import Agente
from .cerebro.ferramentas import Contexto, Registro
from .cerebro.memoria import Memoria
from .config import Config, Preferencias
from .estado import Estado
from .eventos import Barramento
from .habilidades import registrar_ferramentas, windows
from .habilidades.apps import CatalogoApps
from .habilidades.agenda import Agenda
from .habilidades.arquivos import Arquivos
from .habilidades.foco import ModoFoco
from .habilidades.gatilhos import Vigia
from .habilidades.clima import ServicoClima
from .habilidades.hologramas import Hologramas
from .habilidades.janelas import Layouts
from .habilidades.jornal import Jornal
from .habilidades.lembretes import Lembretes
from .habilidades.noticias import ServicoNoticias
from .habilidades.rotinas import Rotinas
from .habilidades.tarefas import Tarefas
from .habilidades.terminal import Terminal
from .seguranca import Acesso, Sessao
from .util.tempo import data_extenso, saudacao
from .visao.camera import Camera
from .visao.maos import Maos
from .visao.rosto import Rosto
from .voz.assistente_voz import AssistenteVoz
from .voz.audio import SOM_DESBLOQUEIO
from .voz.fala import Fala
from .voz.transcricao import Transcritor

log = logging.getLogger("sexta")

BRIEFING_SISTEMA = """Você é a Sexta-Feira, assistente pessoal. Escreva o briefing matinal que será FALADO em voz alta, \
em português do Brasil, a partir dos dados em JSON. Regras: no máximo 230 palavras (cerca de 2 minutos); comece com a \
saudação e a data; depois o clima em uma frase; a agenda do dia (se vazia, diga que está livre) e as tarefas para hoje; as principais notícias do \
Brasil e de tecnologia, cada uma em uma frase curta e clara, juntando as que falam do mesmo assunto; e os temas que o \
usuário acompanha, se houver. Tom confiante e leve. Sem markdown, listas, emojis nem links. Termine com uma frase curta."""


def briefing_simples(dados: dict) -> str:
    partes = [f"{dados['saudacao']}. Hoje é {dados['data']}."]
    if dados.get("clima"):
        partes.append(dados["clima"])
    partes.append(f"Na agenda: {'; '.join(dados['agenda'])}." if dados.get("agenda") else "Sua agenda de hoje está livre.")
    if dados.get("tarefas_para_hoje"):
        partes.append("Para hoje: " + "; ".join(dados["tarefas_para_hoje"]) + ".")
    if dados.get("brasil"):
        partes.append("No Brasil: " + "; ".join(dados["brasil"][:5]) + ".")
    if dados.get("tecnologia"):
        partes.append("Em tecnologia: " + "; ".join(dados["tecnologia"][:5]) + ".")
    if dados.get("temas"):
        partes.append("Dos seus temas: " + "; ".join(dados["temas"][:3]) + ".")
    return " ".join(partes)


class SextaFeira:
    def __init__(self, cfg: Config, *, com_voz: bool = True) -> None:
        self.cfg = cfg
        self.com_voz = com_voz
        self.versao = __version__
        self.barramento = Barramento()
        self.prefs = Preferencias(cfg.dados / "preferencias.json")
        self.estado = Estado(self.barramento)
        self.acesso = Acesso(cfg.dados / "acesso.json")
        self.memoria = Memoria(cfg.dados / "memoria.json")

        self.camera = Camera(self)
        self.rosto = Rosto(self)
        self.maos = Maos(self)
        self.sessao = Sessao(self.prefs, self.barramento, lambda: self.rosto.cadastrado())

        self.fala = Fala(self)
        self.transcritor = Transcritor(cfg.whisper_modelo, cfg.whisper_dispositivo, cfg.modelos / "whisper")
        self.voz = AssistenteVoz(self)

        self.clima = ServicoClima()
        self.noticias = ServicoNoticias()
        self.jornal = Jornal(self, cfg.pasta_config / "noticias.yaml", cfg.dados)
        self.apps = CatalogoApps(cfg.pasta_config / "apps.yaml")
        self.hologramas = Hologramas(self)
        self.lembretes = Lembretes(self, cfg.dados / "sexta.db")
        self.tarefas = Tarefas(self, cfg.dados / "sexta.db")
        self.agenda = Agenda(self, cfg.agenda_ics)
        self.foco = ModoFoco(self)
        self.rotinas = Rotinas(self, cfg.pasta_config / "rotinas.yaml", cfg.pasta_config / "rotinas_criadas.yaml")
        self.arquivos = Arquivos(cfg.pastas_arquivos)
        self.layouts = Layouts(self, cfg.pasta_config / "layouts.yaml", cfg.pasta_config / "layouts_criados.yaml")
        self.terminal = Terminal(cfg.pasta_config / "terminal.yaml")
        self.atividades = Atividades(self, cfg.dados / "atividades.jsonl")
        self.vigia = Vigia(self)

        self.registro = Registro()
        self.registro.ao_executar = self.atividades.anotar
        registrar_ferramentas(self, self.registro)
        self.agente = Agente(self)

        self._rodando = False
        self._verificando = threading.Lock()
        self.servidores: list = []
        self.endereco_hud = f"http://127.0.0.1:{cfg.porta}/#t={self.acesso.token_pc}"

    # ------------------------------------------------------------------ utilidades
    def contexto(self, canal: str = "voz", cliente=None) -> Contexto:
        return Contexto(self, canal=canal, cliente=cliente)

    def pasta_prints(self) -> Path:
        try:
            return windows.pasta_conhecida("imagens") / "Sexta-Feira"
        except Exception:  # noqa: BLE001
            return self.cfg.dados / "prints"

    def definir_cidade(self, local: dict) -> None:
        self.prefs.atualizar({"cidade": local.get("nome") or local.get("rotulo"), "cidade_lat": local["lat"],
                              "cidade_lon": local["lon"], "cidade_fuso": local.get("fuso"),
                              "cidade_rotulo": local.get("rotulo")}, interno=True)
        self.barramento.publicar("preferencias", preferencias=self.prefs.tudo())

    def maos_para_hud(self, ligar: bool) -> None:
        """Liga/desliga o controle por gestos e avisa o HUD do PC."""
        if ligar:
            self.maos.ligar()
        else:
            self.maos.desligar()
        self.barramento.publicar("maos.modo", ligado=ligar, para="pc")

    def briefing(self, ctx: Contexto | None = None) -> str:
        """Briefing matinal falado (até ~2 min): clima, agenda do dia e 5 + 5 manchetes."""
        ctx = ctx or self.contexto()
        agora = datetime.now()
        nome = self.prefs.get("nome") or self.prefs.get("tratamento") or "chefe"
        clima = self.registro.executar("obter_clima", {}, ctx)
        hoje = self.lembretes.do_dia(agora)
        agenda = [f"{l['texto']} às {l['hora']}" for l in hoje if datetime.fromisoformat(l["quando"]) >= agora]
        try:
            agenda = [self.agenda.descrever(e) for e in self.agenda.do_dia(agora.date()) if e["fim"] >= agora] + agenda
        except Exception:  # noqa: BLE001
            log.exception("Agenda indisponível no briefing")
        agenda = agenda[:6]
        tarefas = [f"{t['titulo']} ({t['prazo_texto']})" for t in self.tarefas.pendentes()
                   if t["atrasada"] or t["prazo"] == agora.date().isoformat()][:4]
        try:
            noticias = self.jornal.dados_briefing()
            self.hologramas.mostrar("jornal", self.jornal.dados_holograma("destaques"), titulo="Jornal")
        except Exception:  # noqa: BLE001 - sem notícias o briefing segue com o resto
            log.exception("Notícias do briefing indisponíveis")
            noticias = {"brasil": [], "tecnologia": [], "temas": []}
        dados = {
            "saudacao": f"{saudacao(agora)}, {nome}", "data": data_extenso(agora),
            "clima": clima["resumo"] if clima.get("ok") else "",
            "agenda": agenda, "tarefas_para_hoje": tarefas, **noticias,
        }
        try:
            texto = self.agente.completar(BRIEFING_SISTEMA, json.dumps(dados, ensure_ascii=False))
        except Exception as erro:  # noqa: BLE001 - sem IA: roteiro pronto
            log.info("Briefing sem IA (%s)", erro)
            texto = ""
        return texto or briefing_simples(dados)

    # ------------------------------------------------------------------ identidade
    def garantir_identidade(self, canal: str) -> bool:
        """Antes de obedecer a voz: confere o rosto se a proteção estiver ligada."""
        if canal != "voz" or not self.sessao.precisa_verificar():
            return True
        if self.sessao.bloqueada:
            return self.desbloquear_por_rosto()
        self.estado.definir("verificando")
        resultado = self.rosto.verificar(timeout=5.0, exigir_piscada=False, progresso=self._progresso_verificacao)
        if resultado.ok:
            self.sessao.registrar_verificacao()
            return True
        self.fala.falar("Não consegui ver seu rosto. Olhe para a câmera e tente de novo." if resultado.motivo == "sem_rosto"
                        else "Não reconheci você.")
        return False

    def verificar_para_acao(self, ctx: Contexto) -> tuple[bool, str]:
        """Nível 3 de segurança: depois do "sim", confere o rosto antes de apagar, desligar ou rodar comando."""
        if ctx.canal != "voz":
            # celular pareado e HUD local já passaram pela chave de acesso (e pelo PIN, se houver bloqueio)
            return True, ""
        if not self.rosto.cadastrado() or not self.rosto.modelos_presentes():
            log.warning("Ação de nível 3 confirmada só por voz: rosto não cadastrado")
            return True, ""
        self.estado.definir("verificando")
        try:
            resultado = self.rosto.verificar(timeout=6.0, exigir_piscada=False, progresso=self._progresso_verificacao)
        finally:
            self.estado.definir("pensando")
        if resultado.ok:
            self.sessao.registrar_verificacao()
            return True, ""
        if resultado.motivo == "sem_rosto":
            return False, "Não consegui ver seu rosto, então não fiz. Olhe para a câmera e peça de novo."
        return False, "Não reconheci você, então não fiz."

    def desbloquear_por_rosto(self, automatico: bool = False) -> bool:
        if not self.sessao.bloqueada:
            return True
        if not self._verificando.acquire(blocking=False):
            return False
        try:
            self.estado.definir("verificando")
            self.barramento.publicar("verificacao", fase="inicio", automatico=automatico)
            resultado = self.rosto.verificar(
                timeout=25.0 if automatico else 12.0,
                exigir_piscada=bool(self.prefs.get("exigir_piscada")),
                progresso=self._progresso_verificacao,
            )
            self.barramento.publicar("verificacao", fase="ok" if resultado.ok else "falhou", motivo=resultado.motivo)
            if resultado.ok:
                self.sessao.desbloquear("rosto")
                nome = self.prefs.get("nome") or self.prefs.get("tratamento") or "chefe"
                self.fala.tocar_som(SOM_DESBLOQUEIO)
                self.fala.falar(f"Identidade confirmada. {saudacao()}, {nome}.")
                return True
            if not automatico and resultado.motivo != "cancelado":
                mensagens = {"sem_piscada": "Reconheci você, mas preciso que pisque para confirmar.",
                             "sem_rosto": "Não consegui ver seu rosto.", "erro": "Tive um problema com a câmera ou o reconhecimento facial. Use o PIN por enquanto."}
                self.fala.falar(mensagens.get(resultado.motivo, "Não reconheci você."))
            return False
        finally:
            self._verificando.release()
            if self.estado.atual == "verificando":
                self.estado.definir("inativa")

    def _progresso_verificacao(self, fase: str, similaridade: float) -> None:
        self.barramento.publicar("verificacao", fase=fase, similaridade=round(similaridade, 3))

    def desbloquear_por_pin(self, pin: str) -> bool:
        if self.acesso.verificar_pin(pin):
            self.sessao.desbloquear("pin")
            return True
        return False

    # ------------------------------------------------------------------ ciclo de vida
    def executar(self) -> None:
        from .servidor import outra_sexta_aberta, porta_ocupada, servir

        if porta_ocupada(self.cfg.porta):
            if outra_sexta_aberta(self.cfg.porta):
                log.info("A Sexta-Feira já está aberta; abrindo o HUD dela.")
                self.abrir_hud()
                raise SystemExit(0)
            log.error("A porta %s está ocupada por outro programa. Troque PORTA no arquivo .env.", self.cfg.porta)
            raise SystemExit(1)
        self._rodando = True
        threading.Thread(target=self._inicializar_servicos, name="inicializacao", daemon=True).start()
        try:
            asyncio.run(servir(self))
        except KeyboardInterrupt:
            pass
        finally:
            self.encerrar()

    def _inicializar_servicos(self) -> None:
        time.sleep(0.8)  # deixa o servidor subir primeiro
        if self.sessao.protecao_ativa():
            self.sessao.bloquear("inicio")
        ok, mensagem = self.agente.ollama.verificar()
        self.estado.aviso("ollama", None if ok else mensagem)
        log.info(mensagem)
        if ok:
            threading.Thread(target=self._aquecer_cerebro, name="aquecer-ia", daemon=True).start()
        self.arquivos.iniciar()
        if self.cfg.abrir_hud:
            self.abrir_hud()
        if self.com_voz:
            self.voz.iniciar()
            threading.Thread(target=self._carregar_whisper, daemon=True).start()
        self.lembretes.iniciar()
        self.rotinas.iniciar(lambda: self.contexto("voz"))
        self.vigia.iniciar()
        self.jornal.iniciar()
        self.agenda.iniciar()
        threading.Thread(target=self._vigiar_windows, name="vigia-windows", daemon=True).start()
        threading.Thread(target=self.apps.menu_iniciar, daemon=True).start()
        if windows.WINDOWS:
            from .bandeja import iniciar_bandeja

            iniciar_bandeja(self)
        self.estado.definir("inativa")
        if self.prefs.get("saudacao_ao_iniciar") and self.com_voz:
            nome = self.prefs.get("nome")
            frase = f"Sexta-Feira online. {saudacao()}{', ' + nome if nome else ''}."
            agora = datetime.now()
            if agora.weekday() == 4 and agora.hour >= 16:
                frase += " E hoje é sexta-feira: sextou!"
            if self.sessao.bloqueada:
                frase += " Olhe para a câmera para eu confirmar que é você."
            self.fala.falar(frase)
        if self.sessao.bloqueada:
            self.fala.aguardar(10)
            self.desbloquear_por_rosto(automatico=True)

    def _aquecer_cerebro(self) -> None:
        self.agente.aquecer()
        verificar_memoria = getattr(self.agente.ollama, "uso_de_memoria", None)
        if verificar_memoria:  # Ollama: avisa se o modelo não coube na placa de vídeo
            aviso = verificar_memoria()
            if aviso:
                log.warning(aviso)
                self.estado.aviso("ollama_memoria", aviso)

    def _carregar_whisper(self) -> None:
        try:
            self.transcritor.carregar()
            self.estado.aviso("whisper", None)
        except Exception as erro:  # noqa: BLE001
            log.error("Whisper indisponível: %s", erro)
            self.estado.aviso("whisper", f"Transcrição de voz indisponível: {erro}")

    def abrir_hud(self) -> None:
        url = self.endereco_hud
        if self.cfg.navegador == "edge" and windows.WINDOWS:
            try:
                import subprocess

                subprocess.Popen(["cmd", "/c", "start", "", "msedge", f"--app={url}", "--start-maximized"],
                                 creationflags=windows.SEM_JANELA)
                return
            except OSError:
                pass
        webbrowser.open(url)

    def _vigiar_windows(self) -> None:
        anterior = windows.sessao_bloqueada()
        if anterior is None:
            return
        mudancas = 0
        bloqueado_em = time.monotonic() if anterior else 0.0
        while self._rodando:
            time.sleep(1.0)
            atual = windows.sessao_bloqueada()
            mudancas = mudancas + 1 if atual != anterior else 0
            if mudancas < 2:  # ignora piscadas (ex.: janela do UAC)
                continue
            anterior, mudancas = atual, 0
            if atual:
                log.info("Windows bloqueado")
                bloqueado_em = time.monotonic()
                self.fala.parar()
                self.maos_para_hud(False)
                self.sessao.bloquear("windows")
            else:
                log.info("Windows desbloqueado")
                self.rotinas.disparar("desbloquear")
                if self.sessao.bloqueada:
                    threading.Thread(target=self.desbloquear_por_rosto, kwargs={"automatico": True}, daemon=True).start()
                elif time.monotonic() - bloqueado_em > 60:  # só cumprimenta depois de uma ausência de verdade
                    nome = self.prefs.get("nome") or self.prefs.get("tratamento") or "chefe"
                    self.fala.falar(f"Bem-vindo de volta, {nome}.")

    def sair(self) -> None:
        """Pede para os servidores pararem (o resto encerra em seguida)."""
        for servidor in self.servidores:
            servidor.should_exit = True

    def encerrar(self) -> None:
        if not self._rodando:
            return
        self._rodando = False
        log.info("Encerrando a Sexta-Feira")
        for parar in (self.voz.parar, self.lembretes.parar, self.vigia.parar, self.rotinas.parar, self.jornal.parar, self.agenda.parar, lambda: self.foco.encerrar(silencioso=True), self.maos.desligar,
                      self.fala.encerrar):
            try:
                parar()
            except Exception:  # noqa: BLE001
                pass