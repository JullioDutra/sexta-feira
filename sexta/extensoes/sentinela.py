"""Protocolo Sentinela, Casa Limpa e "Onde eu parei?".

Sentinela: "ativa o protocolo sentinela" (ou sozinho, quando você sai do PC e a preferência ``sentinela_auto``
está ligada) bloqueia o Windows e a Sexta-Feira e passa a vigiar pela webcam: a cada ~8 s a câmera liga,
procura rostos e desliga — por isso **a luz da câmera pisca enquanto o Sentinela está armado**. Mexer no
teclado/mouse faz a checagem na hora. Um rosto que não é o seu (2 quadros seguidos), ou alguém mexendo no PC
sem o seu rosto na frente, vira foto em ``dados/sentinela/`` (só no computador, nunca sai dele), entrada no
registro de atividades, na memória e no histórico de segurança, e um aviso no celular — sem falar nada.
No máximo um alerta a cada 2 minutos. Quando o seu rosto aparece, o Sentinela desarma e cumprimenta baixinho;
"desativa o sentinela" pede o seu rosto.

Casa Limpa: "protocolo casa limpa" fecha as janelas dos programas (WM_CLOSE: cada um pode pedir para salvar),
organiza Downloads e apaga temporários com mais de 24 h — sempre depois do seu "sim".

Onde eu parei: a cada 5 minutos de uso (e quando o Windows bloqueia) a Sexta-Feira anota os programas abertos,
os arquivos usados e as páginas visitadas na sessão; "onde eu parei?" mostra a sessão anterior e reabre o que
você escolher.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import uuid
import webbrowser
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from ..cerebro.ferramentas import CONFIRMAR, LIVRE, ROSTO, P
from ..habilidades import windows
from ..util.texto import normalizar

log = logging.getLogger(__name__)

PREFERENCIAS = {"sentinela_auto": False, "sentinela_minutos": 5}
HOLOGRAMAS = {"sentinela": "Protocolo Sentinela", "retomar": "Onde você parou"}

# -- Sentinela ------------------------------------------------------------------------------------
INTERVALO_S = 8.0             # entre uma olhada e outra da câmera (a luz pisca nesse ritmo)
CARENCIA_S = 15.0             # logo depois de armar, mexer no PC ainda é o próprio usuário saindo
ALERTA_INTERVALO_S = 120.0    # no máximo uma foto + aviso a cada 2 minutos
AUTO_CHECAR_S = 30.0          # com o modo automático, olha se você saiu a cada 30 s
PAUSA_PRESENTE_S = 5 * 60     # viu você parado na frente do PC: só olha de novo em 5 min (ou se mexer)
ATIVIDADE_S = 2.0             # ocioso abaixo disso = alguém acabou de mexer
QUADROS_CHECAGEM = 3
QUADROS_ATIVIDADE = 6
ESPACO_QUADROS_S = 0.4
_NOME_FOTO = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:_\d{1,2})?\.jpg$")

# -- Casa Limpa -------------------------------------------------------------------------------------
IDADE_TEMPORARIO_S = 24 * 3600
NAO_FECHAR_EXE = {"explorer", "sexta", "sexta-feira", "taskmgr", "lockapp", "searchapp", "shellhost",
                  "systemsettings", "textinputhost"}
ATRIBUTO_REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: links simbólicos e junções

# -- Onde eu parei ------------------------------------------------------------------------------------
INSTANTANEO_S = 5 * 60
VIGIA_SESSAO_S = 10.0
NOVA_SESSAO_S = 30 * 60
MAX_SESSOES = 10
ABAS_JANELA_S = 2 * 3600
MAX_ABAS = 8
MAX_ARQUIVOS = 12
MAX_APPS = 12
SESSAO_NOVA_S = 20 * 60       # "onde eu parei" logo depois de voltar mostra a sessão anterior
EPOCA_CHROME_S = 11_644_473_600  # segundos entre 1601-01-01 e 1970-01-01
NOMES_APPS = {"code": "VS Code", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "brave": "Brave",
              "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint", "outlook": "Outlook",
              "notepad": "Bloco de Notas", "notepad++": "Notepad++", "spotify": "Spotify", "discord": "Discord",
              "whatsapp": "WhatsApp", "telegram": "Telegram", "obs64": "OBS", "figma": "Figma", "notion": "Notion",
              "acrobat": "Acrobat", "acrord32": "Acrobat", "windowsterminal": "Terminal", "devenv": "Visual Studio",
              "pycharm64": "PyCharm", "idea64": "IntelliJ", "slack": "Slack", "ms-teams": "Teams", "teams": "Teams",
              "zoom": "Zoom", "vlc": "VLC", "photoshop": "Photoshop", "steam": "Steam", "opera": "Opera"}
NAVEGADORES = {"chrome", "msedge", "firefox", "brave", "opera", "vivaldi"}
APPS_SISTEMA = {"explorer", "applicationframehost", "systemsettings", "taskmgr", "lockapp", "searchapp", "searchhost",
                "shellexperiencehost", "startmenuexperiencehost", "textinputhost", "python", "pythonw", "conhost",
                "ollama", "ollama app"}
_RUIDO_URL = re.compile(
    r"(?:^|\.)(?:google\.[a-z.]+/(?:search|url|sorry)|bing\.com/(?:search|ck/)|duckduckgo\.com/(?:\?|html|l/)|"
    r"search\.yahoo\.com|yandex\.[a-z]+/search|accounts\.google\.com|login\.microsoftonline\.com|"
    r"login\.live\.com|consent\.(?:google|youtube)\.com|appleid\.apple\.com|auth\.|sso\.|oauth|/login|/logout|"
    r"/signin|/sign-in|/signup|/auth/|/authorize|/callback|redirect|/url\?|/l\.php|t\.co/|lnkd\.in/|"
    r"localhost|127\.0\.0\.1|newtab|chrome-search)", re.IGNORECASE)


# ================================================================================================
# Sentinela
# ================================================================================================

def _agora_texto(quando: datetime | None = None) -> str:
    return (quando or datetime.now()).strftime("%H:%M")


def nome_foto_valido(nome: str) -> bool:
    """Só nomes gerados pelo Sentinela (sem barras, sem "..", sem outras extensões)."""
    return bool(nome) and len(nome) < 40 and _NOME_FOTO.fullmatch(nome) is not None


class Sentinela:
    def __init__(self, app, pasta: Path) -> None:
        self.app = app
        self.pasta = pasta
        self.armado = False
        self.desde: float | None = None
        self.motivo = ""
        self.alertas = 0                       # alertas desde que armou
        self._ultimo_alerta = 0.0
        self._dono_seguidos = 0
        self._estranho_seguidos = 0
        self._ausente_seguidos = 0
        self._pausa_ate = 0.0
        self._lock = threading.RLock()
        self._parar = threading.Event()
        self._acordar = threading.Event()
        self._thread: threading.Thread | None = None
        self._sem_visao_avisado = False
        # dá para trocar nos testes
        self.ocioso = _segundos_ocioso
        self.bloqueado = windows.sessao_bloqueada

    # -- estado --------------------------------------------------------------------------------
    def cadastrado(self) -> bool:
        try:
            return bool(self.app.rosto.cadastrado())
        except Exception:  # noqa: BLE001
            return False

    def fotos(self) -> list[dict]:
        try:
            arquivos = [f for f in self.pasta.iterdir() if f.is_file() and nome_foto_valido(f.name)]
        except OSError:
            return []
        saida = []
        for f in sorted(arquivos, key=lambda f: f.name, reverse=True):
            try:
                quando = datetime.strptime(f.name[:19], "%Y-%m-%d_%H-%M-%S")
            except ValueError:
                continue
            saida.append({"nome": f.name, "quando": quando.isoformat(timespec="seconds"),
                          "tamanho": f.stat().st_size})
        return saida

    def caminho_foto(self, nome: str) -> Path | None:
        if not nome_foto_valido(nome):
            return None
        caminho = self.pasta / nome
        return caminho if caminho.is_file() else None

    def apagar_foto(self, nome: str) -> bool:
        caminho = self.caminho_foto(nome)
        if caminho is None:
            return False
        caminho.unlink(missing_ok=True)
        self._publicar()
        return True

    def estado(self) -> dict:
        return {"armado": self.armado, "desde": datetime.fromtimestamp(self.desde).isoformat(timespec="seconds")
                if self.desde else None, "motivo": self.motivo, "alertas": self.alertas,
                "auto": bool(self.app.prefs.get("sentinela_auto")),
                "minutos": _minutos(self.app.prefs.get("sentinela_minutos")),
                "cadastrado": self.cadastrado(), "windows": windows.WINDOWS}

    def dados_holograma(self) -> dict:
        return {**self.estado(), "fotos": self.fotos()[:30]}

    def _publicar(self) -> None:
        try:
            self.app.barramento.publicar("sentinela", **self.estado())
            if self.app.hologramas.aberto("sentinela"):
                self.app.hologramas.atualizar_tipo("sentinela", self.dados_holograma())
        except Exception:  # noqa: BLE001 - sem HUD (testes): o estado basta
            log.debug("Não consegui publicar o estado do Sentinela", exc_info=True)

    # -- armar / desarmar ----------------------------------------------------------------------
    def armar(self, motivo: str = "voz") -> str:
        with self._lock:
            if self.armado:
                return "O Protocolo Sentinela já está ativo."
            self.armado, self.desde, self.motivo = True, time.time(), motivo
            self.alertas = 0
            self._dono_seguidos = self._estranho_seguidos = self._ausente_seguidos = 0
        aviso = ""
        try:
            windows.bloquear_windows()
        except windows.NaoSuportado:
            aviso = " Fora do Windows não consigo bloquear a tela."
        except OSError as erro:
            log.warning("Sentinela: não bloqueei o Windows: %s", erro)
            aviso = " O Windows não deixou bloquear a tela."
        try:
            self.app.sessao.bloquear("sentinela")
        except Exception:  # noqa: BLE001
            log.debug("Sessão não bloqueou", exc_info=True)
        log.info("Protocolo Sentinela armado (%s)", motivo)
        self._anotar("Protocolo Sentinela ativado" + (" automaticamente." if motivo == "automatico" else "."))
        self._publicar()
        self._acordar.set()
        frase = "Protocolo Sentinela ativado. Fico de olho."
        if not self.cadastrado():
            frase += (" Seu rosto não está cadastrado, então vou fotografar qualquer pessoa que mexer no PC. "
                      "Cadastre em Ajustes para eu te reconhecer.")
        return frase + aviso

    def desarmar(self, motivo: str = "voz", saudar: bool = False) -> str:
        with self._lock:
            if not self.armado:
                return "O Protocolo Sentinela não está ativo."
            self.armado, self.desde, self.motivo = False, None, ""
            alertas, self.alertas = self.alertas, 0
        log.info("Protocolo Sentinela desarmado (%s)", motivo)
        self._anotar(f"Protocolo Sentinela desativado ({'rosto reconhecido' if motivo == 'rosto' else motivo}).")
        if motivo == "rosto" and getattr(self.app.sessao, "motivo", "") == "sentinela":
            try:
                self.app.sessao.desbloquear("rosto")
            except Exception:  # noqa: BLE001
                log.debug("Sessão não desbloqueou", exc_info=True)
        self._publicar()
        if alertas:
            frase = (f"Enquanto você esteve fora, registrei {alertas} alerta{'s' if alertas != 1 else ''}. "
                     "As fotos estão no holograma Sentinela.")
        else:
            frase = "Ninguém mexeu no PC."
        if saudar:
            nome = self.app.prefs.get("tratamento") or self.app.prefs.get("nome") or ""
            frase = f"Bem-vindo de volta{', ' + nome if nome else ''}. {frase}"
            try:
                self.app.fala.falar(frase)
            except Exception:  # noqa: BLE001
                log.debug("Sem voz para a saudação", exc_info=True)
            return frase
        return f"Protocolo Sentinela desativado. {frase}"

    # -- visão ---------------------------------------------------------------------------------
    def _ler_quadros(self, quantos: int) -> list:
        camera = self.app.camera
        uso = "sentinela"
        quadros: list = []
        camera.adquirir(uso)
        try:
            quadro, seq = camera.esperar_quadro(0, 4.0)  # a câmera leva um tempo para ligar
            if quadro is None:
                return []
            quadros.append(quadro)
            while len(quadros) < quantos and not self._parar.is_set():
                time.sleep(ESPACO_QUADROS_S)
                quadro, seq = camera.esperar_quadro(seq, 1.5)
                if quadro is None:
                    break
                quadros.append(quadro)
        finally:
            camera.liberar(uso)
        return quadros

    def _avaliar(self, quadro) -> tuple[bool, bool]:
        """(tem rosto, é o dono) em um quadro."""
        rosto = self.app.rosto
        rostos = rosto.detectar(quadro)[:3]
        if not rostos:
            return False, False
        if not self.cadastrado():
            return True, False
        limiar = float(self.app.prefs.get("limiar_rosto") or 0.42)
        dono = any(rosto.similaridade(rosto.assinatura(quadro, r)) >= limiar for r in rostos)
        return True, dono

    def _avaliar_seguro(self, quadro) -> tuple[bool, bool] | None:
        try:
            return self._avaliar(quadro)
        except Exception as erro:  # noqa: BLE001 - sem modelos de rosto: segue só com a atividade
            if not self._sem_visao_avisado:
                log.warning("Sentinela sem reconhecimento facial: %s", erro)
                self._sem_visao_avisado = True
            return None

    def checar(self, atividade: bool = False) -> str:
        """Uma olhada pela câmera. Devolve "dono", "intruso", "rosto", "vazio" ou "nada"."""
        if not self.armado:
            return "nada"
        quadros = self._ler_quadros(QUADROS_ATIVIDADE if atividade else QUADROS_CHECAGEM)
        viu_dono, foto, viu_rosto = False, None, False
        for quadro in quadros:
            avaliado = self._avaliar_seguro(quadro)
            foto = quadro if foto is None or avaliado and avaliado[0] else foto
            if avaliado is None:
                continue
            tem, dono = avaliado
            viu_rosto = viu_rosto or tem
            if dono:
                viu_dono = True
                self._dono_seguidos += 1
                self._estranho_seguidos = 0
            elif tem:
                self._estranho_seguidos += 1
                self._dono_seguidos = 0
            else:
                self._dono_seguidos = self._estranho_seguidos = 0
            if self._dono_seguidos >= 2:
                self.desarmar("rosto", saudar=True)
                return "dono"
            if self._estranho_seguidos >= 2 and self.cadastrado():
                self._estranho_seguidos = 0
                self.alertar(quadro, "rosto")
                return "intruso"
        if atividade and not viu_dono:
            self.alertar(foto, "rosto" if viu_rosto and self.cadastrado() else "atividade")
            return "intruso"
        return "rosto" if viu_rosto else "vazio"

    # -- alerta --------------------------------------------------------------------------------
    def _salvar_foto(self, quadro, quando: datetime) -> str | None:
        if quadro is None:
            return None
        try:
            import cv2

            ok, dados = cv2.imencode(".jpg", quadro, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            if not ok:
                return None
            self.pasta.mkdir(parents=True, exist_ok=True)
            base = quando.strftime("%Y-%m-%d_%H-%M-%S")
            nome, n = f"{base}.jpg", 1
            while (self.pasta / nome).exists() and n < 99:
                nome, n = f"{base}_{n}.jpg", n + 1
            (self.pasta / nome).write_bytes(dados.tobytes())
            return nome
        except Exception:  # noqa: BLE001 - sem foto, o aviso ainda vale
            log.exception("Sentinela: não consegui salvar a foto")
            return None

    def alertar(self, quadro, tipo: str) -> bool:
        """Foto + registros + celular. Nunca fala (o PC pode estar num lugar público)."""
        agora = time.time()
        with self._lock:
            if agora - self._ultimo_alerta < ALERTA_INTERVALO_S:
                return False
            self._ultimo_alerta = agora
            self.alertas += 1
        quando = datetime.now()
        nome = self._salvar_foto(quadro, quando)
        hora = _agora_texto(quando)
        if tipo == "rosto":
            descricao = f"Rosto desconhecido no PC às {hora}."
        else:
            descricao = f"Alguém mexeu no PC às {hora} sem o seu rosto na frente da câmera."
        complemento = " A foto ficou salva no computador." if nome else " Não consegui tirar a foto."
        log.warning("Sentinela: %s", descricao)
        self._anotar(descricao + (f" Foto: {nome}." if nome else ""), {"foto": nome or "", "tipo": tipo})
        self._lembrar(descricao, tipo, quando)
        self._historico_seguranca(descricao, nome, tipo, quando)
        try:
            from ..habilidades.notificacoes import notificar

            notificar(self.app, descricao + complemento, titulo="Sentinela", prioridade="high")
        except Exception:  # noqa: BLE001
            log.exception("Sentinela: o aviso ao celular falhou")
        self._publicar()
        return True

    def _anotar(self, resumo: str, argumentos: dict | None = None) -> None:
        try:
            self.app.atividades.anotar({"ferramenta": "sentinela", "argumentos": argumentos or {}, "nivel": 1,
                                        "situacao": "ok", "resumo": resumo, "canal": "sentinela"})
        except Exception:  # noqa: BLE001
            log.debug("Sem registro de atividades", exc_info=True)

    def _lembrar(self, descricao: str, tipo: str, quando: datetime) -> None:
        aprender = getattr(getattr(self.app, "memoria", None), "aprender", None)
        if aprender is None:
            return
        try:
            aprender("conhecimento", f"Protocolo Sentinela em {quando:%d/%m/%Y}: {descricao}",
                     etiquetas=["sentinela", "seguranca", f"alerta:{tipo}"], origem="sentinela")
        except Exception:  # noqa: BLE001 - memória nunca derruba o alerta
            log.debug("Memória indisponível", exc_info=True)

    def _historico_seguranca(self, descricao: str, nome: str | None, tipo: str, quando: datetime) -> None:
        seg = getattr(self.app, "seguranca", None)
        guardar = getattr(seg, "guardar", None) or getattr(seg, "_guardar", None)
        if guardar is None:
            return
        try:
            guardar({"tipo": "sentinela", "quando": quando.isoformat(timespec="seconds"), "risco": "alto",
                     "arquivo": f"Sentinela: {'rosto desconhecido' if tipo == 'rosto' else 'alguém mexeu no PC'} "
                                f"às {_agora_texto(quando)}",
                     "descricao": descricao, "foto": nome or "", "alerta": tipo})
        except Exception:  # noqa: BLE001
            log.debug("Histórico de segurança indisponível", exc_info=True)

    # -- laços ---------------------------------------------------------------------------------
    def _houve_atividade(self) -> bool:
        if self.desde is None or time.time() - self.desde < CARENCIA_S:
            return False
        ocioso = self.ocioso()
        return ocioso is not None and ocioso < ATIVIDADE_S

    def _vigiar_armado(self) -> None:
        proxima = time.monotonic() + 2.0
        bloqueado_antes = self.bloqueado()
        while self.armado and not self._parar.is_set():
            atividade = self._houve_atividade()
            bloqueado = self.bloqueado()
            if bloqueado_antes and bloqueado is False and not self.cadastrado():
                # sem rosto cadastrado, só quem sabe a senha do Windows desbloqueia: é você
                self.desarmar("windows", saudar=True)
                return
            bloqueado_antes = bloqueado if bloqueado is not None else bloqueado_antes
            if atividade or time.monotonic() >= proxima:
                try:
                    self.checar(atividade)
                except Exception:  # noqa: BLE001
                    log.exception("Erro na vigilância do Sentinela")
                proxima = time.monotonic() + INTERVALO_S
            self._parar.wait(0.5)

    def ausente(self) -> bool:
        """Para o modo automático: ninguém mexe há X minutos e a câmera não vê o seu rosto."""
        ocioso = self.ocioso()
        if ocioso is None or ocioso < _minutos(self.app.prefs.get("sentinela_minutos")) * 60:
            self._ausente_seguidos = 0
            self._pausa_ate = 0.0
            return False
        if time.monotonic() < self._pausa_ate:
            return False
        viu_dono = viu_rosto = False
        for quadro in self._ler_quadros(2):
            avaliado = self._avaliar_seguro(quadro)
            if avaliado:
                viu_rosto = viu_rosto or avaliado[0]
                viu_dono = viu_dono or avaliado[1]
        presente = viu_dono or (viu_rosto and not self.cadastrado())
        if presente:  # você está aí (vendo um filme?): a câmera descansa um pouco
            self._pausa_ate = time.monotonic() + PAUSA_PRESENTE_S
        self._ausente_seguidos = 0 if presente else self._ausente_seguidos + 1
        return self._ausente_seguidos >= 2

    def _laco(self) -> None:
        while not self._parar.is_set():
            if self.armado:
                self._vigiar_armado()
                continue
            if self.app.prefs.get("sentinela_auto") and windows.WINDOWS:
                try:
                    if self.ausente():
                        self.armar("automatico")
                        continue
                except Exception:  # noqa: BLE001
                    log.exception("Erro no Sentinela automático")
            self._acordar.wait(AUTO_CHECAR_S)
            self._acordar.clear()

    def iniciar(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._parar.clear()
            self._thread = threading.Thread(target=self._laco, name="sentinela", daemon=True)
            self._thread.start()

    def encerrar(self) -> None:
        self._parar.set()
        self._acordar.set()


def _segundos_ocioso() -> float | None:
    from ..habilidades import gatilhos

    return gatilhos.segundos_ocioso()


def _minutos(valor) -> float:
    try:
        return max(1.0, float(valor or 5))
    except (TypeError, ValueError):
        return 5.0


# ================================================================================================
# Casa Limpa
# ================================================================================================

def formatar_bytes(total: int) -> str:
    if total >= 1024 ** 3:
        return f"{total / 1024 ** 3:.1f} GB".replace(".", ",")
    if total >= 1024 ** 2:
        return f"{round(total / 1024 ** 2)} MB"
    if total >= 1024:
        return f"{round(total / 1024)} KB"
    return f"{total} bytes"


def _eh_link(caminho: str, info: os.stat_result) -> bool:
    if stat.S_ISLNK(info.st_mode):
        return True
    if getattr(info, "st_file_attributes", 0) & ATRIBUTO_REPARSE:
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction and isjunction(caminho))


def pasta_temporaria() -> Path:
    return Path(os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir())


def raiz_temporaria_segura(raiz: Path) -> bool:
    """Nunca limpa a raiz de um disco, a pasta do usuário nem algo raso demais."""
    try:
        raiz = raiz.resolve()
    except OSError:
        return False
    casa = Path.home().resolve()
    return raiz.is_dir() and len(raiz.parts) >= 3 and raiz != casa and raiz not in casa.parents


def limpar_temporarios(raiz: Path | None = None, idade_s: float = IDADE_TEMPORARIO_S,
                       agora: float | None = None) -> dict:
    """Apaga arquivos com mais de ``idade_s`` dentro de ``raiz`` (o %TEMP%). Não segue links nem junções,
    não sai da raiz, pula o que está em uso e remove as subpastas que ficaram vazias."""
    raiz = (raiz or pasta_temporaria())
    if not raiz_temporaria_segura(raiz):
        return {"arquivos": 0, "bytes": 0, "erros": 0, "recusado": True}
    raiz = raiz.resolve()
    limite = (agora if agora is not None else time.time()) - idade_s
    apagados = liberados = erros = 0

    def dentro(caminho: str) -> bool:
        try:
            return os.path.commonpath([str(raiz), caminho]) == str(raiz)
        except ValueError:
            return False

    def varrer(pasta: str) -> bool:
        """Devolve True se a pasta ficou vazia."""
        nonlocal apagados, liberados, erros
        vazia = True
        try:
            entradas = list(os.scandir(pasta))
        except OSError:
            return False
        for entrada in entradas:
            caminho = entrada.path
            try:
                info = entrada.stat(follow_symlinks=False)
            except OSError:
                vazia = False
                continue
            if _eh_link(caminho, info) or not dentro(caminho):
                vazia = False  # link/junção: nem segue, nem apaga
                continue
            if stat.S_ISDIR(info.st_mode):
                if varrer(caminho) and info.st_mtime < limite:
                    try:
                        os.rmdir(caminho)
                        continue
                    except OSError:
                        pass
                vazia = False
                continue
            if info.st_mtime >= limite:
                vazia = False
                continue
            try:
                os.remove(caminho)
                apagados += 1
                liberados += info.st_size
            except OSError:  # em uso ou sem permissão
                erros += 1
                vazia = False
        return vazia

    varrer(str(raiz))
    return {"arquivos": apagados, "bytes": liberados, "erros": erros, "recusado": False}


def _pid_da_janela(hwnd: int) -> int:
    import ctypes
    from ctypes import wintypes

    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value)


def _pids_protegidos() -> set[int]:
    """A própria Sexta-Feira e a cadeia de processos que a abriu (o terminal, o atalho...)."""
    pids = {os.getpid()}
    try:
        import psutil

        pids.update(p.pid for p in psutil.Process().parents())
    except Exception:  # noqa: BLE001
        pass
    return pids


def pode_fechar(titulo: str, exe: str, pid: int, protegidos: set[int]) -> bool:
    from ..habilidades.apps import NUNCA_FECHAR

    if normalizar(titulo).startswith("sexta feira"):
        return False
    exe = exe.lower().removesuffix(".exe")
    if not exe or exe in NAO_FECHAR_EXE or f"{exe}.exe" in NUNCA_FECHAR or exe in NUNCA_FECHAR:
        return False
    return pid not in protegidos


def fechar_tudo() -> int:
    """WM_CLOSE em cada janela de programa do usuário (cada um pode pedir para salvar)."""
    from ..habilidades import janelas

    protegidos = _pids_protegidos()
    fechadas = 0
    for janela in janelas.listar():
        try:
            pid = _pid_da_janela(janela.hwnd)
        except Exception:  # noqa: BLE001
            continue
        if not pode_fechar(janela.titulo, janela.exe, pid, protegidos):
            continue
        try:
            janelas.fechar(janela)
            fechadas += 1
        except Exception:  # noqa: BLE001
            log.debug("Não fechei %s", janela.rotulo(), exc_info=True)
    return fechadas


def _organizar_downloads(app, ctx) -> int:
    resultado = app.registro.executar("arquivos", {"acao": "organizar_downloads"}, replace(ctx, confiavel=True))
    if not resultado.get("ok"):
        return 0
    achado = re.search(r"(\d+)\s+arquivos?", str(resultado.get("resumo") or ""))
    return int(achado.group(1)) if achado else 0


def frase_casa_limpa(janelas_: int, organizados: int, temporarios: dict) -> str:
    partes = [f"fechei {janelas_} janela{'s' if janelas_ != 1 else ''}" if janelas_ else "não havia janelas para fechar"]
    partes.append(f"organizei {organizados} arquivo{'s' if organizados != 1 else ''}" if organizados
                  else "Downloads já estava organizado")
    if temporarios.get("recusado"):
        partes.append("não mexi nos temporários (pasta estranha)")
    elif temporarios.get("bytes"):
        partes.append(f"liberei {formatar_bytes(temporarios['bytes'])} de temporários")
    else:
        partes.append("não havia temporários antigos")
    texto = ", ".join(partes[:-1]) + " e " + partes[-1] + "."
    return texto[0].upper() + texto[1:]


def casa_limpa(app, ctx) -> dict:
    if not windows.WINDOWS:
        return {"ok": False, "resumo": "A Casa Limpa só funciona no Windows."}
    fechadas = fechar_tudo()
    if fechadas:
        time.sleep(2.0)  # os programas soltam os arquivos temporários ao fechar
    organizados = _organizar_downloads(app, ctx)
    temporarios = limpar_temporarios()
    frase = frase_casa_limpa(fechadas, organizados, temporarios)
    return {"ok": True, "resumo": frase, "janelas": fechadas, "organizados": organizados,
            "temporarios": temporarios}


def _acao_fechar_tudo(app, valor, ctx, variaveis) -> None:
    if not windows.WINDOWS:
        app.barramento.publicar("aviso", nivel="erro", texto="Protocolo: fechar tudo só funciona no Windows.")
        return
    total = fechar_tudo()
    app.barramento.publicar("aviso", nivel="info", texto=f"Protocolo: pedi para fechar {total} janelas.")


def _acao_limpar_temporarios(app, valor, ctx, variaveis) -> None:
    if not windows.WINDOWS:
        app.barramento.publicar("aviso", nivel="erro", texto="Protocolo: limpar temporários só funciona no Windows.")
        return
    r = limpar_temporarios()
    app.barramento.publicar("aviso", nivel="info",
                            texto=f"Protocolo: apaguei {r['arquivos']} temporários ({formatar_bytes(r['bytes'])}).")


ACOES_PROTOCOLO = {
    "fechar_tudo": {"rotulo": "Fechar todos os programas", "entrada": "nenhum",
                    "dica": "fecha as janelas com calma (cada programa pode pedir para salvar)",
                    "executar": _acao_fechar_tudo},
    "limpar_temporarios": {"rotulo": "Limpar temporários", "entrada": "nenhum",
                           "dica": "apaga arquivos da pasta TEMP com mais de 24 horas",
                           "executar": _acao_limpar_temporarios},
}


# ================================================================================================
# Onde eu parei
# ================================================================================================

def limpar_url(url: str) -> str | None:
    try:
        partes = urlsplit(url)
    except ValueError:
        return None
    if partes.scheme not in ("http", "https") or not partes.netloc:
        return None
    if _RUIDO_URL.search(f"{partes.netloc}{partes.path}{'?' + partes.query if partes.query else ''}"):
        return None
    return urlunsplit((partes.scheme, partes.netloc, partes.path, partes.query, ""))


def escolher_abas(visitas: list[tuple[str, str, float]], limite: int = MAX_ABAS) -> list[dict]:
    """[(url, titulo, unix)] -> as ``limite`` páginas mais recentes, sem repetidas e sem ruído."""
    vistas: dict[str, dict] = {}
    for url, titulo, quando in sorted(visitas, key=lambda v: v[2], reverse=True):
        limpa = limpar_url(url)
        if limpa is None or limpa in vistas:
            continue
        vistas[limpa] = {"url": limpa, "titulo": (titulo or "").strip()[:120] or urlsplit(limpa).netloc,
                         "quando": quando}
        if len(vistas) >= limite:
            break
    return list(vistas.values())


def _copiar_e_ler(arquivo: Path, consulta: str, parametros: tuple) -> list[tuple]:
    """O navegador mantém o banco travado: lê uma cópia temporária (com o -wal, se houver)."""
    pasta = Path(tempfile.mkdtemp(prefix="sexta-historico-"))
    try:
        copia = pasta / "historico.sqlite"
        shutil.copy2(arquivo, copia)
        for sufixo in ("-wal", "-journal"):
            extra = arquivo.with_name(arquivo.name + sufixo)
            if extra.exists():
                try:
                    shutil.copy2(extra, pasta / f"historico.sqlite{sufixo}")
                except OSError:
                    pass
        conexao = sqlite3.connect(str(copia))
        try:
            return conexao.execute(consulta, parametros).fetchall()
        finally:
            conexao.close()
    except (OSError, sqlite3.Error) as erro:
        log.debug("Histórico de %s ilegível: %s", arquivo, erro)
        return []
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def ler_historico_chromium(arquivo: Path, desde: float) -> list[tuple[str, str, float]]:
    limite = int((desde + EPOCA_CHROME_S) * 1_000_000)
    linhas = _copiar_e_ler(arquivo, "SELECT url, title, last_visit_time FROM urls WHERE last_visit_time >= ? "
                                    "ORDER BY last_visit_time DESC LIMIT 300", (limite,))
    return [(u, t or "", v / 1_000_000 - EPOCA_CHROME_S) for u, t, v in linhas if u and v]


def ler_historico_firefox(arquivo: Path, desde: float) -> list[tuple[str, str, float]]:
    linhas = _copiar_e_ler(arquivo, "SELECT url, title, last_visit_date FROM moz_places WHERE last_visit_date >= ? "
                                    "ORDER BY last_visit_date DESC LIMIT 300", (int(desde * 1_000_000),))
    return [(u, t or "", v / 1_000_000) for u, t, v in linhas if u and v]


def arquivos_historico() -> list[tuple[str, Path]]:
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    achados: list[tuple[str, Path]] = []
    for base in (local / "Google" / "Chrome" / "User Data", local / "Microsoft" / "Edge" / "User Data",
                 local / "BraveSoftware" / "Brave-Browser" / "User Data"):
        try:
            perfis = [p for p in base.iterdir() if p.is_dir() and (p.name == "Default" or p.name.startswith("Profile"))]
        except OSError:
            continue
        achados += [("chromium", p / "History") for p in perfis if (p / "History").is_file()]
    try:
        achados += [("firefox", p / "places.sqlite") for p in (roaming / "Mozilla" / "Firefox" / "Profiles").iterdir()
                    if (p / "places.sqlite").is_file()]
    except OSError:
        pass
    return achados


def abas_recentes(desde: float, fontes: list[tuple[str, Path]] | None = None) -> list[dict]:
    visitas: list[tuple[str, str, float]] = []
    for tipo, arquivo in (fontes if fontes is not None else arquivos_historico()):
        leitor = ler_historico_firefox if tipo == "firefox" else ler_historico_chromium
        visitas += leitor(arquivo, desde)
    return escolher_abas(visitas)


def _aspas_ps(texto: str) -> str:
    return "'" + texto.replace("'", "''") + "'"


def arquivos_recentes(desde: float) -> list[dict]:
    """Atalhos da pasta Recent modificados na sessão, resolvidos numa só chamada do PowerShell."""
    if not windows.WINDOWS:
        return []
    pasta = Path(os.environ.get("APPDATA") or "") / "Microsoft" / "Windows" / "Recent"
    try:
        atalhos = sorted((f for f in pasta.glob("*.lnk") if f.stat().st_mtime >= desde),
                         key=lambda f: f.stat().st_mtime, reverse=True)[:30]
    except OSError:
        return []
    if not atalhos:
        return []
    lista = ",".join(_aspas_ps(str(f)) for f in atalhos)
    script = ("$sh = New-Object -ComObject WScript.Shell; "
              f"$alvos = @(foreach ($l in @({lista})) {{ try {{ $sh.CreateShortcut($l).TargetPath }} catch {{ '' }} }}); "
              "ConvertTo-Json -Compress -InputObject $alvos")
    try:
        alvos = json.loads(windows.powershell(script, timeout=20) or "[]")
    except (OSError, ValueError, subprocess.SubprocessError) as erro:
        log.debug("Não li os arquivos recentes: %s", erro)
        return []
    if isinstance(alvos, str):
        alvos = [alvos]
    saida, vistos = [], set()
    for alvo in alvos:
        if not alvo or not isinstance(alvo, str) or alvo.lower() in vistos:
            continue
        caminho = Path(alvo)
        if caminho.is_file():
            vistos.add(alvo.lower())
            saida.append({"nome": caminho.name, "caminho": str(caminho)})
        if len(saida) >= MAX_ARQUIVOS:
            break
    return saida


def apps_abertos() -> list[dict]:
    if not windows.WINDOWS:
        return []
    import psutil

    from ..habilidades import janelas
    from ..habilidades.apps import NUNCA_FECHAR

    saida: dict[str, dict] = {}
    for janela in janelas.listar():
        exe = janela.exe
        if not exe or exe in APPS_SISTEMA or f"{exe}.exe" in NUNCA_FECHAR or normalizar(janela.titulo).startswith("sexta feira"):
            continue
        try:
            caminho = psutil.Process(_pid_da_janela(janela.hwnd)).exe()
        except Exception:  # noqa: BLE001
            continue
        if not caminho or caminho.lower().startswith(os.environ.get("SystemRoot", r"C:\Windows").lower()):
            continue
        chave = caminho.lower()
        if chave in saida:
            saida[chave]["janelas"] += 1
            continue
        saida[chave] = {"exe": exe, "caminho": caminho, "titulo": janela.titulo[:120], "janelas": 1}
        if len(saida) >= MAX_APPS:
            break
    return list(saida.values())


def nome_app(exe: str) -> str:
    return NOMES_APPS.get(exe.lower(), exe[:1].upper() + exe[1:])


def _assunto(app_: dict) -> str:
    """ "relatorio.py - projeto-x - Visual Studio Code" -> "projeto-x"."""
    partes = [p.strip() for p in re.split(r" [-—–|] ", app_.get("titulo") or "") if p.strip()]
    if app_.get("exe") == "code" and len(partes) >= 3:
        return partes[-2]
    return ""


def resumo_sessao(sessao: dict) -> str:
    apps, arquivos, abas = sessao.get("apps") or [], sessao.get("arquivos") or [], sessao.get("abas") or []
    partes: list[str] = []
    navegador = next((a for a in apps if a["exe"] in NAVEGADORES), None)
    for app_ in apps:
        if app_ is navegador or len(partes) >= 1:
            continue
        assunto = _assunto(app_)
        partes.append(f"no {nome_app(app_['exe'])}" + (f" em {assunto}" if assunto else ""))
    if abas:
        onde = f"no {nome_app(navegador['exe'])}" if navegador else "no navegador"
        partes.append(f"{onde} com {len(abas)} aba{'s' if len(abas) != 1 else ''}")
    elif navegador:
        partes.append(f"no {nome_app(navegador['exe'])}")
    if arquivos:
        partes.append(f"editando {arquivos[0]['nome']}")
    if not partes:
        return "Não anotei nada da sua sessão anterior."
    texto = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]
    return f"Você estava {texto}. Quer que eu reabra?"


class Sessoes:
    def __init__(self, app, arquivo: Path) -> None:
        self.app = app
        self.arquivo = arquivo
        self._lock = threading.Lock()
        self._sessoes: list[dict] = self._carregar()
        self._ultima_atividade = 0.0
        self._ultimo_instantaneo = 0.0
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        # dá para trocar nos testes
        self.coletar_apps = apps_abertos
        self.coletar_arquivos = arquivos_recentes
        self.coletar_abas = abas_recentes
        self.ocioso = _segundos_ocioso
        self.bloqueado = windows.sessao_bloqueada

    def _carregar(self) -> list[dict]:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            return [s for s in dados if isinstance(s, dict) and "id" in s][-MAX_SESSOES:] if isinstance(dados, list) else []
        except (OSError, ValueError):
            return []

    def _gravar(self) -> None:
        try:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.arquivo.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._sessoes, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.arquivo)
        except OSError as erro:
            log.warning("Não consegui salvar as sessões: %s", erro)

    def listar(self) -> list[dict]:
        with self._lock:
            return [dict(s) for s in self._sessoes]

    def obter(self, id_: str) -> dict | None:
        return next((s for s in self.listar() if s["id"] == id_), None)

    def atual(self, agora: float) -> dict:
        """A sessão em andamento (cria outra depois de 30 min longe ou num novo dia)."""
        with self._lock:
            ultima = self._sessoes[-1] if self._sessoes else None
            if ultima is not None:
                fim = ultima.get("fim_ts", ultima.get("inicio_ts", 0))
                mesmo_dia = datetime.fromtimestamp(fim).date() == datetime.fromtimestamp(agora).date()
                if agora - fim < NOVA_SESSAO_S and mesmo_dia:
                    return ultima
            nova = {"id": uuid.uuid4().hex[:10], "inicio_ts": agora, "fim_ts": agora,
                    "inicio": datetime.fromtimestamp(agora).isoformat(timespec="minutes"),
                    "fim": datetime.fromtimestamp(agora).isoformat(timespec="minutes"),
                    "apps": [], "arquivos": [], "abas": []}
            self._sessoes.append(nova)
            del self._sessoes[:-MAX_SESSOES]
            return nova

    def marcar_atividade(self, agora: float) -> None:
        sessao = self.atual(agora)
        with self._lock:
            sessao["fim_ts"] = agora
            sessao["fim"] = datetime.fromtimestamp(agora).isoformat(timespec="minutes")

    def instantaneo(self, agora: float | None = None) -> dict:
        agora = agora or time.time()
        sessao = self.atual(agora)
        inicio = sessao["inicio_ts"]
        apps = self._seguro(self.coletar_apps)
        arquivos = self._seguro(self.coletar_arquivos, inicio)
        abas = self._seguro(self.coletar_abas, max(inicio, agora - ABAS_JANELA_S))
        with self._lock:
            if apps:  # uma leitura vazia (tela bloqueando) não apaga o que já sabíamos
                sessao["apps"] = apps
            if arquivos:
                sessao["arquivos"] = arquivos
            if abas:
                sessao["abas"] = abas
            sessao["fim_ts"] = agora
            sessao["fim"] = datetime.fromtimestamp(agora).isoformat(timespec="minutes")
            self._gravar()
        self._ultimo_instantaneo = agora
        return dict(sessao)

    @staticmethod
    def _seguro(funcao, *args) -> list:
        try:
            return list(funcao(*args) or [])
        except Exception:  # noqa: BLE001
            log.debug("Coleta da sessão falhou", exc_info=True)
            return []

    def anterior(self, agora: float | None = None) -> dict | None:
        """A sessão para "onde eu parei": a anterior, se a atual acabou de começar."""
        agora = agora or time.time()
        sessoes = [s for s in self.listar() if s.get("apps") or s.get("arquivos") or s.get("abas")]
        if not sessoes:
            return None
        ultima = sessoes[-1]
        recente = agora - ultima.get("fim_ts", 0) < NOVA_SESSAO_S
        if recente and agora - ultima["inicio_ts"] < SESSAO_NOVA_S and len(sessoes) > 1:
            return sessoes[-2]
        return ultima

    # -- laço ------------------------------------------------------------------------------------
    def passo(self, agora: float | None = None) -> None:
        agora = agora or time.time()
        bloqueado = self.bloqueado()
        if bloqueado and not self._bloqueado_antes and self._ultima_atividade:
            self.instantaneo(agora)  # o Windows acabou de bloquear: anota como ficou
        self._bloqueado_antes = bool(bloqueado)
        ocioso = self.ocioso()
        if bloqueado or ocioso is None or ocioso > INSTANTANEO_S:
            return
        self._ultima_atividade = agora
        self.marcar_atividade(agora)
        if agora - self._ultimo_instantaneo >= INSTANTANEO_S:
            self.instantaneo(agora)

    _bloqueado_antes = False

    def _laco(self) -> None:
        self._parar.wait(60)  # não disputa a máquina com a subida da Sexta-Feira
        while not self._parar.is_set():
            try:
                self.passo()
            except Exception:  # noqa: BLE001
                log.exception("Erro anotando a sessão")
            self._parar.wait(VIGIA_SESSAO_S)

    def iniciar(self) -> None:
        if not windows.WINDOWS:
            return
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._laco, name="sessoes", daemon=True)
            self._thread.start()

    def encerrar(self) -> None:
        self._parar.set()


def _processos_rodando() -> set[str]:
    try:
        import psutil
    except ImportError:
        return set()
    caminhos = set()
    for p in psutil.process_iter(["exe"]):
        exe = p.info.get("exe")
        if exe:
            caminhos.add(exe.lower())
    return caminhos


def reabrir(sessao: dict, apps: list[int] | None = None, arquivos: list[int] | None = None,
            abas: list[int] | None = None) -> dict:
    """Reabre os itens escolhidos (índices da sessão salva; ``None`` = todos). Só abre o que está anotado."""
    windows._exigir_windows()

    def escolher(lista: list, indices: list[int] | None) -> list:
        if indices is None:
            return list(lista)
        return [lista[i] for i in dict.fromkeys(indices) if isinstance(i, int) and 0 <= i < len(lista)]

    rodando = _processos_rodando()
    abertos = {"apps": 0, "arquivos": 0, "abas": 0, "ja_abertos": 0}
    for item in escolher(sessao.get("apps") or [], apps):
        caminho = str(item.get("caminho") or "")
        if not caminho.lower().endswith(".exe") or not Path(caminho).is_file():
            continue
        if caminho.lower() in rodando:
            abertos["ja_abertos"] += 1
            continue
        try:
            subprocess.Popen([caminho], cwd=str(Path(caminho).parent), close_fds=True)
            abertos["apps"] += 1
        except OSError as erro:
            log.warning("Não reabri %s: %s", caminho, erro)
    for item in escolher(sessao.get("arquivos") or [], arquivos):
        caminho = str(item.get("caminho") or "")
        if caminho and Path(caminho).is_file() and Path(caminho).suffix.lower() not in (".exe", ".bat", ".cmd",
                                                                                         ".ps1", ".vbs", ".msi",
                                                                                         ".lnk", ".scr", ".com"):
            try:
                os.startfile(caminho)  # type: ignore[attr-defined]
                abertos["arquivos"] += 1
            except OSError as erro:
                log.warning("Não reabri %s: %s", caminho, erro)
    urls = [a["url"] for a in escolher(sessao.get("abas") or [], abas) if limpar_url(str(a.get("url") or ""))]
    for i, url in enumerate(urls):
        webbrowser.open(url, new=1 if i == 0 else 2)  # uma janela, o resto em abas
        abertos["abas"] += 1
    return abertos


def frase_reabertos(r: dict) -> str:
    partes = []
    if r["apps"]:
        partes.append(f"{r['apps']} programa{'s' if r['apps'] != 1 else ''}")
    if r["arquivos"]:
        partes.append(f"{r['arquivos']} arquivo{'s' if r['arquivos'] != 1 else ''}")
    if r["abas"]:
        partes.append(f"{r['abas']} página{'s' if r['abas'] != 1 else ''}")
    if not partes:
        return "Já estava tudo aberto." if r["ja_abertos"] else "Não havia nada para reabrir."
    texto = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]
    return f"Reabri {texto}."


def dados_retomar(sessao: dict | None) -> dict:
    if sessao is None:
        return {"sessao": None}
    publico = {k: sessao.get(k) for k in ("id", "inicio", "fim", "apps", "arquivos", "abas")}
    return {"sessao": publico, "resumo": resumo_sessao(sessao)}


# ================================================================================================
# ganchos
# ================================================================================================

def instalar(app) -> None:
    app.sentinela = Sentinela(app, app.cfg.dados / "sentinela")
    app.sessoes = Sessoes(app, app.cfg.dados / "sessoes.json")


def _nivel_sentinela(args: dict) -> int:
    return ROSTO if args.get("acao") == "desativar" else LIVRE


def _nivel_retomar(args: dict) -> int:
    return CONFIRMAR if args.get("acao") == "reabrir" else LIVRE


def registrar(app, registro) -> None:
    @registro.ferramenta(
        "sentinela",
        "Protocolo Sentinela: bloqueia o PC e vigia pela webcam enquanto o usuário está longe; fotografa quem "
        "mexer e avisa no celular. ativar arma; desativar desarma (confere o rosto); status diz se está ativo; "
        "mostrar abre o holograma com as fotos.",
        nivel=_nivel_sentinela, direta=True,
        descrever=lambda a: "desativar o Protocolo Sentinela",
        acao=P("string", "Ação.", enum=["ativar", "desativar", "status", "mostrar"], obrigatorio=True),
    )
    def sentinela(ctx, acao: str):
        s: Sentinela = app.sentinela
        if acao == "ativar":
            return {"ok": True, "resumo": s.armar("voz" if ctx.canal == "voz" else ctx.canal)}
        if acao == "desativar":
            return {"ok": True, "resumo": s.desarmar(ctx.canal)}
        if acao == "mostrar":
            app.hologramas.mostrar("sentinela", s.dados_holograma())
            return {"ok": True, "resumo": "Aqui está o Sentinela."}
        fotos = len(s.fotos())
        texto = "O Protocolo Sentinela está ativo." if s.armado else "O Protocolo Sentinela está desligado."
        if fotos:
            texto += f" Tenho {fotos} foto{'s' if fotos != 1 else ''} guardada{'s' if fotos != 1 else ''}."
        return {"ok": True, "resumo": texto}

    @registro.ferramenta(
        "casa_limpa",
        "Protocolo Casa Limpa: fecha todas as janelas de programas do usuário (cada um pode pedir para salvar), "
        "organiza a pasta Downloads e apaga arquivos temporários com mais de 24 horas.",
        nivel=CONFIRMAR, direta=True,
        descrever=lambda a: ("fechar todos os programas abertos (o que não foi salvo pode pedir para salvar), "
                             "organizar a pasta Downloads e apagar os temporários com mais de 24 horas"),
    )
    def casa_limpa_ferramenta(ctx):
        return casa_limpa(app, ctx)

    @registro.ferramenta(
        "retomar",
        "Onde o usuário parou: mostrar lista os programas, arquivos e páginas da sessão anterior e pergunta se "
        "reabre; reabrir abre tudo de novo (pede confirmação).",
        nivel=_nivel_retomar, direta=True,
        descrever=lambda a: "reabrir os programas, arquivos e páginas da sua sessão anterior",
        acao=P("string", "Ação.", enum=["mostrar", "reabrir"], obrigatorio=True),
        sessao=P("string", "Para reabrir: o id da sessão (vazio = a anterior)."),
    )
    def retomar(ctx, acao: str, sessao: str | None = None):
        sessoes: Sessoes = app.sessoes
        alvo = sessoes.obter(sessao) if sessao else sessoes.anterior()
        if alvo is None:
            return {"ok": False, "resumo": "Ainda não anotei nenhuma sessão sua. Eu anoto a cada 5 minutos de uso, "
                                           "no Windows."}
        if acao == "reabrir":
            try:
                return {"ok": True, "resumo": frase_reabertos(reabrir(alvo))}
            except windows.NaoSuportado as erro:
                return {"ok": False, "resumo": str(erro)}
        dados = dados_retomar(alvo)
        try:
            app.hologramas.mostrar("retomar", dados)
        except Exception:  # noqa: BLE001
            log.debug("Sem holograma", exc_info=True)
        resumo = dados["resumo"]
        if resumo.endswith("Quer que eu reabra?"):
            registro.aguardar("retomar", {"acao": "reabrir", "sessao": alvo["id"]},
                              "reabrir os programas, arquivos e páginas da sessão anterior", ctx, CONFIRMAR)
            return {"ok": True, "resumo": resumo, "pendente": True}
        return {"ok": True, "resumo": resumo}


_SEXTA = r"(?:sexta feira |sexta )?"
_VERBO_ATIVAR = r"(?:ativa|ative|ativar|liga|ligue|ligar|inicia|inicie|iniciar|aciona|acione|entra|entre|entrar|executa|execute)"
_ATIVAR = re.compile(rf"^{_SEXTA}(?:{_VERBO_ATIVAR}(?: o| em| no)? )?(?:protocolo|modo) sentinela$|"
                     rf"^{_SEXTA}{_VERBO_ATIVAR}(?: o)? sentinela$")
_DESATIVAR = re.compile(rf"^{_SEXTA}(?:desativa|desative|desativar|desliga|desligue|desligar|desarma|desarme|"
                        r"desarmar|para|pare|parar|encerra|encerre|sai|sair)(?: o| do| da)? (?:protocolo |modo )?"
                        r"sentinela$")
_MOSTRAR_SENTINELA = re.compile(rf"^{_SEXTA}(?:abre|abrir|mostra|mostrar|exibe)(?: o| as)? (?:fotos do |holograma do |"
                                r"painel do )?(?:protocolo )?sentinela$")
_STATUS_SENTINELA = re.compile(rf"^{_SEXTA}(?:o )?(?:protocolo )?sentinela (?:esta )?(?:ativo|ligado|armado)$")
_CASA_LIMPA = re.compile(rf"^{_SEXTA}(?:(?:ativa|ative|executa|execute|roda|rode|inicia|inicie|faz|faca)(?: o| a)? )?"
                         r"(?:(?:protocolo |modo )?casa limpa|limpa a casa|(?:faz|faca) uma faxina no (?:pc|computador))$")
_RETOMAR = re.compile(rf"^{_SEXTA}(?:onde (?:e que )?eu parei|o que eu estava fazendo|retoma(?:r)? de onde (?:eu )?parei|"
                      r"retoma(?:r)? (?:a )?(?:minha )?sessao(?: anterior)?)$")


def atalho(t: str, ctx, rodar, original: str | None):
    t = t.rstrip(" ?")
    if _DESATIVAR.match(t):
        return rodar("sentinela", {"acao": "desativar"})
    if _ATIVAR.match(t):
        return rodar("sentinela", {"acao": "ativar"})
    if _MOSTRAR_SENTINELA.match(t):
        return rodar("sentinela", {"acao": "mostrar"})
    if _STATUS_SENTINELA.match(t):
        return rodar("sentinela", {"acao": "status"})
    if _CASA_LIMPA.match(t):
        return rodar("casa_limpa", {})
    if _RETOMAR.match(t):
        return rodar("retomar", {"acao": "mostrar"})
    return None


def rotas(api, app, autenticado, so_pc) -> None:
    from fastapi import Body, Depends, HTTPException
    from fastapi.responses import FileResponse

    s: Sentinela = app.sentinela

    def nome_ou_404(nome: str) -> Path:
        caminho = s.caminho_foto(nome)
        if caminho is None:
            raise HTTPException(404, "Foto não encontrada.")
        return caminho

    @api.get("/api/sentinela/estado")
    async def estado_sentinela(_=Depends(autenticado)):
        return await asyncio.to_thread(s.dados_holograma)

    @api.get("/api/sentinela/fotos")
    async def fotos_sentinela(_=Depends(autenticado)):
        return {"fotos": await asyncio.to_thread(s.fotos)}

    @api.get("/api/sentinela/fotos/{nome}")
    async def foto_sentinela(nome: str, _=Depends(autenticado)):
        return FileResponse(nome_ou_404(nome), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @api.delete("/api/sentinela/fotos/{nome}")
    async def apagar_foto_sentinela(nome: str, _=Depends(so_pc)):
        nome_ou_404(nome)
        await asyncio.to_thread(s.apagar_foto, nome)
        return {"texto": "Foto apagada.", "fotos": s.fotos()}

    @api.post("/api/sentinela/armar")
    async def armar_sentinela(_=Depends(so_pc)):
        return {"texto": await asyncio.to_thread(s.armar, "hud")}

    @api.post("/api/sentinela/desarmar")
    async def desarmar_sentinela(_=Depends(so_pc)):
        if app.sessao.bloqueada:
            raise HTTPException(423, "A Sexta-Feira está bloqueada. Olhe para a câmera ou use o PIN.")
        return {"texto": await asyncio.to_thread(s.desarmar, "hud")}

    @api.post("/api/retomar/reabrir")
    async def reabrir_sessao(corpo: dict = Body(...), _=Depends(so_pc)):
        if app.sessao.bloqueada:
            raise HTTPException(423, "A Sexta-Feira está bloqueada. Olhe para a câmera ou use o PIN.")
        sessao = app.sessoes.obter(str(corpo.get("sessao") or ""))
        if sessao is None:
            raise HTTPException(404, "Sessão não encontrada.")

        def indices(chave: str) -> list[int]:
            valor = corpo.get(chave) or []
            return [i for i in valor if isinstance(i, int) and not isinstance(i, bool)] if isinstance(valor, list) else []

        try:
            r = await asyncio.to_thread(reabrir, sessao, indices("apps"), indices("arquivos"), indices("abas"))
        except windows.NaoSuportado as erro:
            raise HTTPException(501, str(erro)) from None
        app.atividades.anotar({"ferramenta": "retomar", "argumentos": {"acao": "reabrir"}, "nivel": CONFIRMAR,
                               "situacao": "ok", "resumo": frase_reabertos(r), "canal": "texto"})
        return {"texto": frase_reabertos(r), **r}


def dados_holograma(app, tipo: str) -> dict | None:
    if tipo == "sentinela":
        return app.sentinela.dados_holograma()
    if tipo == "retomar":
        return dados_retomar(app.sessoes.anterior())
    return None


def diagnostico(app) -> list[dict]:
    s: Sentinela = app.sentinela
    itens = []
    if not s.cadastrado():
        itens.append({"nome": "Protocolo Sentinela", "ok": True, "detalhe": "sem rosto cadastrado: fotografa qualquer pessoa",
                      "dica": "Cadastre seu rosto em Ajustes para o Sentinela te reconhecer e desarmar sozinho"})
    else:
        itens.append({"nome": "Protocolo Sentinela", "ok": True,
                      "detalhe": ("ativo" if s.armado else "pronto") + (" · automático" if app.prefs.get("sentinela_auto") else ""),
                      "dica": ""})
    if not windows.WINDOWS:
        itens.append({"nome": "Casa Limpa e Onde eu parei", "ok": False, "detalhe": "só no Windows",
                      "dica": "Rode a Sexta-Feira no Windows"})
    else:
        itens.append({"nome": "Onde eu parei", "ok": True,
                      "detalhe": f"{len(app.sessoes.listar())} sessões anotadas", "dica": ""})
    return itens


def _ao_mudar_preferencias(app, mudou: dict) -> None:
    if "sentinela_auto" in mudou:
        app.sentinela._acordar.set()


def iniciar(app) -> None:
    app.prefs.ao_mudar(lambda mudou: _ao_mudar_preferencias(app, mudou))
    app.sentinela.iniciar()
    app.sessoes.iniciar()


def encerrar(app) -> None:
    app.sentinela.encerrar()
    app.sessoes.encerrar()
