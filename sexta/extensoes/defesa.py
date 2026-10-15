"""Extensão "defesa": vigilância contínua do PC, links suspeitos e segredos esquecidos nos projetos.

Tudo defensivo e local:

- **Vigilância** (preferência ``vigilancia_seguranca``): a cada ``vigilancia_minutos`` ela roda uma revisão leve
  (proteção, inicialização, tarefas agendadas e portas) usando a extensão ``seguranca`` e compara com a linha de base
  (``dados/vigilancia.json``). Item novo de risco médio/alto vira alerta (HUD, celular, memória; voz se for alto).
  "Pode ignorar" coloca os itens do último alerta na linha de base; "o que mudou no PC?" repete o último alerta.
- **Links:** "esse link é seguro?" (com o link no pedido ou copiado) — análise só local: domínio parecido com marca
  conhecida (troca de letras, punycode, subdomínio enganoso), encurtador, IP no lugar do domínio, TLD muito usado em
  golpe, http sem cadeado, @ no endereço. O link nunca é aberto.
- **Segredos nos projetos:** "procura senhas esquecidas no projeto X" — chaves de API, tokens e chaves privadas em
  arquivos de texto das pastas de projeto; o relatório mostra arquivo:linha com o segredo mascarado e lembra se o
  ``.env`` não está no ``.gitignore``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from ..util.texto import normalizar

log = logging.getLogger(__name__)

PREFERENCIAS = {"vigilancia_seguranca": True, "vigilancia_minutos": 15}
PARTES_VIGILANCIA = ("protecao", "inicializacao", "tarefas", "portas")

# -- links ----------------------------------------------------------------------------------------

MARCAS = ["itau", "bradesco", "santander", "caixa", "bancodobrasil", "bb", "nubank", "inter", "c6bank", "picpay",
          "mercadopago", "mercadolivre", "pagseguro", "paypal", "gov", "receita", "correios", "detran", "serasa",
          "netflix", "spotify", "amazon", "magazineluiza", "magalu", "americanas", "shopee", "aliexpress", "ifood",
          "uber", "whatsapp", "instagram", "facebook", "google", "gmail", "microsoft", "outlook", "apple", "icloud",
          "steam", "epicgames", "discord", "binance", "linkedin"]
DOMINIOS_OFICIAIS = {"bancodobrasil": "bb.com.br", "gov": "gov.br", "receita": "gov.br", "magalu": "magazineluiza.com.br"}
ENCURTADORES = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "cutt.ly", "rebrand.ly", "ow.ly", "shorturl.at",
                "encurtador.com.br", "tiny.cc", "s.id", "rb.gy"}
TLDS_SUSPEITOS = {"xyz", "top", "click", "online", "site", "live", "icu", "buzz", "monster", "rest", "cfd", "sbs",
                  "shop", "work", "support", "info", "zip", "mov"}
PALAVRAS_ISCA = ("login", "senha", "verifica", "atualiza", "seguranca", "confirm", "desbloq", "premio", "brinde",
                 "pix", "boleto", "fatura", "conta", "token", "acesso")


def _distancia(a: str, b: str) -> int:
    """Distância de edição (Levenshtein) — pequena entre marca e domínio = imitação."""
    if abs(len(a) - len(b)) > 2:
        return 99
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        atual = [i]
        for j, cb in enumerate(b, 1):
            atual.append(min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + (ca != cb)))
        anterior = atual
    return anterior[-1]


def _dominio_registrado(host: str) -> tuple[str, str]:
    """('mercadolivre', 'mercadolivre.com.br') a partir de 'www.mercadolivre.com.br'."""
    partes = host.split(".")
    if len(partes) >= 3 and partes[-1] == "br" and partes[-2] in ("com", "gov", "org", "net", "edu", "art", "app"):
        return partes[-3], ".".join(partes[-3:])
    if len(partes) >= 2:
        return partes[-2], ".".join(partes[-2:])
    return host, host


def analisar_link(url: str) -> dict:
    """Veredito (baixo/medio/alto) com os motivos. Não acessa o link."""
    url = (url or "").strip().strip("<>\"'")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "http://" + url
    partes = urlsplit(url)
    host = (partes.hostname or "").lower().rstrip(".")
    motivos: list[str] = []
    pontos = 0
    if not host:
        return {"url": url, "risco": "medio", "motivos": ["Não consegui ler o endereço."], "host": ""}
    if partes.scheme == "http":
        pontos += 1
        motivos.append("Não usa HTTPS (sem cadeado): nunca digite senha nesse site.")
    if "@" in partes.netloc:
        pontos += 3
        motivos.append("Tem @ no endereço: o que vem antes é enfeite, o site de verdade é o depois do @.")
    if re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host):
        pontos += 3
        motivos.append("Usa um número de IP no lugar do nome do site — típico de golpe.")
    if host.startswith("xn--") or ".xn--" in host:
        pontos += 3
        motivos.append("Usa letras de outros alfabetos disfarçadas (punycode) — pode imitar um site conhecido.")
    if host in ENCURTADORES:
        pontos += 1
        motivos.append("É um link encurtado: não dá para saber o destino sem abrir. Peça o link completo.")
    nome, registrado = _dominio_registrado(host)
    tld = host.rsplit(".", 1)[-1]
    if tld in TLDS_SUSPEITOS:
        pontos += 1
        motivos.append(f"Termina em .{tld}, muito usado em sites de golpe.")
    nome_limpo = re.sub(r"[^a-z0-9]", "", nome)
    for marca in MARCAS:
        oficial = DOMINIOS_OFICIAIS.get(marca)
        if nome_limpo == marca or (oficial and registrado == oficial):
            break  # é o próprio site da marca (ou o domínio oficial dela)
        sub = host[: -len(registrado)].rstrip(".")
        if len(marca) >= 4 and marca in re.sub(r"[^a-z0-9]", "", sub):
            pontos += 3
            motivos.append(f"Cita \"{marca}\" no começo, mas o site de verdade é {registrado}.")
            break
        if len(marca) >= 5 and (marca in nome_limpo or _distancia(nome_limpo, marca) <= (1 if len(marca) < 7 else 2)):
            pontos += 3
            motivos.append(f"O nome {registrado} imita \"{marca}\", mas não é o site oficial.")
            break
    caminho = normalizar(f"{partes.path} {partes.query}")
    iscas = [p for p in PALAVRAS_ISCA if p in caminho or p in host]
    if iscas and pontos:
        pontos += 1
        motivos.append(f"Fala de {', '.join(iscas[:3])} — isca comum para roubar dados.")
    if host.count("-") >= 3 or len(host) > 45:
        pontos += 1
        motivos.append("Endereço muito comprido ou cheio de hífens.")
    risco = "alto" if pontos >= 3 else "medio" if pontos >= 1 else "baixo"
    if not motivos:
        motivos.append("Nada suspeito no endereço. Isso não garante o conteúdo: desconfie se pedir senha ou Pix.")
    return {"url": url, "host": host, "dominio": registrado, "risco": risco, "motivos": motivos}


def frase_link(r: dict) -> str:
    inicio = {"alto": f"Cuidado: {r['host']} tem cara de golpe.", "medio": f"{r['host']} merece desconfiança.",
              "baixo": f"{r['host']} parece normal."}[r["risco"]]
    return f"{inicio} {r['motivos'][0]}"


# -- segredos ---------------------------------------------------------------------------------------

PADROES_SEGREDO = [
    ("chave da AWS", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("token do GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("chave do Google", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("chave da Stripe", re.compile(r"\b(sk|rk)_live_[0-9A-Za-z]{20,}\b")),
    ("token do Slack", re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b")),
    ("chave da Anthropic", re.compile(r"\bsk-ant-[0-9A-Za-z_\-]{20,}\b")),
    ("chave da OpenAI", re.compile(r"\bsk-(proj-)?[A-Za-z0-9]{32,}\b")),
    ("chave privada", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("token JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
]
_ATRIBUICAO = re.compile(r"(?i)\b(senha|password|passwd|pwd|secret|segredo|token|api[_-]?key|chave)\w*\s*[:=]\s*"
                         r"[\"']([^\"'\s]{8,})[\"']")
IGNORAR_PASTAS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".next", ".idea",
                  ".vscode", "target", "vendor", ".mypy_cache", ".pytest_cache", "coverage"}
EXTENSOES_TEXTO = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
                   ".txt", ".md", ".java", ".kt", ".cs", ".go", ".rb", ".php", ".sh", ".ps1", ".bat", ".xml",
                   ".properties", ".conf", ".sql", ".html", ".vue", ".swift", ".dart", ".rs", ".c", ".cpp", ".h"}
EXEMPLOS = re.compile(r"(?i)(exemplo|example|sample|dummy|fake|teste|test|placeholder|changeme|your[_-]?|xxx|\*\*\*|<.+>)")
MAX_ARQUIVO = 1_000_000
MAX_ARQUIVOS = 20_000


def _entropia(texto: str) -> float:
    if not texto:
        return 0.0
    contagem = {c: texto.count(c) for c in set(texto)}
    return -sum(n / len(texto) * math.log2(n / len(texto)) for n in contagem.values())


def mascarar(segredo: str) -> str:
    return segredo[:4] + "…" + segredo[-2:] if len(segredo) > 10 else "…"


def procurar_segredos(pasta: Path, limite: int = 200) -> dict:
    """Varre os arquivos de texto da pasta. Devolve achados com o segredo mascarado (nunca o valor inteiro)."""
    achados: list[dict] = []
    vistos = 0
    for raiz, pastas, arquivos in os.walk(pasta):
        pastas[:] = [p for p in pastas if p not in IGNORAR_PASTAS and not p.startswith(".") or p in (".github",)]
        for nome in arquivos:
            caminho = Path(raiz) / nome
            if caminho.suffix.lower() not in EXTENSOES_TEXTO and not nome.startswith(".env"):
                continue
            vistos += 1
            if vistos > MAX_ARQUIVOS or len(achados) >= limite:
                break
            try:
                if caminho.is_symlink() or caminho.stat().st_size > MAX_ARQUIVO:
                    continue
                linhas = caminho.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            relativo = str(caminho.relative_to(pasta))
            for n, linha in enumerate(linhas, 1):
                for tipo, padrao in PADROES_SEGREDO:
                    m = padrao.search(linha)
                    if m and not EXEMPLOS.search(linha):
                        achados.append({"arquivo": relativo, "linha": n, "tipo": tipo, "trecho": mascarar(m.group(0))})
                        break
                else:
                    m = _ATRIBUICAO.search(linha)
                    if m and _entropia(m.group(2)) >= 3.0 and not EXEMPLOS.search(m.group(2)):
                        achados.append({"arquivo": relativo, "linha": n, "tipo": f"{m.group(1).lower()} no código",
                                        "trecho": mascarar(m.group(2))})
    avisos = []
    if any(p.name.startswith(".env") and p.name != ".env.example" for p in pasta.glob(".env*")):
        gitignore = pasta / ".gitignore"
        conteudo = gitignore.read_text(encoding="utf-8", errors="ignore") if gitignore.exists() else ""
        if not re.search(r"(?m)^\s*/?\.env\b", conteudo):
            avisos.append("Existe um arquivo .env e ele não está no .gitignore: ele pode ir parar no GitHub.")
    return {"pasta": str(pasta), "arquivos": min(vistos, MAX_ARQUIVOS), "achados": achados, "avisos": avisos}


def texto_segredos(r: dict) -> str:
    linhas = [f"Pasta: {r['pasta']} ({r['arquivos']} arquivos de texto)", ""]
    for a in r["avisos"]:
        linhas.append(f"⚠ {a}")
    if r["achados"]:
        linhas.append(f"{len(r['achados'])} possível(is) segredo(s):")
        linhas += [f"• {a['arquivo']}:{a['linha']} — {a['tipo']} ({a['trecho']})" for a in r["achados"][:60]]
        linhas += ["", "O que fazer: tire o segredo do código (use variável de ambiente ou .env no .gitignore) e, se ele "
                   "já foi para o GitHub, troque a chave no serviço — apagar do histórico não basta."]
    else:
        linhas.append("Nenhum segredo encontrado.")
    return "\n".join(linhas)


# -- vigilância --------------------------------------------------------------------------------------

def _chave_item(item: dict) -> str:
    return f"{item.get('categoria', '')}|{item.get('id') or item.get('titulo', '')}"


class Vigilancia:
    def __init__(self, app, arquivo: Path) -> None:
        self.app = app
        self.arquivo = arquivo
        self._parar = threading.Event()
        self._lock = threading.Lock()
        try:
            self.estado = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.estado = {}
        self.estado.setdefault("base", [])
        self.ultimo_alerta: list[dict] = self.estado.get("ultimo_alerta", [])

    def _salvar(self) -> None:
        try:
            tmp = self.arquivo.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.estado, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.arquivo)
        except OSError as erro:
            log.warning("Não consegui salvar a vigilância: %s", erro)

    def verificar(self) -> list[dict]:
        """Uma passada: devolve os itens novos que merecem alerta (e já avisa)."""
        seguranca = getattr(self.app, "seguranca", None)
        if seguranca is None:
            return []
        relatorio = seguranca.revisar(PARTES_VIGILANCIA, mostrar=False)
        itens = [i for i in relatorio.get("itens", []) if isinstance(i, dict)]
        with self._lock:
            base = set(self.estado["base"])
            primeira = not self.estado.get("pronta")
            novos = [i for i in itens if _chave_item(i) not in base]
            self.estado["base"] = sorted(base | {_chave_item(i) for i in itens if primeira or i.get("risco") == "baixo"})
            self.estado["pronta"] = True
            self.estado["ultima"] = time.time()
            if primeira:  # a primeira passada só aprende como o PC é
                self._salvar()
                return []
            alertas = [i for i in novos if i.get("risco") in ("medio", "alto")]
            if alertas:
                self.ultimo_alerta = alertas
                self.estado["ultimo_alerta"] = alertas
            self._salvar()
        if alertas:
            self._avisar(alertas)
        return alertas

    def _avisar(self, alertas: list[dict]) -> None:
        titulos = "; ".join(a.get("titulo", "") for a in alertas[:3])
        texto = f"Segurança: mudança no PC — {titulos}."
        self.app.barramento.publicar("aviso", nivel="erro", texto=texto)
        try:
            from ..habilidades.notificacoes import notificar

            notificar(self.app, texto, titulo="Vigilância")
        except Exception:  # noqa: BLE001
            log.debug("Notificação da vigilância falhou", exc_info=True)
        memoria = getattr(self.app, "memoria", None)
        if memoria is not None:
            try:
                for a in alertas[:5]:
                    memoria.aprender("conhecimento", f"Vigilância ({time.strftime('%d/%m %H:%M')}): {a.get('titulo')}",
                                     etiquetas=["seguranca", "vigilancia", str(a.get("categoria", ""))], origem="vigilancia")
            except Exception:  # noqa: BLE001
                log.debug("Memória não guardou o alerta", exc_info=True)
        if any(a.get("risco") == "alto" for a in alertas) and not self.app.fala.falando_ou_na_fila():
            self.app.fala.falar(f"Atenção: {alertas[0].get('titulo')}. Diga \"o que mudou no PC\" para ver, "
                                f"ou \"pode ignorar\" se foi você.")

    def ignorar(self) -> str:
        if not self.ultimo_alerta:
            return "Não há alerta para ignorar."
        with self._lock:
            self.estado["base"] = sorted(set(self.estado["base"]) | {_chave_item(a) for a in self.ultimo_alerta})
            n = len(self.ultimo_alerta)
            self.ultimo_alerta = []
            self.estado["ultimo_alerta"] = []
            self._salvar()
        return f"Tudo bem, marquei {n} item{'s' if n > 1 else ''} como conhecido{'s' if n > 1 else ''}."

    def descrever(self) -> str:
        if not self.ultimo_alerta:
            ultima = self.estado.get("ultima")
            quando = f" A última verificação foi às {time.strftime('%H:%M', time.localtime(ultima))}." if ultima else ""
            return "Nada de novo desde a última verificação." + quando
        partes = []
        for a in self.ultimo_alerta[:4]:
            partes.append(f"{a.get('titulo')}" + (f" — {a['sugestao']}" if a.get("sugestao") else ""))
        return "Mudanças: " + "; ".join(partes) + "."

    def iniciar(self) -> None:
        threading.Thread(target=self._laco, name="vigilancia", daemon=True).start()

    def parar(self) -> None:
        self._parar.set()

    def _laco(self) -> None:
        from ..habilidades import windows

        if not windows.WINDOWS or self._parar.wait(180):
            return
        while not self._parar.is_set():
            if self.app.prefs.get("vigilancia_seguranca", True):
                try:
                    self.verificar()
                except Exception as erro:  # noqa: BLE001
                    log.info("Vigilância falhou: %s", erro)
            minutos = max(5, int(self.app.prefs.get("vigilancia_minutos") or 15))
            if self._parar.wait(minutos * 60):
                return


# -- ganchos --------------------------------------------------------------------------------------

def instalar(app) -> None:
    app.vigilancia = Vigilancia(app, app.cfg.dados / "vigilancia.json")


def iniciar(app) -> None:
    app.vigilancia.iniciar()


def encerrar(app) -> None:
    app.vigilancia.parar()


def _acao_vigilancia(app, valor, ctx, variaveis) -> None:
    app.prefs.atualizar({"vigilancia_seguranca": str(valor).strip().lower() in ("ligar", "true", "sim", "1")})


ACOES_PROTOCOLO = {
    "vigilancia": {"rotulo": "Vigilância de segurança", "entrada": "opcoes", "opcoes": ["ligar", "desligar"],
                   "dica": "liga ou desliga a vigilância contínua", "executar": _acao_vigilancia},
}


def _pastas_projeto(app) -> list[Path]:
    try:
        from .agentes_ferramentas import pastas_de_projetos

        return pastas_de_projetos(app)
    except Exception:  # noqa: BLE001
        return []


def resolver_projeto(app, nome: str) -> Path | None:
    nome = (nome or "").strip()
    if nome and (Path(nome).expanduser().is_dir()):
        return Path(nome).expanduser().resolve()
    alvo = normalizar(nome)
    for base in _pastas_projeto(app):
        if normalizar(base.name) == alvo:
            return base
        try:
            for filho in base.iterdir():
                if filho.is_dir() and normalizar(filho.name) == alvo:
                    return filho
        except OSError:
            continue
    return None


def _link_do_pedido(original: str | None) -> str | None:
    m = re.search(r"(https?://\S+|www\.\S+|\b[\w-]+(\.[\w-]+)+\.[a-z]{2,}(/\S*)?)", original or "", re.I)
    return m.group(0).rstrip(".,;)") if m else None


def verificar_link(app, texto: str | None) -> dict:
    url = _link_do_pedido(texto)
    if not url:
        try:
            from ..habilidades import area_transferencia

            url = _link_do_pedido(area_transferencia.ler())
        except Exception:  # noqa: BLE001
            url = None
    if not url:
        return {"ok": False, "resumo": "Não achei um link no pedido nem no que você copiou."}
    r = analisar_link(url)
    app.hologramas.mostrar("texto", {"texto": f"{r['url']}\n\nRisco: {r['risco']}\n\n" + "\n".join(f"• {m}" for m in r["motivos"])},
                           titulo="Segurança · link")
    return {"ok": True, "resumo": frase_link(r), "risco": r["risco"], "motivos": r["motivos"]}


def varrer_projeto(app, nome: str, canal: str = "texto") -> dict:
    pasta = resolver_projeto(app, nome)
    if pasta is None:
        dica = ", ".join(p.name for p in _pastas_projeto(app)[:4])
        return {"ok": False, "resumo": f"Não achei o projeto {nome}." + (f" Pastas de projeto: {dica}." if dica else
                                                                          " Configure as pastas de projeto em Ajustes → Agentes.")}
    r = procurar_segredos(pasta)
    app.hologramas.mostrar("texto", {"texto": texto_segredos(r)}, titulo=f"Segurança · segredos em {pasta.name}")
    memoria = getattr(app, "memoria", None)
    if memoria is not None:
        try:
            memoria.aprender("conhecimento", f"Varredura de segredos em {pasta.name}: {len(r['achados'])} achado(s)",
                             etiquetas=["seguranca", "segredos", pasta.name], origem="defesa")
        except Exception:  # noqa: BLE001
            pass
    n = len(r["achados"])
    if not n and not r["avisos"]:
        return {"ok": True, "resumo": f"Nenhuma senha ou chave esquecida no projeto {pasta.name}."}
    resumo = (f"Achei {n} possível{'is' if n != 1 else ''} segredo{'s' if n != 1 else ''} no projeto {pasta.name}"
              if n else f"Nenhum segredo no código de {pasta.name}")
    if r["avisos"]:
        resumo += ", e o .env não está no .gitignore"
    return {"ok": True, "resumo": resumo + ". Detalhes na tela."}


_LINK = re.compile(r"(esse|este|o|aquele) (link|site|endereco)( que eu copiei)? (e |eh |parece )?(seguro|confiavel|golpe|"
                   r"phishing|perigoso)|^(verifica|analisa|checa) (esse |o |este )?(link|site|endereco)|"
                   r"(e|eh) golpe esse link|esse link (e|eh) golpe")
_SEGREDOS = re.compile(r"^(procura|busca|verifica|varre|checa) (por )?(senhas|segredos|chaves|tokens|credenciais)"
                       r"( esquecidas| esquecidos| vazadas| expostas| expostos)? (no|do|nos) (projeto|repositorio) (?P<nome>.+)$")
_IGNORAR = re.compile(r"^(pode ignorar|ignora( esse| o)? alerta|fui eu|foi eu que (instalei|mudei))$")
_MUDOU = re.compile(r"^(o que mudou no (pc|computador)|qual (foi )?o alerta( de seguranca)?|o que foi o alerta)$")
_VIG = re.compile(r"^(liga|ativa|desliga|desativa) a vigilancia( de seguranca)?$")


def atalho(t, ctx, rodar, original):
    app = ctx.app
    if _LINK.search(t):
        return lambda: verificar_link(app, original)["resumo"]
    if m := _SEGREDOS.match(t):
        nome = m.group("nome")
        if original:
            achado = re.search(r"(?:projeto|reposit[óo]rio)\s+(.+?)\s*[?.!]*$", original, re.I)
            nome = achado.group(1) if achado else nome
        return lambda: varrer_projeto(app, nome, ctx.canal)["resumo"]
    if _IGNORAR.match(t) and app.vigilancia.ultimo_alerta:
        return lambda: app.vigilancia.ignorar()
    if _MUDOU.match(t):
        return lambda: app.vigilancia.descrever()
    if m := _VIG.match(t):
        ligar = m.group(1) in ("liga", "ativa")

        def mudar() -> str:
            app.prefs.atualizar({"vigilancia_seguranca": ligar})
            return "Vigilância de segurança ligada." if ligar else "Vigilância de segurança desligada."
        return mudar
    return None


def registrar(app, registro) -> None:
    from ..cerebro.ferramentas import P

    @registro.ferramenta(
        "seguranca_link",
        "Diz se um link parece golpe/phishing (análise local do endereço; o link não é aberto). Sem link, usa o que "
        "o usuário copiou.",
        direta=True,
        link=P("string", "O link (ou texto com o link)."),
    )
    def seguranca_link(ctx, link: str | None = None):
        return verificar_link(app, link)

    @registro.ferramenta(
        "seguranca_segredos",
        "Procura senhas, chaves de API, tokens e chaves privadas esquecidas no código de um projeto do usuário "
        "(pastas de projeto) e mostra arquivo:linha com o segredo mascarado.",
        direta=True,
        projeto=P("string", "Nome da pasta do projeto ou caminho completo.", obrigatorio=True),
    )
    def seguranca_segredos(ctx, projeto: str):
        return varrer_projeto(app, projeto, ctx.canal)

    @registro.ferramenta(
        "seguranca_vigilancia",
        "Vigilância contínua do PC: status (o que mudou), ignorar (o último alerta foi o usuário), ligar, desligar, "
        "verificar_agora.",
        direta=True,
        acao=P("string", "Ação.", enum=["status", "ignorar", "ligar", "desligar", "verificar_agora"], obrigatorio=True),
    )
    def seguranca_vigilancia(ctx, acao: str):
        v = app.vigilancia
        if acao == "ignorar":
            return {"ok": True, "resumo": v.ignorar()}
        if acao in ("ligar", "desligar"):
            app.prefs.atualizar({"vigilancia_seguranca": acao == "ligar"})
            return {"ok": True, "resumo": f"Vigilância {'ligada' if acao == 'ligar' else 'desligada'}."}
        if acao == "verificar_agora":
            try:
                novos = v.verificar()
            except Exception as erro:  # noqa: BLE001
                return {"ok": False, "resumo": f"Não consegui verificar: {erro}"}
            return {"ok": True, "resumo": v.descrever() if novos else "Verifiquei: nada de novo."}
        return {"ok": True, "resumo": v.descrever()}


def diagnostico(app) -> list[dict]:
    ligada = bool(app.prefs.get("vigilancia_seguranca", True))
    ultima = app.vigilancia.estado.get("ultima")
    return [{"nome": "Vigilância de segurança", "ok": True,
             "detalhe": ("ligada" if ligada else "desligada") + (
                 f", última verificação {time.strftime('%d/%m %H:%M', time.localtime(ultima))}" if ultima else ""),
             "dica": "" if ligada else "Diga \"liga a vigilância\"."}]
