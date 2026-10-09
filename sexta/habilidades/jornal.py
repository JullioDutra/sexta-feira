"""Central de notícias ("Jornal"): fontes configuráveis, agrupamento, temas com alerta e briefing.

- Fontes em ``config/noticias.yaml`` (RSS/Atom, Google Notícias, Hacker News, GitHub em alta).
- A mesma notícia publicada por várias fontes vira um item só ("3 fontes"), e as repetidas somem.
- "Seus temas": "me avisa quando sair notícia de RTX 60" — a cada 15 min ela procura e avisa
  por voz, no HUD e no celular.
- Salvas para depois, leitura da matéria (resumida pela IA) e o briefing matinal de até 2 minutos.
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx
import yaml

from ..util.texto import normalizar
from .noticias import BASE, PARAMS, TOPICOS, ha_quanto

log = logging.getLogger(__name__)

FONTES_PADRAO: dict[str, list[dict[str, str]]] = {
    "brasil": [
        {"nome": "Google Notícias", "url": "google:brasil"},
        {"nome": "g1", "url": "https://g1.globo.com/rss/g1/"},
    ],
    "tecnologia": [
        {"nome": "Tecnoblog", "url": "https://tecnoblog.net/feed/"},
        {"nome": "Canaltech", "url": "https://canaltech.com.br/rss/"},
        {"nome": "Olhar Digital", "url": "https://olhardigital.com.br/feed/"},
        {"nome": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
        {"nome": "Hacker News", "url": "hackernews:"},
        {"nome": "GitHub em alta", "url": "github:trending"},
    ],
}
ABAS = ["destaques", "brasil", "tecnologia", "temas", "salvas"]
VAZIAS = {"a", "o", "as", "os", "de", "do", "da", "dos", "das", "e", "em", "no", "na", "nos", "nas", "um", "uma",
          "para", "por", "com", "que", "se", "ao", "the", "of", "to", "in", "and", "for", "on", "is", "with", "apos",
          "sobre", "como", "mais", "diz", "vai", "ser", "tem", "seu", "sua"}
CACHE_S = 600
INTERVALO_TEMAS_S = 15 * 60
NS = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/"}


class ErroJornal(Exception):
    pass


# -- leitura de feeds -------------------------------------------------------------------

def _limpar_html(texto: str, limite: int = 320) -> str:
    texto = re.sub(r"<[^>]+>", " ", html.unescape(texto or ""))
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto if len(texto) <= limite else texto[: limite - 1].rsplit(" ", 1)[0] + "…"


def _data(texto: str | None) -> datetime | None:
    if not texto:
        return None
    texto = texto.strip()
    try:
        return parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        pass
    try:
        data = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        return data if data.tzinfo else data.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def interpretar_feed(xml: str | bytes, fonte: str, limite: int = 15) -> list[dict[str, Any]]:
    """RSS 2.0 ou Atom -> [{titulo, link, fonte, publicado, resumo}]."""
    raiz = ET.fromstring(xml)
    itens: list[dict[str, Any]] = []
    entradas = list(raiz.iter("item")) or raiz.findall("atom:entry", NS) or list(raiz.iter("{%s}entry" % NS["atom"]))
    for e in entradas:
        if e.tag == "item":
            titulo = e.findtext("title") or ""
            link = (e.findtext("link") or "").strip()
            resumo = e.findtext("description") or ""
            publicado = _data(e.findtext("pubDate"))
            fonte_item = (e.findtext("source") or "").strip() or fonte
        else:
            titulo = e.findtext("atom:title", default="", namespaces=NS)
            link_el = e.find("atom:link[@rel='alternate']", NS)
            if link_el is None:  # (um Element sem filhos é "falso": não dá para usar `or` aqui)
                link_el = e.find("atom:link", NS)
            link = (link_el.get("href") if link_el is not None else "") or ""
            resumo = e.findtext("atom:summary", default="", namespaces=NS) or e.findtext("atom:content", default="", namespaces=NS)
            publicado = _data(e.findtext("atom:published", namespaces=NS) or e.findtext("atom:updated", namespaces=NS))
            fonte_item = fonte
        titulo = _limpar_html(titulo, 300)
        if fonte_item and titulo.endswith(f" - {fonte_item}"):  # Google Notícias põe a fonte no título
            titulo = titulo[: -len(fonte_item) - 3].strip()
        if not titulo:
            continue
        itens.append({"titulo": titulo, "link": link, "fonte": fonte_item, "publicado": publicado,
                      "resumo": _limpar_html(resumo)})
        if len(itens) >= limite:
            break
    return itens


# -- agrupamento ----------------------------------------------------------------------------

def _palavras(titulo: str) -> set[str]:
    return {p for p in normalizar(titulo).split() if len(p) > 2 and p not in VAZIAS}


def agrupar(itens: list[dict[str, Any]], limiar: float = 0.5) -> list[dict[str, Any]]:
    """Junta a mesma notícia vinda de fontes diferentes e ordena por relevância.

    Relevância = quantas fontes deram a notícia, com um bônus para as mais recentes.
    """
    grupos: list[dict[str, Any]] = []
    for item in itens:
        palavras = _palavras(item["titulo"])
        if not palavras:
            continue
        melhor, nota = None, 0.0
        for g in grupos:
            comum = len(palavras & g["_palavras"])
            similaridade = comum / max(1, min(len(palavras), len(g["_palavras"])))
            if comum >= 3 and similaridade > nota:
                melhor, nota = g, similaridade
        if melhor is not None and nota >= limiar:
            if item["fonte"] not in melhor["fontes"]:
                melhor["fontes"].append(item["fonte"])
            melhor["_palavras"] |= palavras
            if (item["publicado"] or datetime.min.replace(tzinfo=timezone.utc)) > (
                    melhor["publicado"] or datetime.min.replace(tzinfo=timezone.utc)):
                melhor["publicado"] = item["publicado"]
            if not melhor["resumo"] and item.get("resumo"):
                melhor["resumo"] = item["resumo"]
            continue
        grupos.append({**item, "fontes": [item["fonte"]], "_palavras": set(palavras)})
    agora = datetime.now(timezone.utc)

    def relevancia(g: dict) -> float:
        horas = (agora - g["publicado"]).total_seconds() / 3600 if g["publicado"] else 24
        return len(g["fontes"]) * 2 + max(0.0, 1.5 - horas / 12) + g.get("_peso", 0)

    grupos.sort(key=relevancia, reverse=True)
    return grupos


def para_holograma(item: dict[str, Any]) -> dict[str, Any]:
    publicado = item.get("publicado")
    if isinstance(publicado, str):
        publicado = _data(publicado)
    return {"id": item.get("id") or _id(item), "titulo": item["titulo"], "link": item.get("link", ""),
            "fontes": item.get("fontes") or [item.get("fonte", "")], "quando": ha_quanto(publicado),
            "publicado": publicado.isoformat() if publicado else None, "resumo": item.get("resumo", ""),
            "tema": item.get("tema")}


def _id(item: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha1((item.get("link") or item["titulo"]).encode("utf-8")).hexdigest()[:12]


# -- texto da matéria ------------------------------------------------------------------------

class _Paragrafos(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paragrafos: list[str] = []
        self._dentro = 0
        self._ignorar = 0
        self._atual: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "aside", "form"):
            self._ignorar += 1
        elif tag == "p":
            self._dentro += 1
            self._atual = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "aside", "form"):
            self._ignorar = max(0, self._ignorar - 1)
        elif tag == "p" and self._dentro:
            self._dentro -= 1
            texto = re.sub(r"\s+", " ", "".join(self._atual)).strip()
            if len(texto) >= 60:
                self.paragrafos.append(texto)

    def handle_data(self, data):
        if self._dentro and not self._ignorar:
            self._atual.append(data)


def extrair_texto(pagina: str, limite: int = 6000) -> str:
    leitor = _Paragrafos()
    try:
        leitor.feed(pagina)
    except Exception:  # noqa: BLE001 - HTML quebrado: usa o que deu para ler
        pass
    return "\n".join(leitor.paragrafos)[:limite]


# -- o serviço -------------------------------------------------------------------------------

class Jornal:
    def __init__(self, app, arquivo_config: Path, pasta_dados: Path, http: httpx.Client | None = None) -> None:
        self.app = app
        self.arquivo_config = arquivo_config
        self.arquivo_temas = pasta_dados / "temas.json"
        self.arquivo_salvas = pasta_dados / "noticias_salvas.json"
        self.http = http or httpx.Client(timeout=10.0, follow_redirects=True,
                                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Sexta-Feira/1.0"})
        self.fontes: dict[str, list[dict[str, str]]] = {k: list(v) for k, v in FONTES_PADRAO.items()}
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._lock = threading.Lock()
        self._rodando = False
        self.ultimas: dict[str, list[dict]] = {}  # aba -> itens mostrados (para "lê a segunda")
        self.recarregar()

    # -- configuração e arquivos ------------------------------------------------------------
    def recarregar(self) -> None:
        if not self.arquivo_config.exists():
            return
        try:
            dados = yaml.safe_load(self.arquivo_config.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as erro:
            log.error("Erro lendo %s: %s", self.arquivo_config.name, erro)
            return
        fontes = {}
        for categoria, lista in (dados.get("fontes") or {}).items():
            itens = []
            for f in lista or []:
                if isinstance(f, dict) and f.get("url"):
                    itens.append({"nome": str(f.get("nome") or f["url"]), "url": str(f["url"])})
                elif isinstance(f, dict) and len(f) == 1:  # formato curto: - Tecnoblog: https://...
                    nome, url = next(iter(f.items()))
                    itens.append({"nome": str(nome), "url": str(url)})
            fontes[normalizar(str(categoria))] = itens
        if fontes:
            self.fontes = fontes

    def _ler_json(self, arquivo: Path, padrao):
        try:
            return json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return padrao

    def _gravar_json(self, arquivo: Path, dados) -> None:
        tmp = arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(arquivo)

    # -- coleta --------------------------------------------------------------------------------
    def _coletar_fonte(self, fonte: dict[str, str]) -> list[dict[str, Any]]:
        url = fonte["url"]
        with self._lock:
            em_cache = self._cache.get(url)
            if em_cache and time.time() - em_cache[0] < CACHE_S:
                return em_cache[1]
        try:
            if url.startswith("google:"):
                categoria = url.split(":", 1)[1]
                endereco = f"{BASE}/headlines/section/topic/{TOPICOS[categoria]}?{PARAMS}" if categoria in TOPICOS \
                    else f"{BASE}/search?q={quote_plus(categoria + ' when:1d')}&{PARAMS}"
                itens = interpretar_feed(self.http.get(endereco).raise_for_status().content, "")
            elif url.startswith("hackernews:"):
                itens = self._hacker_news()
            elif url.startswith("github:"):
                itens = self._github()
            else:
                itens = interpretar_feed(self.http.get(url).raise_for_status().content, fonte["nome"])
        except (httpx.HTTPError, ET.ParseError, ValueError, KeyError) as erro:
            log.warning("Fonte %s indisponível: %s", fonte["nome"], erro)
            return []
        with self._lock:
            self._cache[url] = (time.time(), itens)
        return itens

    def _hacker_news(self, quantidade: int = 8) -> list[dict[str, Any]]:
        base = "https://hacker-news.firebaseio.com/v0"
        ids = self.http.get(f"{base}/topstories.json").raise_for_status().json()[:quantidade]

        def item(i):
            d = self.http.get(f"{base}/item/{i}.json").raise_for_status().json() or {}
            return {"titulo": d.get("title", ""), "link": d.get("url") or f"https://news.ycombinator.com/item?id={i}",
                    "fonte": "Hacker News", "resumo": f"{d.get('score', 0)} pontos, {d.get('descendants', 0)} comentários",
                    "publicado": datetime.fromtimestamp(d.get("time", 0), timezone.utc) if d.get("time") else None}

        with ThreadPoolExecutor(max_workers=8) as pool:
            return [i for i in pool.map(item, ids) if i["titulo"]]

    def _github(self, quantidade: int = 6) -> list[dict[str, Any]]:
        desde = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        r = self.http.get("https://api.github.com/search/repositories",
                          params={"q": f"created:>{desde}", "sort": "stars", "order": "desc", "per_page": quantidade},
                          headers={"Accept": "application/vnd.github+json"}).raise_for_status().json()
        return [{"titulo": f"{repo['full_name']}: {repo.get('description') or 'sem descrição'}",
                 "link": repo["html_url"], "fonte": "GitHub em alta",
                 "resumo": f"{repo.get('stargazers_count', 0)} estrelas, {repo.get('language') or 'linguagem não informada'}",
                 "publicado": _data(repo.get("created_at")), "_peso": 0.5} for repo in r.get("items", [])]

    def coletar(self, categoria: str) -> list[dict[str, Any]]:
        fontes = self.fontes.get(categoria, [])
        if not fontes:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(fontes))) as pool:
            listas = list(pool.map(self._coletar_fonte, fontes))
        # intercala as fontes para nenhuma dominar o topo
        itens = [i for lista in listas for i in lista]
        return agrupar(itens)

    def buscar_tema(self, tema: str) -> list[dict[str, Any]]:
        endereco = f"{BASE}/search?q={quote_plus(tema + ' when:2d')}&{PARAMS}"
        try:
            itens = interpretar_feed(self.http.get(endereco).raise_for_status().content, "", limite=10)
        except (httpx.HTTPError, ET.ParseError) as erro:
            log.warning("Busca do tema %s falhou: %s", tema, erro)
            itens = []
        palavras = _palavras(tema)
        for categoria in self.fontes:  # também procura nos feeds já baixados
            for lista_cache in (self._cache.get(f["url"], (0, []))[1] for f in self.fontes[categoria]):
                for i in lista_cache:
                    if palavras and palavras <= _palavras(i["titulo"] + " " + i.get("resumo", "")):
                        itens.append(i)
        return [{**g, "tema": tema} for g in agrupar(itens)]

    # -- abas do holograma -----------------------------------------------------------------
    def abas(self) -> dict[str, list[dict[str, Any]]]:
        brasil = self.coletar("brasil")[:12]
        tecnologia = self.coletar("tecnologia")[:12]
        outras = [g for c in self.fontes if c not in ("brasil", "tecnologia") for g in self.coletar(c)[:6]]
        destaques = agrupar([*brasil[:8], *tecnologia[:8], *outras])[:10]
        temas = []
        for t in self.temas():
            temas += self.buscar_tema(t["tema"])[:4]
        resultado = {"destaques": destaques, "brasil": brasil, "tecnologia": tecnologia, "temas": temas,
                     "salvas": self.salvas()}
        self.ultimas = resultado
        return resultado

    def dados_holograma(self, aba: str = "destaques") -> dict[str, Any]:
        abas = self.abas()
        return {"aba": aba if aba in ABAS else "destaques",
                "abas": {k: [para_holograma(i) for i in v] for k, v in abas.items()},
                "temas": [t["tema"] for t in self.temas()],
                "atualizado": datetime.now().strftime("%H:%M")}

    def por_id(self, id_: str) -> dict[str, Any] | None:
        for lista in self.ultimas.values():
            for item in lista:
                if (item.get("id") or _id(item)) == id_:
                    return item
        return None

    def posicao(self, item: dict[str, Any]) -> tuple[str, int]:
        for aba in ABAS:
            lista = self.ultimas.get(aba) or []
            if item in lista:
                return aba, lista.index(item) + 1
        return "destaques", 1

    def item(self, aba: str, numero: int) -> dict[str, Any] | None:
        lista = self.ultimas.get(aba) or self.abas().get(aba) or []
        return lista[numero - 1] if 0 < numero <= len(lista) else None

    # -- salvas --------------------------------------------------------------------------------
    def salvas(self) -> list[dict[str, Any]]:
        return self._ler_json(self.arquivo_salvas, [])

    def salvar(self, item: dict[str, Any]) -> bool:
        salvas = self.salvas()
        chave = item.get("link") or item["titulo"]
        if any((s.get("link") or s["titulo"]) == chave for s in salvas):
            return False
        salvas.insert(0, {**para_holograma(item), "salvo_em": datetime.now().isoformat(timespec="minutes")})
        self._gravar_json(self.arquivo_salvas, salvas[:100])
        return True

    def remover_salva(self, link_ou_id: str) -> bool:
        salvas = self.salvas()
        restantes = [s for s in salvas if link_ou_id not in (s.get("link"), s.get("id"))]
        self._gravar_json(self.arquivo_salvas, restantes)
        return len(restantes) != len(salvas)

    # -- temas ---------------------------------------------------------------------------------
    def temas(self) -> list[dict[str, Any]]:
        return self._ler_json(self.arquivo_temas, [])

    def adicionar_tema(self, tema: str) -> bool:
        tema = re.sub(r"\s+", " ", tema).strip(" .!?")
        temas = self.temas()
        if not tema or any(normalizar(t["tema"]) == normalizar(tema) for t in temas):
            return False
        # o que já saiu até agora conta como visto: o alerta é só para o que vier depois
        vistos = [i.get("link") or i["titulo"] for i in self.buscar_tema(tema)]
        temas.append({"tema": tema, "criado": datetime.now().isoformat(timespec="minutes"), "vistos": vistos[-200:]})
        self._gravar_json(self.arquivo_temas, temas)
        return True

    def remover_tema(self, tema: str) -> list[str]:
        alvo = normalizar(tema)
        temas = self.temas()
        removidos = [t["tema"] for t in temas if alvo and (alvo in normalizar(t["tema"]) or normalizar(t["tema"]) in alvo)]
        self._gravar_json(self.arquivo_temas, [t for t in temas if t["tema"] not in removidos])
        return removidos

    def verificar_temas(self) -> list[tuple[str, dict[str, Any]]]:
        """Procura novidades dos temas e devolve [(tema, notícia nova)] — já marcadas como vistas."""
        temas = self.temas()
        novidades = []
        for t in temas:
            vistos = set(t.get("vistos", []))
            for item in self.buscar_tema(t["tema"]):
                chave = item.get("link") or item["titulo"]
                if chave in vistos:
                    continue
                vistos.add(chave)
                t.setdefault("vistos", []).append(chave)
                novidades.append((t["tema"], item))
            t["vistos"] = t.get("vistos", [])[-200:]
        if temas:
            self._gravar_json(self.arquivo_temas, temas)
        return novidades

    def iniciar(self) -> None:
        self._rodando = True
        threading.Thread(target=self._laco_temas, name="temas-noticias", daemon=True).start()

    def parar(self) -> None:
        self._rodando = False

    def _laco_temas(self) -> None:
        time.sleep(60)  # deixa a inicialização terminar
        while self._rodando:
            try:
                if self.temas():
                    self._avisar(self.verificar_temas())
            except Exception:  # noqa: BLE001
                log.exception("Erro verificando os temas de notícias")
            time.sleep(INTERVALO_TEMAS_S)

    def _avisar(self, novidades: list[tuple[str, dict[str, Any]]]) -> None:
        from .notificacoes import notificar

        por_tema: dict[str, list[dict]] = {}
        for tema, item in novidades:
            por_tema.setdefault(tema, []).append(item)
        tratamento = self.app.prefs.get("tratamento") or "chefe"
        for tema, itens in por_tema.items():
            primeiro = itens[0]
            extra = f" e mais {len(itens) - 1}" if len(itens) > 1 else ""
            texto = f"{tratamento.capitalize()}, saiu notícia sobre {tema}: {primeiro['titulo']}{extra}."
            log.info("Alerta de tema: %s", texto)
            self.app.fala.falar(texto)
            notificar(self.app, f"{primeiro['titulo']} ({', '.join(primeiro.get('fontes') or [primeiro.get('fonte', '')])})",
                      titulo=f"Notícia sobre {tema}")
            self.app.barramento.publicar("aviso", nivel="lembrete", texto=f"Notícia sobre {tema}: {primeiro['titulo']}")
        if por_tema and self.app.hologramas.aberto("jornal"):
            self.app.hologramas.atualizar_tipo("jornal", self.dados_holograma("temas"))

    # -- leitura da matéria --------------------------------------------------------------------
    def texto_da_materia(self, item: dict[str, Any]) -> str:
        link = item.get("link") or ""
        if not link or "news.google.com" in link:  # links do Google Notícias são redirecionamentos por script
            return item.get("resumo") or ""
        try:
            r = self.http.get(link)
            r.raise_for_status()
            return extrair_texto(r.text) or item.get("resumo") or ""
        except httpx.HTTPError as erro:
            log.info("Não consegui abrir a matéria %s: %s", link, erro)
            return item.get("resumo") or ""

    # -- briefing --------------------------------------------------------------------------------
    def dados_briefing(self) -> dict[str, Any]:
        return {"brasil": [i["titulo"] for i in self.coletar("brasil")[:5]],
                "tecnologia": [i["titulo"] for i in self.coletar("tecnologia")[:5]],
                "temas": [f"{i['tema']}: {i['titulo']}" for t in self.temas() for i in self.buscar_tema(t["tema"])[:1]]}
