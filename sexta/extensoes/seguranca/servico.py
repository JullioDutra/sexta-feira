"""O serviço de segurança (``app.seguranca``): analisa, revisa, guarda o histórico, ensina a memória,
mostra o holograma, consulta o VirusTotal (só o hash) e faz a revisão automática semanal."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from ...util.texto import normalizar
from . import arquivo, pc
from .arquivo import ErroAnalise

log = logging.getLogger(__name__)

MAX_HISTORICO = 50
SEMANA = timedelta(days=7)
ESPERA_INICIAL_S = 10 * 60   # a revisão automática não disputa a máquina com a subida da Sexta-Feira
CHECAR_S = 60 * 60
NOMES_RISCO = {"alto": "alto", "medio": "médio", "baixo": "baixo"}
VIRUSTOTAL_URL = "https://www.virustotal.com/api/v3/files/{hash}"
PASTAS_BUSCA = ("Downloads", "Desktop", "Documents", "Área de Trabalho", "Documentos", "")
_HASH = re.compile(r"^[0-9a-fA-F]{32}$|^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$")
_ULTIMO_DOWNLOAD = re.compile(r"^(?:o |a )?(?:ultimo|ultima) (?:download|arquivo baixado|coisa que (?:eu )?baixei|"
                              r"arquivo que (?:eu )?baixei)$")


def chave_virustotal() -> str:
    return os.environ.get("VIRUSTOTAL_API_KEY", "").strip()


def interpretar_virustotal(dados: dict) -> dict:
    """Resposta da API v3 (``/files/{hash}``) -> resumo."""
    atributos = (dados.get("data") or {}).get("attributes") or {}
    stats = atributos.get("last_analysis_stats") or {}
    maliciosos, suspeitos = int(stats.get("malicious") or 0), int(stats.get("suspicious") or 0)
    total = sum(int(v or 0) for k, v in stats.items() if k in ("malicious", "suspicious", "undetected", "harmless"))
    rotulo = ((atributos.get("popular_threat_classification") or {}).get("suggested_threat_label") or "")
    quando = atributos.get("last_analysis_date")
    return {"conhecido": True, "maliciosos": maliciosos, "suspeitos": suspeitos, "total": total, "rotulo": rotulo,
            "nome": atributos.get("meaningful_name") or "", "reputacao": atributos.get("reputation"),
            "analisado_em": datetime.fromtimestamp(quando).strftime("%d/%m/%Y") if quando else None}


def frase_virustotal(nome: str, vt: dict) -> str:
    if not vt.get("conhecido"):
        return (f"O VirusTotal não conhece {nome}: ninguém enviou esse arquivo antes. Isso não diz se é bom ou ruim, "
                f"só que é raro.")
    if vt["maliciosos"] >= 5:
        extra = f" (classificado como {vt['rotulo']})" if vt.get("rotulo") else ""
        return (f"No VirusTotal, {vt['maliciosos']} de {vt['total']} antivírus apontam {nome} como malicioso{extra}. "
                f"Eu apagaria esse arquivo.")
    if vt["maliciosos"] or vt["suspeitos"]:
        return (f"No VirusTotal, {vt['maliciosos'] + vt['suspeitos']} de {vt['total']} antivírus desconfiam de {nome}. "
                f"Poucos alertas costumam ser falso positivo, mas vale cautela.")
    return f"No VirusTotal, nenhum dos {vt['total']} antivírus acusou {nome}."


class Seguranca:
    def __init__(self, app, pasta: Path, coletor: pc.Coletor | None = None,
                 assinatura: Callable[[Path], dict] | None = None, http=None) -> None:
        self.app = app
        self.arquivo_historico = pasta / "analises.json"
        self.arquivo_estado = pasta / "seguranca.json"
        self.coletor = coletor
        self.assinatura = assinatura
        self.http = http                      # cliente httpx (os testes passam um com transporte simulado)
        self._lock = threading.Lock()
        self._historico: list[dict] = self._carregar(self.arquivo_historico, [])
        self._estado: dict = self._carregar(self.arquivo_estado, {})
        self._mostrando: dict | None = None
        self._rodando = False
        self._parar = threading.Event()

    # -- persistência ----------------------------------------------------------------------------------
    @staticmethod
    def _carregar(arquivo: Path, padrao):
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
            return dados if isinstance(dados, type(padrao)) else padrao
        except (OSError, json.JSONDecodeError):
            return padrao

    @staticmethod
    def _gravar(arquivo: Path, dados) -> None:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, arquivo)

    def historico(self) -> list[dict]:
        with self._lock:
            return list(self._historico)

    def resumo_historico(self) -> list[dict]:
        return [{"id": h["id"], "tipo": h["tipo"], "quando": h["quando"], "risco": h["risco"],
                 "titulo": h.get("arquivo") or "Revisão do PC", "assinatura": (h.get("assinatura") or {}).get("texto"),
                 "virustotal": h.get("virustotal")} for h in self.historico()]

    def obter(self, id_: str) -> dict | None:
        return next((h for h in self.historico() if h["id"] == id_), None)

    def _guardar(self, relatorio: dict) -> dict:
        relatorio["id"] = relatorio.get("id") or uuid.uuid4().hex[:12]
        with self._lock:
            self._historico = [relatorio] + [h for h in self._historico if h["id"] != relatorio["id"]]
            del self._historico[MAX_HISTORICO:]
            copia = list(self._historico)
        try:
            self._gravar(self.arquivo_historico, copia)
        except OSError as erro:
            log.warning("Não consegui salvar o histórico de análises: %s", erro)
        return relatorio

    def ultima_analise_de_arquivo(self) -> dict | None:
        return next((h for h in self.historico() if h["tipo"] == "arquivo"), None)

    def buscar(self, busca: str, limite: int = 5) -> list[dict]:
        termos = normalizar(busca or "").split()
        achados = []
        for h in self.historico():
            alvo = normalizar(" ".join(str(h.get(k) or "") for k in ("arquivo", "caminho", "descricao", "sha256", "risco")))
            if all(t in alvo for t in termos):
                achados.append(h)
            if len(achados) >= limite:
                break
        return achados

    # -- memória ------------------------------------------------------------------------------------
    def _aprender(self, texto: str, etiquetas: list[str]) -> None:
        memoria = getattr(self.app, "memoria", None)
        aprender = getattr(memoria, "aprender", None)
        if aprender is None:
            return
        try:
            aprender("conhecimento", texto, etiquetas=etiquetas, origem="seguranca")
        except Exception:  # noqa: BLE001 - memória nova ainda em construção: nunca derruba a análise
            log.exception("Não consegui guardar a análise na memória")

    def _aprender_arquivo(self, r: dict) -> None:
        quando = datetime.fromisoformat(r["quando"]).strftime("%d/%m/%Y %H:%M")
        assinatura = r.get("assinatura") or {}
        assinado = assinatura.get("texto") or "?"
        if assinatura.get("assinante"):
            assinado += f" (assinante: {assinatura['assinante']})"
        motivos = "; ".join([m["texto"] for m in r["motivos"] if m["peso"] > 0][:3]) or "nada suspeito"
        texto = (f"Análise de segurança do arquivo {r['arquivo']} em {quando}: {r['descricao']}. Assinatura digital: "
                 f"{assinado}. Risco {NOMES_RISCO[r['risco']]}. "
                 f"Motivos: {motivos}. SHA-256 {r['sha256']}. Caminho: {r['caminho']}.")
        etiquetas = ["seguranca", "analise_arquivo", f"arquivo:{r['arquivo']}", f"tipo:{r['categoria']}",
                     f"risco:{r['risco']}", "assinado" if assinatura.get("status") == "Valid" else "sem_assinatura_valida"]
        etiquetas += [f"tecnica:{t}" for t in r.get("tecnicas", [])]
        self._aprender(texto, etiquetas)

    def _aprender_pc(self, r: dict) -> None:
        quando = datetime.fromisoformat(r["quando"]).strftime("%d/%m/%Y %H:%M")
        altos = [i["titulo"] for i in r["itens"] if i["risco"] == "alto"]
        medios = [i["titulo"] for i in r["itens"] if i["risco"] == "medio"]
        texto = (f"Revisão de segurança do PC em {quando}: risco geral {r['risco']}. "
                 f"Pontos altos: {'; '.join(altos[:5]) or 'nenhum'}. Pontos médios: {'; '.join(medios[:5]) or 'nenhum'}.")
        self._aprender(texto, ["seguranca", "revisao_pc", f"risco:{r['risco']}"] +
                       [f"tecnica:{i['categoria']}" for i in r["itens"] if i["risco"] in ("alto", "medio")][:6])

    # -- holograma ----------------------------------------------------------------------------------
    def dados_holograma(self) -> dict:
        return {"atual": self._mostrando, "historico": self.resumo_historico(),
                "virustotal": bool(chave_virustotal()) and bool(self.app.prefs.get("seguranca_virustotal", True))}

    def mostrar(self, relatorio: dict | None, titulo: str | None = None) -> None:
        self._mostrando = relatorio
        try:
            self.app.hologramas.mostrar("seguranca", self.dados_holograma(), titulo=titulo)
        except Exception:  # noqa: BLE001 - sem HUD (testes antigos): a resposta falada basta
            log.debug("Holograma de segurança indisponível", exc_info=True)

    def mostrar_carregando(self, texto: str) -> None:
        self.mostrar({"tipo": "carregando", "texto": texto})

    # -- arquivos -----------------------------------------------------------------------------------
    def resolver_arquivo(self, texto: str) -> Path:
        """Caminho completo, "%USERPROFILE%\\...", "~/...", "o último download" ou só o nome (procurado em Downloads,
        Área de Trabalho e Documentos)."""
        bruto = (texto or "").strip().strip("\"'“”‘’").strip()
        if not bruto:
            raise ErroAnalise("Qual arquivo? Diga o nome ou o caminho completo.")
        casa = Path.home()
        if _ULTIMO_DOWNLOAD.match(normalizar(bruto)):
            downloads = casa / "Downloads"
            arquivos = [p for p in downloads.iterdir() if p.is_file() and not p.name.endswith((".crdownload", ".part",
                                                                                                ".tmp"))] \
                if downloads.is_dir() else []
            if not arquivos:
                raise ErroAnalise("Não encontrei nenhum arquivo na pasta Downloads.")
            return max(arquivos, key=lambda p: p.stat().st_mtime)
        expandido = Path(os.path.expandvars(os.path.expanduser(bruto)))
        if expandido.is_absolute():
            if expandido.exists():
                return expandido
            raise ErroAnalise(f"Não encontrei {expandido}.")
        relativo = casa / expandido
        if len(expandido.parts) > 1 and relativo.exists():
            return relativo
        return self._procurar_pelo_nome(expandido.name, casa)

    @staticmethod
    def _procurar_pelo_nome(nome: str, casa: Path) -> Path:
        alvo = nome.lower()
        candidatos: list[Path] = []
        for pasta in PASTAS_BUSCA:
            base = casa / pasta if pasta else casa
            if not base.is_dir():
                continue
            niveis = [base.iterdir()] if not pasta else [base.iterdir(), (q for p in base.iterdir() if p.is_dir()
                                                                         and not p.name.startswith(".")
                                                                         for q in _seguro_iterdir(p))]
            for nivel in niveis:
                for p in nivel:
                    try:
                        if p.is_file() and (p.name.lower() == alvo or p.stem.lower() == alvo):
                            candidatos.append(p)
                    except OSError:
                        continue
        if not candidatos:
            raise ErroAnalise(f"Não encontrei {nome} em Downloads, Área de Trabalho nem Documentos. "
                              "Diga o caminho completo.")
        return max(candidatos, key=lambda p: p.stat().st_mtime)

    def programa(self, nome: str) -> Path:
        """O executável de um programa aberto ("chrome") ou, com "janela_ativa", o da janela em primeiro plano."""
        import psutil

        if nome in ("janela_ativa", "esse", "este"):
            from ...habilidades import windows

            if not windows.WINDOWS:
                raise ErroAnalise("Só no Windows consigo saber qual programa está na tela.")
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
            try:
                exe = psutil.Process(pid.value).exe()
            except (psutil.Error, OSError):
                raise ErroAnalise("Não consegui ver qual programa está em primeiro plano.") from None
            return Path(exe)
        alvo = normalizar(nome).replace(" ", "").removesuffix("exe").removesuffix(".")
        achados = []
        for p in psutil.process_iter(["name", "exe"]):
            processo = (p.info.get("name") or "").lower().removesuffix(".exe")
            if p.info.get("exe") and alvo and (processo == alvo or (len(alvo) >= 4 and alvo in processo)):
                achados.append((processo != alvo, p.info["exe"]))
        if not achados:
            raise ErroAnalise(f"Não encontrei o programa {nome} aberto. Abra o programa ou diga o caminho do arquivo.")
        return Path(sorted(achados)[0][1])

    def analisar(self, caminho: Path) -> dict:
        r = arquivo.analisar(caminho, assinatura=self.assinatura)
        self._guardar(r)
        self._aprender_arquivo(r)
        self.mostrar(r, titulo=f"Segurança · {r['arquivo']}")
        return r

    # -- revisão do PC ------------------------------------------------------------------------------
    def revisar(self, partes: tuple[str, ...] = pc.PARTES, *, mostrar: bool = True) -> dict:
        from ...habilidades import windows

        if self.coletor is None and not windows.WINDOWS:
            raise ErroAnalise("A revisão de segurança do PC só funciona no Windows.")
        if mostrar:
            self.mostrar_carregando("Revisando a segurança do PC…")
        r = pc.revisar(self.coletor or pc.Coletor(), partes, pid_proprio=os.getpid())
        if set(partes) == set(pc.PARTES):
            self._guardar(r)
            self._aprender_pc(r)
        if mostrar:
            self.mostrar(r, titulo="Segurança · revisão do PC")
        return r

    def marcar_corrigido(self, acao: dict, novo_titulo: str) -> None:
        """Depois de uma correção, o item no holograma muda (sem precisar revisar tudo de novo)."""
        atual = self._mostrando
        if not atual or atual.get("tipo") != "pc":
            return
        for item in atual["itens"]:
            if item.get("acao") and all(item["acao"].get(k) == v for k, v in acao.items() if k != "acao"):
                item["risco"], item["titulo"] = "ok", novo_titulo
                inverso = {"desativar_inicializacao": "reativar_inicializacao", "reativar_inicializacao":
                           "desativar_inicializacao", "desativar_tarefa": "reativar_tarefa",
                           "reativar_tarefa": "desativar_tarefa"}.get(acao.get("acao"))
                item["acao"] = {**item["acao"], "acao": inverso} if inverso else None
        self.mostrar(atual)

    # -- VirusTotal ---------------------------------------------------------------------------------
    def virustotal(self, sha256: str) -> dict:
        import httpx

        chave = chave_virustotal()
        if not chave:
            raise ErroAnalise("Para consultar o VirusTotal, crie uma chave grátis em virustotal.com e coloque "
                              "VIRUSTOTAL_API_KEY no arquivo .env.")
        if not _HASH.match(sha256 or ""):
            raise ErroAnalise("Hash inválido.")
        cliente = self.http or httpx.Client(timeout=20)
        try:
            resposta = cliente.get(VIRUSTOTAL_URL.format(hash=sha256.lower()), headers={"x-apikey": chave})
        except httpx.HTTPError as erro:
            raise ErroAnalise(f"Não consegui falar com o VirusTotal: {erro}") from None
        finally:
            if self.http is None:
                cliente.close()
        if resposta.status_code == 404:
            return {"conhecido": False}
        if resposta.status_code in (401, 403):
            raise ErroAnalise("O VirusTotal recusou a chave. Confira VIRUSTOTAL_API_KEY no .env.")
        if resposta.status_code == 429:
            raise ErroAnalise("Passei do limite de consultas grátis do VirusTotal. Tente de novo em um minuto.")
        if resposta.status_code >= 400:
            raise ErroAnalise(f"O VirusTotal respondeu com erro {resposta.status_code}.")
        return interpretar_virustotal(resposta.json())

    def registrar_virustotal(self, sha256: str, vt: dict) -> None:
        """Guarda o resultado na análise do histórico (e na memória)."""
        with self._lock:
            alvos = [h for h in self._historico if h.get("sha256") == sha256]
            for h in alvos:
                h["virustotal"] = vt
            copia = list(self._historico)
        if alvos:
            self._gravar(self.arquivo_historico, copia)
            if self._mostrando and self._mostrando.get("sha256") == sha256:
                self._mostrando["virustotal"] = vt
                self.mostrar(self._mostrando)
        nome = alvos[0]["arquivo"] if alvos else sha256[:12]
        self._aprender(f"VirusTotal para {nome} (SHA-256 {sha256}): {frase_virustotal(nome, vt)}",
                       ["seguranca", "virustotal", f"arquivo:{nome}"])

    # -- revisão automática semanal -----------------------------------------------------------------
    def estado(self) -> dict:
        from ...habilidades import windows
        from . import pe

        return {"windows": windows.WINDOWS, "pefile": pe.pefile_disponivel(), "virustotal_configurado": bool(chave_virustotal()),
                "revisao_semanal": bool(self.app.prefs.get("seguranca_revisao_semanal", False)),
                "ultima_automatica": self._estado.get("ultima_automatica"),
                "analises": len(self.historico())}

    def revisao_automatica_vencida(self, agora: datetime | None = None) -> bool:
        if not self.app.prefs.get("seguranca_revisao_semanal", False):
            return False
        ultima = self._estado.get("ultima_automatica")
        if not ultima:
            return True
        try:
            return (agora or datetime.now()) - datetime.fromisoformat(ultima) >= SEMANA
        except ValueError:
            return True

    def revisao_automatica(self) -> dict | None:
        """Roda a revisão semanal sem abrir o holograma; avisa só se houver ponto importante."""
        if not self.revisao_automatica_vencida():
            return None
        try:
            r = self.revisar(mostrar=False)
        except ErroAnalise as erro:
            log.info("Revisão automática não rodou: %s", erro)
            return None
        self._estado["ultima_automatica"] = datetime.now().isoformat(timespec="seconds")
        try:
            self._gravar(self.arquivo_estado, self._estado)
        except OSError as erro:
            log.warning("Não consegui salvar o estado da revisão: %s", erro)
        if r["contagem"]["alto"]:
            self.app.barramento.publicar("aviso", nivel="erro",
                                         texto=f"Revisão semanal de segurança: {r['veredito']}")
        return r

    def iniciar(self) -> None:
        if self._rodando:
            return
        self._rodando = True
        threading.Thread(target=self._laco, name="seguranca-semanal", daemon=True).start()

    def _laco(self) -> None:
        if self._parar.wait(ESPERA_INICIAL_S):
            return
        while not self._parar.is_set():
            try:
                self.revisao_automatica()
            except Exception:  # noqa: BLE001 - a thread não pode morrer
                log.exception("Erro na revisão automática de segurança")
            if self._parar.wait(CHECAR_S):
                return

    def encerrar(self) -> None:
        self._parar.set()


def _seguro_iterdir(pasta: Path):
    try:
        yield from pasta.iterdir()
    except OSError:
        return
