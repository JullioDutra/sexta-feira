"""Extensão "ciberseguranca": auditoria de segurança adaptativa dos SEUS ativos.

Defensiva e só de inspeção. Nunca explora, invade nem ataca: olha, mede e relata o que está exposto, e explica
como se proteger. Junta num fluxo só o que já existe (revisão do PC e análise de programas da extensão `seguranca`,
engenharia reversa com o REA pelo agente) com duas inspeções novas:

- **Site:** certificado TLS (validade, emissor), cabeçalhos de segurança (HSTS, CSP, X-Frame-Options…), cookies,
  redirecionamento para HTTPS, `security.txt`, servidor exposto — tudo com requisições normais, como um navegador.
- **Rede da casa/escritório:** inventário da SUA rede local (só faixas privadas): quais aparelhos estão ligados,
  nome e fabricante (pelo MAC), e quais serviços conhecidos cada um deixa abertos (SSH, HTTP, SMB, RDP, banco de
  dados…), apontando os inseguros (Telnet, FTP, porta de banco exposta). É a visão da "superfície de ataque" da sua
  própria rede, para você fechar o que não devia estar aberto.

**Autorização obrigatória:** toda inspeção exige que o alvo esteja na sua lista de escopos autorizados; se não
estiver, ela pergunta e só segue com o seu "sim" (e aí guarda o escopo). Endereços públicos de rede (fora das faixas
privadas) são recusados — ela audita a sua rede, não a dos outros.

**Adaptativa:** cada auditoria vira uma ficha na memória (`conhecimento`), e a próxima auditoria do mesmo alvo começa
comparando com a anterior ("o que mudou desde a última vez") e reaproveitando o que já aprendeu.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..util.texto import normalizar

log = logging.getLogger(__name__)

HOLOGRAMAS = {"ciberseguranca": "Auditoria de segurança"}
PREFERENCIAS = {"ciber_rede_max_hosts": 256, "ciber_porta_timeout_ms": 500}

CONFIRMAR = 2
TIMEOUT_HTTP = 12.0

# Cabeçalhos de segurança que um site deveria mandar (nome -> por que importa)
CABECALHOS = {
    "strict-transport-security": "Força HTTPS (HSTS) e evita downgrade para HTTP.",
    "content-security-policy": "Limita de onde scripts/recursos carregam (barra muito XSS).",
    "x-frame-options": "Impede que o site seja colocado dentro de um iframe (clickjacking).",
    "x-content-type-options": "Impede o navegador de 'adivinhar' o tipo de conteúdo (nosniff).",
    "referrer-policy": "Controla o que vaza no cabeçalho Referer.",
    "permissions-policy": "Restringe câmera, microfone, geolocalização etc.",
}

# Serviços conhecidos, para dizer o que um aparelho da rede expõe (identificação, não exploração)
PORTAS = {
    21: ("FTP", "inseguro"), 22: ("SSH", None), 23: ("Telnet", "inseguro"), 25: ("SMTP", None),
    53: ("DNS", None), 80: ("HTTP", None), 110: ("POP3", "inseguro"), 139: ("NetBIOS", "atencao"),
    143: ("IMAP", None), 443: ("HTTPS", None), 445: ("SMB", "atencao"), 587: ("SMTP", None),
    631: ("Impressora (IPP)", None), 1433: ("SQL Server", "atencao"), 1900: ("UPnP", "atencao"),
    3000: ("App web", None), 3306: ("MySQL", "atencao"), 3389: ("Área de Trabalho Remota", "atencao"),
    5432: ("PostgreSQL", "atencao"), 5900: ("VNC", "atencao"), 6379: ("Redis", "atencao"),
    8080: ("HTTP alternativo", None), 8443: ("HTTPS alternativo", None), 9200: ("Elasticsearch", "atencao"),
    27017: ("MongoDB", "atencao"),
}
PORTAS_RELEVANTES = tuple(PORTAS)
ORDEM_RISCO = {"alto": 0, "medio": 1, "baixo": 2, "ok": 3}


def agora_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ----------------------------------------------------------------- escopos autorizados

def _alvo_normalizado(alvo: str) -> str:
    alvo = (alvo or "").strip().strip("/")
    alvo = re.sub(r"^[a-z]+://", "", alvo, flags=re.I)
    return alvo.split("/")[0].split("@")[-1].lower()


class Escopos:
    """A lista do que o usuário autorizou auditar (domínios, 'este pc', 'minha rede')."""

    def __init__(self, arquivo: Path) -> None:
        self.arquivo = arquivo
        self._lock = threading.Lock()
        try:
            self.lista: list[dict] = json.loads(arquivo.read_text(encoding="utf-8")).get("escopos", [])
        except (OSError, ValueError):
            self.lista = []

    def _salvar(self) -> None:
        try:
            tmp = self.arquivo.with_suffix(".tmp")
            tmp.write_text(json.dumps({"escopos": self.lista}, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.arquivo)
        except OSError as erro:
            log.warning("Não consegui salvar os escopos: %s", erro)

    def autorizado(self, tipo: str, alvo: str) -> bool:
        alvo = _alvo_normalizado(alvo) if tipo == "site" else normalizar(alvo)
        with self._lock:
            for e in self.lista:
                if e["tipo"] != tipo:
                    continue
                if tipo == "site" and (e["alvo"] == alvo or alvo.endswith("." + e["alvo"])):
                    return True
                if tipo in ("pc", "rede") and e["alvo"] == alvo:
                    return True
        return False

    def autorizar(self, tipo: str, alvo: str) -> None:
        chave = _alvo_normalizado(alvo) if tipo == "site" else normalizar(alvo)
        with self._lock:
            if not any(e["tipo"] == tipo and e["alvo"] == chave for e in self.lista):
                self.lista.append({"tipo": tipo, "alvo": chave, "rotulo": alvo, "quando": agora_iso()})
                self._salvar()

    def remover(self, alvo: str) -> bool:
        chave = normalizar(alvo)
        with self._lock:
            antes = len(self.lista)
            self.lista = [e for e in self.lista if normalizar(e["alvo"]) != chave and normalizar(e["rotulo"]) != chave]
            mudou = len(self.lista) != antes
            if mudou:
                self._salvar()
        return mudou


# ----------------------------------------------------------------- site (só leitura)

def analisar_tls(host: str, porta: int = 443, conectar=None) -> dict:
    """Pega o certificado via handshake TLS (sem enviar nenhum dado da aplicação)."""
    conectar = conectar or _tls_real
    try:
        cert, versao, cifra = conectar(host, porta)
    except Exception as erro:  # noqa: BLE001
        return {"ok": False, "erro": str(erro)}
    depois = cert.get("notAfter")
    dias = None
    if depois:
        try:
            venc = datetime.strptime(depois, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            dias = (venc - datetime.now(timezone.utc)).days
        except ValueError:
            pass
    emissor = dict(x[0] for x in cert.get("issuer", []))
    return {"ok": True, "versao": versao, "cifra": (cifra or [None])[0] if isinstance(cifra, (list, tuple)) else cifra,
            "emissor": emissor.get("organizationName") or emissor.get("commonName", ""),
            "expira_em": depois, "dias_para_expirar": dias}


def _tls_real(host: str, porta: int):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, porta), timeout=TIMEOUT_HTTP) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            return tls.getpeercert(), tls.version(), tls.cipher()


def avaliar_site(url: str, resposta: dict, tls: dict) -> dict:
    """Monta o relatório do site a partir da resposta HTTP e do TLS (funções puras, fáceis de testar)."""
    cabecalhos = {k.lower(): v for k, v in (resposta.get("headers") or {}).items()}
    itens: list[dict] = []
    final = resposta.get("url_final") or url
    https = final.lower().startswith("https://")
    if not https:
        itens.append({"risco": "alto", "titulo": "Site sem HTTPS",
                      "detalhe": "O tráfego vai em texto puro; qualquer um na rede pode ler senhas e dados.",
                      "sugestao": "Instale um certificado (Let's Encrypt é grátis) e force o redirecionamento para HTTPS."})
    if tls.get("ok"):
        dias = tls.get("dias_para_expirar")
        if dias is not None and dias < 0:
            itens.append({"risco": "alto", "titulo": "Certificado TLS vencido",
                          "detalhe": f"Venceu há {-dias} dia(s).", "sugestao": "Renove o certificado agora."})
        elif dias is not None and dias < 15:
            itens.append({"risco": "medio", "titulo": "Certificado TLS perto de vencer",
                          "detalhe": f"Faltam {dias} dia(s).", "sugestao": "Renove e, se der, ative a renovação automática."})
        if tls.get("versao") in ("TLSv1", "TLSv1.1", "SSLv3"):
            itens.append({"risco": "medio", "titulo": f"Protocolo TLS antigo ({tls['versao']})",
                          "detalhe": "Versões antigas têm fraquezas conhecidas.",
                          "sugestao": "Deixe só TLS 1.2 e 1.3 no servidor."})
    elif https:
        itens.append({"risco": "medio", "titulo": "Não consegui validar o certificado TLS",
                      "detalhe": tls.get("erro", ""), "sugestao": "Confira se o certificado é válido e confiável."})
    if https:
        for nome, porque in CABECALHOS.items():
            if nome not in cabecalhos:
                risco = "medio" if nome in ("strict-transport-security", "content-security-policy") else "baixo"
                itens.append({"risco": risco, "titulo": f"Falta o cabeçalho {nome}", "detalhe": porque,
                              "sugestao": f"Adicione o cabeçalho {nome} nas respostas do servidor."})
    servidor = cabecalhos.get("server", "")
    if re.search(r"\d+\.\d+", servidor):
        itens.append({"risco": "baixo", "titulo": "Servidor expõe a versão",
                      "detalhe": f"Cabeçalho Server: {servidor}.",
                      "sugestao": "Esconda a versão para não entregar pistas (ServerTokens Prod / server_tokens off)."})
    cookies = resposta.get("set_cookie") or []
    inseguros = [c for c in cookies if "httponly" not in c.lower() or ("secure" not in c.lower() and https)]
    if inseguros:
        itens.append({"risco": "baixo", "titulo": "Cookies sem Secure/HttpOnly",
                      "detalhe": f"{len(inseguros)} cookie(s) sem as proteções.",
                      "sugestao": "Marque os cookies de sessão como Secure e HttpOnly (e SameSite)."})
    itens.sort(key=lambda i: ORDEM_RISCO.get(i["risco"], 9))
    risco = next((i["risco"] for i in itens if i["risco"] in ("alto", "medio")), "baixo")
    return {"tipo": "site", "alvo": url, "url_final": final, "tls": tls, "servidor": servidor,
            "itens": itens, "risco": risco, "quando": agora_iso()}


# ----------------------------------------------------------------- rede local (só privada)

def rede_do_ip(ip: str, prefixo: int = 24) -> ipaddress.IPv4Network | None:
    try:
        endereco = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if endereco.version != 4 or not endereco.is_private:
        return None
    return ipaddress.ip_network(f"{ip}/{prefixo}", strict=False)


def e_privado(alvo: str) -> bool:
    try:
        return ipaddress.ip_address(alvo).is_private
    except ValueError:
        rede = _rede(alvo)
        return rede is not None and rede.is_private


def _rede(alvo: str) -> ipaddress.IPv4Network | None:
    try:
        return ipaddress.ip_network(alvo, strict=False)
    except ValueError:
        return None


def porta_aberta(host: str, porta: int, timeout: float) -> str | None:
    """Conecta e lê um banner curto (identificação de serviço). Devolve o banner, '' se abriu sem banner, ou None."""
    try:
        with socket.create_connection((host, porta), timeout=timeout) as sock:
            sock.settimeout(timeout)
            try:
                return (sock.recv(64) or b"").decode("latin-1", "replace").strip()
            except (socket.timeout, OSError):
                return ""
    except (OSError, ValueError):
        return None


def avaliar_host(ip: str, nome: str, abertas: dict[int, str]) -> dict:
    servicos = []
    itens = []
    for porta, banner in sorted(abertas.items()):
        rotulo, aviso = PORTAS.get(porta, (f"porta {porta}", None))
        servicos.append({"porta": porta, "servico": rotulo, "banner": banner[:60]})
        if aviso == "inseguro":
            itens.append({"risco": "alto", "titulo": f"{rotulo} aberto em {nome or ip}",
                          "detalhe": "Protocolo sem criptografia (dados e senha em texto puro).",
                          "sugestao": f"Desative o {rotulo} e use uma alternativa segura (ex.: SSH no lugar de Telnet)."})
        elif aviso == "atencao":
            itens.append({"risco": "medio", "titulo": f"{rotulo} exposto em {nome or ip}",
                          "detalhe": "Serviço que normalmente não deveria ficar aberto na rede.",
                          "sugestao": f"Confirme se precisa do {rotulo} acessível; se não, bloqueie no firewall/roteador."})
    return {"ip": ip, "nome": nome, "servicos": servicos, "itens": itens}


# ----------------------------------------------------------------- serviço

class Ciberseguranca:
    def __init__(self, app, pasta: Path, http=None, tls=None) -> None:
        self.app = app
        self.escopos = Escopos(pasta / "ciberseguranca.json")
        self.arquivo_hist = pasta / "ciber_auditorias.json"
        self._http = http                 # cliente httpx (os testes passam um simulado)
        self._tls = tls or _tls_real
        self._lock = threading.Lock()
        try:
            self.historico: list[dict] = json.loads(self.arquivo_hist.read_text(encoding="utf-8")).get("itens", [])
        except (OSError, ValueError):
            self.historico = []

    # -- http -------------------------------------------------------------------------------
    def _cliente(self):
        if self._http is not None:
            return self._http
        import httpx

        return httpx.Client(timeout=TIMEOUT_HTTP, follow_redirects=True,
                            headers={"User-Agent": "Sexta-Feira/auditoria (verificacao de seguranca autorizada)"})

    def _buscar(self, url: str) -> dict:
        cliente = self._cliente()
        try:
            r = cliente.get(url)
            set_cookie = r.headers.get_list("set-cookie") if hasattr(r.headers, "get_list") else \
                [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"] if hasattr(r.headers, "multi_items") \
                else ([r.headers["set-cookie"]] if "set-cookie" in r.headers else [])
            return {"ok": True, "status": r.status_code, "url_final": str(r.url),
                    "headers": dict(r.headers), "set_cookie": set_cookie}
        except Exception as erro:  # noqa: BLE001
            return {"ok": False, "erro": str(erro)}
        finally:
            if self._http is None:
                try:
                    cliente.close()
                except Exception:  # noqa: BLE001
                    pass

    # -- auditoria de site ------------------------------------------------------------------
    def auditar_site(self, alvo: str) -> dict:
        host = _alvo_normalizado(alvo)
        url = alvo if re.match(r"^https?://", alvo, re.I) else f"https://{host}"
        resposta = self._buscar(url)
        if not resposta.get("ok") and url.startswith("https://"):
            resposta = self._buscar("http://" + host)
        if not resposta.get("ok"):
            return {"tipo": "site", "alvo": host, "erro": f"Não consegui acessar o site: {resposta.get('erro')}",
                    "itens": [], "risco": "ok", "quando": agora_iso()}
        tls = analisar_tls(host, conectar=self._tls) if (resposta.get("url_final") or url).startswith("https") \
            else {"ok": False, "erro": "sem HTTPS"}
        relatorio = avaliar_site(url, resposta, tls)
        return self._finalizar(relatorio, f"site {host}")

    # -- auditoria da rede ------------------------------------------------------------------
    def enderecos_locais(self) -> list[str]:
        ips = []
        try:
            import psutil

            for enderecos in psutil.net_if_addrs().values():
                for e in enderecos:
                    if getattr(e, "family", None) == socket.AF_INET and ipaddress.ip_address(e.address).is_private:
                        ips.append(e.address)
        except Exception:  # noqa: BLE001
            pass
        return ips

    def auditar_rede(self, alvo: str | None = None) -> dict:
        timeout = max(0.1, int(self.app.prefs.get("ciber_porta_timeout_ms") or 500) / 1000)
        max_hosts = max(1, int(self.app.prefs.get("ciber_rede_max_hosts") or 256))
        redes: list[ipaddress.IPv4Network] = []
        if alvo and alvo.strip() not in ("minha rede", "rede", "local"):
            r = _rede(alvo) if "/" in alvo else rede_do_ip(alvo.strip())
            if r is None or not r.is_private:
                return {"tipo": "rede", "erro": "Só audito faixas de IP privadas (a sua rede local).", "itens": [],
                        "risco": "ok", "quando": agora_iso()}
            redes = [r]
        else:
            redes = [rede_do_ip(ip) for ip in self.enderecos_locais()]
            redes = [r for r in redes if r is not None]
        if not redes:
            return {"tipo": "rede", "erro": "Não achei uma rede local para auditar (isso só funciona no seu PC).",
                    "itens": [], "risco": "ok", "quando": agora_iso()}
        enderecos: list[str] = []
        for rede in redes:
            for ip in rede.hosts():
                enderecos.append(str(ip))
                if len(enderecos) >= max_hosts:
                    break
        hosts = self._varrer(enderecos, timeout)
        itens = [i for h in hosts for i in h["itens"]]
        itens.sort(key=lambda i: ORDEM_RISCO.get(i["risco"], 9))
        risco = next((i["risco"] for i in itens if i["risco"] in ("alto", "medio")), "baixo" if hosts else "ok")
        relatorio = {"tipo": "rede", "alvo": ", ".join(str(r) for r in redes), "aparelhos": hosts,
                     "itens": itens, "risco": risco, "quando": agora_iso()}
        return self._finalizar(relatorio, f"rede {relatorio['alvo']}")

    def _varrer(self, enderecos: list[str], timeout: float) -> list[dict]:
        import concurrent.futures as cf

        nomes = _nomes_arp()
        hosts: list[dict] = []

        def checar(ip: str) -> dict | None:
            abertas: dict[int, str] = {}
            for porta in PORTAS_RELEVANTES:
                banner = porta_aberta(ip, porta, timeout)
                if banner is not None:
                    abertas[porta] = banner
            if not abertas:
                return None
            nome = nomes.get(ip) or _nome_reverso(ip)
            return avaliar_host(ip, nome, abertas)

        with cf.ThreadPoolExecutor(max_workers=64) as pool:
            for resultado in pool.map(checar, enderecos):
                if resultado is not None:
                    hosts.append(resultado)
        return sorted(hosts, key=lambda h: tuple(int(x) for x in h["ip"].split(".") if x.isdigit()))

    # -- histórico, memória, holograma ------------------------------------------------------
    def _finalizar(self, relatorio: dict, rotulo: str) -> dict:
        anterior = self.ultimo(relatorio["tipo"], relatorio.get("alvo", ""))
        relatorio["mudancas"] = _comparar(anterior, relatorio) if anterior else []
        relatorio["id"] = f"c{int(time.time() * 1000) % 10**10}"
        with self._lock:
            self.historico.insert(0, _resumir(relatorio))
            self.historico = self.historico[:50]
            try:
                tmp = self.arquivo_hist.with_suffix(".tmp")
                tmp.write_text(json.dumps({"itens": self.historico}, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.arquivo_hist)
            except OSError:
                pass
        self._aprender(relatorio, rotulo)
        return relatorio

    def ultimo(self, tipo: str, alvo: str) -> dict | None:
        alvo = normalizar(alvo)
        return next((h for h in self.historico if h["tipo"] == tipo and normalizar(h.get("alvo", "")) == alvo), None)

    def _aprender(self, relatorio: dict, rotulo: str) -> None:
        memoria = getattr(self.app, "memoria", None)
        if memoria is None:
            return
        altos = [i["titulo"] for i in relatorio["itens"] if i["risco"] == "alto"]
        resumo = (f"Auditoria de {rotulo} ({relatorio['risco']})"
                  + (f": {', '.join(altos[:4])}" if altos else ": nada grave"))
        try:
            memoria.aprender("conhecimento", resumo, etiquetas=["ciberseguranca", relatorio["tipo"]],
                             origem="ciberseguranca")
        except Exception:  # noqa: BLE001
            log.debug("Memória não guardou a auditoria", exc_info=True)

    def mostrar(self, relatorio: dict, titulo: str) -> None:
        try:
            self.app.hologramas.mostrar("ciberseguranca", relatorio, titulo=titulo)
        except Exception:  # noqa: BLE001
            log.debug("Holograma de auditoria indisponível", exc_info=True)


def _comparar(antes: dict, agora: dict) -> list[str]:
    def chaves(r):
        return {i["titulo"] for i in r.get("itens", [])}

    novas = chaves(agora) - chaves(antes)
    sumiram = chaves(antes) - chaves(agora)
    mudancas = [f"novo: {t}" for t in sorted(novas)] + [f"resolvido: {t}" for t in sorted(sumiram)]
    return mudancas[:10]


def _resumir(relatorio: dict) -> dict:
    return {"id": relatorio["id"], "tipo": relatorio["tipo"], "alvo": relatorio.get("alvo", ""),
            "risco": relatorio["risco"], "quando": relatorio["quando"],
            "itens": [{k: i.get(k) for k in ("risco", "titulo", "detalhe", "sugestao")} for i in relatorio["itens"]],
            "mudancas": relatorio.get("mudancas", [])}


def _nomes_arp() -> dict[str, str]:
    """Nome/fabricante por IP a partir da tabela ARP do sistema (best-effort, cross-plataforma)."""
    import subprocess

    from ..habilidades import windows

    nomes: dict[str, str] = {}
    try:
        flags = windows.SEM_JANELA if getattr(windows, "WINDOWS", False) else 0
        saida = subprocess.run(["arp", "-a"], capture_output=True, timeout=5, creationflags=flags).stdout.decode(
            "latin-1", "replace")
    except Exception:  # noqa: BLE001
        return nomes
    for linha in saida.splitlines():
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)\D+([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})", linha)
        if m:
            nomes[m.group(1)] = m.group(2).replace("-", ":").lower()
    return nomes


def _nome_reverso(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except (OSError, socket.herror):
        return ""


# ----------------------------------------------------------------- ganchos da extensão

def instalar(app) -> None:
    app.ciberseguranca = Ciberseguranca(app, app.cfg.dados)


def _texto_relatorio(r: dict) -> str:
    if r.get("erro"):
        return r["erro"]
    linhas = [f"Alvo: {r.get('alvo', '')}", f"Risco geral: {r['risco']}", ""]
    if r["tipo"] == "rede":
        linhas.append(f"{len(r.get('aparelhos', []))} aparelho(s) na rede:")
        for h in r.get("aparelhos", [])[:20]:
            servicos = ", ".join(f"{s['servico']}({s['porta']})" for s in h["servicos"])
            linhas.append(f"• {h['ip']} {h.get('nome') or ''} — {servicos}")
        linhas.append("")
    for i in r["itens"][:30]:
        linhas.append(f"[{i['risco']}] {i['titulo']} — {i.get('detalhe', '')}")
        if i.get("sugestao"):
            linhas.append(f"    ↳ {i['sugestao']}")
    if r.get("mudancas"):
        linhas += ["", "Desde a última auditoria:"] + [f"• {m}" for m in r["mudancas"]]
    if not r["itens"]:
        linhas.append("Nada de grave encontrado.")
    return "\n".join(linhas)


def _frase(r: dict) -> str:
    if r.get("erro"):
        return r["erro"]
    altos = sum(1 for i in r["itens"] if i["risco"] == "alto")
    medios = sum(1 for i in r["itens"] if i["risco"] == "medio")
    onde = "no site" if r["tipo"] == "site" else "na rede" if r["tipo"] == "rede" else ""
    if not altos and not medios:
        base = f"Auditei {onde} e não achei nada grave."
    else:
        partes = []
        if altos:
            partes.append(f"{altos} ponto{'s' if altos > 1 else ''} de risco alto")
        if medios:
            partes.append(f"{medios} de risco médio")
        base = f"Encontrei {onde} " + " e ".join(partes) + "."
        primeiro = next(i for i in r["itens"] if i["risco"] in ("alto", "medio"))
        base += f" O principal: {primeiro['titulo']}."
    if r.get("mudancas"):
        base += f" {len(r['mudancas'])} mudança(s) desde a última vez."
    return base + " Detalhes na tela."


def _nivel_site(app):
    def nivel(args: dict) -> int:
        alvo = args.get("alvo") or ""
        return 1 if app.ciberseguranca.escopos.autorizado("site", alvo) else CONFIRMAR
    return nivel


def _nivel_rede(app):
    def nivel(args: dict) -> int:
        return 1 if app.ciberseguranca.escopos.autorizado("rede", "minha rede") else CONFIRMAR
    return nivel


def registrar(app, registro) -> None:
    from ..cerebro.ferramentas import P

    ciber: Ciberseguranca = app.ciberseguranca

    @registro.ferramenta(
        "ciberseguranca_site",
        "Auditoria de segurança de um site (defensiva, só leitura: certificado TLS, cabeçalhos de segurança, cookies, "
        "redirecionamento para HTTPS, servidor exposto). Use para 'verifica a segurança do meu site X'. Só para sites "
        "do usuário ou que ele tem autorização para auditar; a confirmação é pedida sozinha.",
        direta=True, nivel=_nivel_site(app),
        descrever=lambda a: f"auditar a segurança do site {_alvo_normalizado(a.get('alvo', ''))} — confirma que é seu "
                            f"ou que você tem autorização",
        alvo=P("string", "O endereço do site (ex.: meusite.com.br).", obrigatorio=True),
    )
    def ciberseguranca_site(ctx, alvo: str):
        ciber.escopos.autorizar("site", alvo)  # chegou aqui = autorizado (ou confirmado agora)
        ciber.mostrar(_carregando(), "Auditoria · site")
        r = ciber.auditar_site(alvo)
        ciber.mostrar(r, f"Auditoria · {_alvo_normalizado(alvo)}")
        return {"ok": not r.get("erro"), "resumo": _frase(r), "risco": r["risco"]}

    @registro.ferramenta(
        "ciberseguranca_rede",
        "Inventário de segurança da REDE LOCAL do usuário (só faixas privadas): quais aparelhos estão ligados e que "
        "serviços conhecidos cada um expõe (SSH, HTTP, SMB, RDP, bancos de dados…), apontando os inseguros. Defensivo, "
        "só identificação. Use para 'verifica a minha rede', 'o que está exposto na minha rede'. A confirmação é "
        "pedida sozinha; endereços públicos são recusados.",
        direta=True, nivel=_nivel_rede(app),
        descrever=lambda a: "auditar a sua rede local (inventário dos aparelhos e serviços expostos) — confirma que a "
                            "rede é sua",
        alvo=P("string", "Faixa ou IP da sua rede (padrão: a rede detectada). Ex.: 192.168.0.0/24."),
    )
    def ciberseguranca_rede(ctx, alvo: str | None = None):
        if alvo and not (alvo.strip() in ("minha rede", "rede", "local") or e_privado(alvo.strip())):
            return {"ok": False, "resumo": "Só audito a sua rede local (faixas de IP privadas), não redes públicas."}
        ciber.escopos.autorizar("rede", "minha rede")
        ciber.mostrar(_carregando(), "Auditoria · rede")
        r = ciber.auditar_rede(alvo)
        ciber.mostrar(r, "Auditoria · rede local")
        return {"ok": not r.get("erro"), "resumo": _frase(r), "risco": r["risco"]}

    @registro.ferramenta(
        "ciberseguranca_escopos",
        "Lista, autoriza ou remove os alvos que você autorizou auditar (sites e a sua rede).",
        direta=True,
        acao=P("string", "Ação.", enum=["listar", "autorizar", "remover"], obrigatorio=True),
        tipo=P("string", "Para autorizar: site ou rede.", enum=["site", "rede"]),
        alvo=P("string", "O site ou a rede."),
    )
    def ciberseguranca_escopos(ctx, acao: str, tipo: str | None = None, alvo: str | None = None):
        if acao == "listar":
            lista = ciber.escopos.lista
            return {"ok": True, "resumo": ("Você autorizou: " + ", ".join(e["rotulo"] for e in lista) + ".") if lista
                    else "Você ainda não autorizou nenhum alvo."}
        if not alvo:
            return {"ok": False, "resumo": "Qual alvo?"}
        if acao == "autorizar":
            ciber.escopos.autorizar(tipo or "site", alvo)
            return {"ok": True, "resumo": f"Autorizado: {alvo}."}
        return {"ok": ciber.escopos.remover(alvo), "resumo": f"Removido: {alvo}."}


def _carregando() -> dict:
    return {"tipo": "carregando", "alvo": "", "itens": [], "risco": "ok", "carregando": True}


_SITE = re.compile(r"\b(verifica|analisa|audita|checa|testa|olha) (a )?(seguranca|seguranc[ao] d[eo]|vulnerab\w*) "
                   r"d[eo] (meu |nosso )?site\b|seguranca d[eo] (meu |nosso )?site\b")
_REDE = re.compile(r"\b(verifica|analisa|audita|checa|olha|revisa) (a )?(minha |nossa )?(seguranca d[ae] )?rede"
                   r"( interna| local| wifi| wi-fi| de casa)?\b|o que (esta|ta) exposto n[ao] (minha |nossa )?rede\b")
_AUTORIZAR = re.compile(r"^(autoriza|pode auditar|libera) (o site |a rede |o )?(.+?)( para auditoria| na seguranca)?$")
_ESCOPOS = re.compile(r"^(o que|quais sites?|quais alvos) (eu )?(autorizei|liberei|voce pode auditar)$")
_LINK = re.compile(r"(https?://\S+|\b[a-z0-9-]+(\.[a-z0-9-]+)+\.[a-z]{2,}\b)", re.I)


def atalho(t: str, ctx, rodar, original):
    app = ctx.app
    if _SITE.search(t):
        m = _LINK.search(original or "")
        if m:
            return rodar("ciberseguranca_site", {"alvo": m.group(0).rstrip(".,")})
        return lambda: "Qual é o endereço do site? Diga, por exemplo, 'verifica a segurança do meusite.com.br'."
    if _REDE.search(t):
        m = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?)\b", original or "")
        if m and not e_privado(m.group(1)):  # IP público: recusa antes de qualquer pergunta ou varredura
            return lambda: "Só audito a sua rede local (faixas de IP privadas), não redes públicas."
        return rodar("ciberseguranca_rede", {"alvo": m.group(1)} if m else {})
    if _ESCOPOS.match(t):
        return rodar("ciberseguranca_escopos", {"acao": "listar"})
    if m := _AUTORIZAR.match(t):
        alvo = m.group(3).strip()
        link = _LINK.search(original or "")
        tipo = "rede" if "rede" in t else "site"
        return rodar("ciberseguranca_escopos",
                     {"acao": "autorizar", "tipo": tipo, "alvo": link.group(0) if link and tipo == "site" else alvo})
    return None


def dados_holograma(app, tipo: str) -> dict | None:
    if tipo != "ciberseguranca":
        return None
    hist = app.ciberseguranca.historico
    return hist[0] if hist else {"tipo": "vazio", "itens": [], "risco": "ok",
                                 "dica": "Diga 'verifica a segurança do meu site' ou 'audita a minha rede'."}


def rotas(api, app, autenticado, so_pc) -> None:
    from fastapi import Depends

    @api.get("/api/ciberseguranca")
    def estado(_=Depends(autenticado)):
        ciber: Ciberseguranca = app.ciberseguranca
        return {"escopos": ciber.escopos.lista, "historico": ciber.historico[:20]}


def diagnostico(app) -> list[dict]:
    n = len(app.ciberseguranca.escopos.lista)
    return [{"nome": "Cibersegurança (auditoria)", "ok": True,
             "detalhe": f"{n} alvo(s) autorizado(s)" if n else "nenhum alvo autorizado ainda",
             "dica": "Auditoria defensiva: só sites/redes seus. Diga 'verifica a segurança do meu site X'."}]
