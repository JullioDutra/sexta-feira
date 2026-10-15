"""Memória de longo prazo e aprendizado.

Tudo fica em ``dados/memoria.db`` (SQLite, nada sai do PC):

- **itens**: o que ela sabe, de três tipos —
  ``fato`` (sobre o usuário: nomes, preferências, rotina), ``licao`` (como agir: nasce de erros,
  correções do usuário e relatórios dos agentes) e ``conhecimento`` (o que aprendeu em análises,
  pesquisas e engenharia reversa). Cada item tem etiquetas, origem, confiança e contagem de uso;
- **episodios**: cada pedido — o que foi pedido, por onde passou (atalho/IA), as ferramentas usadas
  com o resultado (ok/erro) e o tempo.

A busca usa FTS5 (milissegundos, sem IA). O prompt de sistema leva só uma "foto" dos fatos centrais
(tirada na partida e na consolidação), para o cache do cérebro continuar valendo; o que foi
aprendido depois e o que é relevante para o pedido vai junto da mensagem do usuário
(``contexto_para``). A consolidação diária (``consolidar``) revisa os episódios com o cérebro,
extrai fatos e lições e enfraquece o que nunca é usado.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from ..util.texto import normalizar

log = logging.getLogger(__name__)

TIPOS = ("fato", "licao", "conhecimento")
FOTO_MAX = 40          # fatos no prompt de sistema
RECENTES_MAX = 12      # fatos novos (depois da foto) que vão em todo pedido
EPISODIOS_MAX = 5000

_PARADAS = set("""a o as os um uma uns umas de do da dos das no na nos nas em por para pra pro com sem
e ou que se me te lhe nos vos eu tu ele ela eles elas voce voces meu minha meus minhas seu sua seus suas
isso isto esse essa este esta aquele aquela ai la aqui ja nao sim mais menos muito pouco qual quais quem
como quando onde porque por que ser estar ter fazer foi era sao esta estao tem tinha vai vou sexta feira
favor agora hoje entao tambem so sobre ate ao aos the of""".split())

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS itens (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL,
    texto TEXT NOT NULL,
    chave TEXT NOT NULL,
    etiquetas TEXT NOT NULL DEFAULT '',
    origem TEXT NOT NULL DEFAULT '',
    confianca REAL NOT NULL DEFAULT 1.0,
    usos INTEGER NOT NULL DEFAULT 0,
    criado REAL NOT NULL,
    usado REAL NOT NULL DEFAULT 0,
    ativo INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS itens_chave ON itens(tipo, chave);
CREATE TABLE IF NOT EXISTS episodios (
    id INTEGER PRIMARY KEY,
    quando REAL NOT NULL,
    pedido TEXT NOT NULL,
    canal TEXT NOT NULL DEFAULT '',
    caminho TEXT NOT NULL DEFAULT '',
    ferramentas TEXT NOT NULL DEFAULT '[]',
    ok INTEGER NOT NULL DEFAULT 1,
    resposta TEXT NOT NULL DEFAULT '',
    ms INTEGER NOT NULL DEFAULT 0,
    nota TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS episodios_quando ON episodios(quando);
CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
"""

_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS itens_fts USING fts5(
    texto, etiquetas, content='itens', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS itens_ai AFTER INSERT ON itens BEGIN
    INSERT INTO itens_fts(rowid, texto, etiquetas) VALUES (new.id, new.texto, new.etiquetas);
END;
CREATE TRIGGER IF NOT EXISTS itens_ad AFTER DELETE ON itens BEGIN
    INSERT INTO itens_fts(itens_fts, rowid, texto, etiquetas) VALUES ('delete', old.id, old.texto, old.etiquetas);
END;
CREATE TRIGGER IF NOT EXISTS itens_au AFTER UPDATE OF texto, etiquetas ON itens BEGIN
    INSERT INTO itens_fts(itens_fts, rowid, texto, etiquetas) VALUES ('delete', old.id, old.texto, old.etiquetas);
    INSERT INTO itens_fts(rowid, texto, etiquetas) VALUES (new.id, new.texto, new.etiquetas);
END;
"""


def _chave(texto: str) -> str:
    return re.sub(r"\s+", " ", normalizar(texto)).strip()


def palavras(texto: str) -> list[str]:
    """Palavras que importam para a busca (sem acento, sem palavras vazias)."""
    vistos: list[str] = []
    for p in re.findall(r"[a-z0-9]+", normalizar(texto)):
        if len(p) < 3 and not p.isdigit() or p in _PARADAS or p in vistos:
            continue
        vistos.append(p)
    return vistos


def _consulta_fts(texto: str) -> str:
    termos = []
    for p in palavras(texto)[:12]:
        # radical simples: "contratos" acha "contrato", "aprendeu" acha "aprender"
        raiz = p[:max(4, len(p) - 2)] if len(p) > 5 else p
        termos.append(f'"{raiz}"*')
    return " OR ".join(termos)


class Memoria:
    LIMITE = 400  # fatos ativos (os menos usados saem na consolidação)

    def __init__(self, arquivo: Path, legado: Path | None = None) -> None:
        self.arquivo = arquivo
        self._lock = threading.RLock()
        self._con = sqlite3.connect(str(arquivo), check_same_thread=False, timeout=10)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.executescript(_ESQUEMA)
        try:
            self._con.executescript(_FTS)
            self.fts = True
        except sqlite3.OperationalError:  # SQLite sem FTS5: busca por LIKE
            log.warning("SQLite sem FTS5: a busca da memória vai ser mais simples")
            self.fts = False
        self._con.commit()
        if legado is not None:
            self._migrar(legado)
        self._foto_em = time.time()
        self._foto = self._fatos_centrais()

    # ------------------------------------------------------------------ itens
    def aprender(self, tipo: str, texto: str, etiquetas: Iterable[str] = (), origem: str = "",
                 confianca: float = 1.0) -> int | None:
        """Guarda (ou reforça, se já existe) um item. Devolve o id, ou None se o texto é vazio."""
        if tipo not in TIPOS:
            raise ValueError(f"tipo de memória inválido: {tipo}")
        texto = re.sub(r"\s+", " ", (texto or "")).strip().rstrip(".")
        if not texto:
            return None
        chave = _chave(texto)
        rotulos = " ".join(sorted({normalizar(e).replace(" ", "_") for e in etiquetas if e}))
        agora = time.time()
        with self._lock:
            linha = self._con.execute("SELECT id, etiquetas, ativo FROM itens WHERE tipo=? AND chave=?",
                                      (tipo, chave)).fetchone()
            if linha:
                juntas = " ".join(sorted(set(linha["etiquetas"].split()) | set(rotulos.split())))
                self._con.execute("UPDATE itens SET confianca=MIN(1.0, confianca+0.2), ativo=1, etiquetas=?, "
                                  "usado=? WHERE id=?", (juntas, agora, linha["id"]))
                self._con.commit()
                return int(linha["id"])
            cur = self._con.execute(
                "INSERT INTO itens(tipo, texto, chave, etiquetas, origem, confianca, criado, usado) "
                "VALUES (?,?,?,?,?,?,?,?)", (tipo, texto, chave, rotulos, origem, confianca, agora, agora))
            self._con.commit()
            return int(cur.lastrowid)

    def lembrar(self, texto: str) -> bool:
        """Fato pedido pelo usuário. Falso se já sabia."""
        texto = (texto or "").strip().rstrip(".")
        if not texto:
            return False
        with self._lock:
            existe = self._con.execute("SELECT 1 FROM itens WHERE tipo='fato' AND chave=? AND ativo=1",
                                       (_chave(texto),)).fetchone()
        self.aprender("fato", texto, origem="usuario")
        return not existe

    def esquecer(self, trecho: str, tipos: tuple[str, ...] = TIPOS) -> list[str]:
        alvo = _chave(trecho)
        if not alvo:
            return []
        marcas = ",".join("?" * len(tipos))
        with self._lock:
            linhas = self._con.execute(f"SELECT id, texto, chave FROM itens WHERE ativo=1 AND tipo IN ({marcas})",
                                       tipos).fetchall()
            removidos = [l for l in linhas if alvo in l["chave"]]
            for l in removidos:
                self._con.execute("DELETE FROM itens WHERE id=?", (l["id"],))
            self._con.commit()
        textos = [l["texto"] for l in removidos]
        if textos:
            self._foto = [f for f in self._foto if f not in textos]
        return textos

    def remover(self, item_id: int) -> str | None:
        with self._lock:
            linha = self._con.execute("SELECT texto FROM itens WHERE id=?", (item_id,)).fetchone()
            if not linha:
                return None
            self._con.execute("DELETE FROM itens WHERE id=?", (item_id,))
            self._con.commit()
        self._foto = [f for f in self._foto if f != linha["texto"]]
        return linha["texto"]

    def listar(self, tipo: str = "fato", limite: int = 200) -> list[str]:
        with self._lock:
            linhas = self._con.execute("SELECT texto FROM itens WHERE tipo=? AND ativo=1 ORDER BY criado LIMIT ?",
                                       (tipo, limite)).fetchall()
        return [l["texto"] for l in linhas]

    def itens(self, tipo: str | None = None, limite: int = 100, desde: float | None = None) -> list[dict]:
        sql, args = "SELECT * FROM itens WHERE ativo=1", []
        if tipo:
            sql += " AND tipo=?"
            args.append(tipo)
        if desde is not None:
            sql += " AND criado>=?"
            args.append(desde)
        sql += " ORDER BY criado DESC LIMIT ?"
        args.append(limite)
        with self._lock:
            return [self._item(l) for l in self._con.execute(sql, args).fetchall()]

    def buscar(self, consulta: str, limite: int = 5, tipos: tuple[str, ...] | None = None) -> list[dict]:
        """Itens mais relevantes para ``consulta`` (BM25 + uso). Marca os achados como usados."""
        tipos = tuple(tipos or TIPOS)
        marcas = ",".join("?" * len(tipos))
        with self._lock:
            if self.fts:
                expressao = _consulta_fts(consulta)
                if not expressao:
                    return []
                try:
                    linhas = self._con.execute(
                        f"SELECT itens.*, bm25(itens_fts, 1.0, 0.6) AS nota FROM itens_fts "
                        f"JOIN itens ON itens.id = itens_fts.rowid "
                        f"WHERE itens_fts MATCH ? AND itens.ativo=1 AND itens.tipo IN ({marcas}) "
                        f"ORDER BY nota LIMIT ?", (expressao, *tipos, limite * 3)).fetchall()
                except sqlite3.OperationalError as erro:
                    log.debug("Busca FTS falhou (%s): %s", expressao, erro)
                    return []
            else:
                termos = palavras(consulta)[:6]
                if not termos:
                    return []
                cond = " OR ".join("chave LIKE ?" for _ in termos)
                linhas = self._con.execute(
                    f"SELECT itens.*, 0 AS nota FROM itens WHERE ativo=1 AND tipo IN ({marcas}) AND ({cond}) LIMIT ?",
                    (*tipos, *[f"%{t[:5]}%" for t in termos], limite * 3)).fetchall()
            # bm25 é negativo (menor = melhor); confiança e uso desempatam
            ordenadas = sorted(linhas, key=lambda l: l["nota"] - 0.3 * l["confianca"] - 0.05 * min(l["usos"], 10))
            achados = ordenadas[:limite]
            if achados:
                agora = time.time()
                self._con.executemany("UPDATE itens SET usos=usos+1, usado=? WHERE id=?",
                                      [(agora, l["id"]) for l in achados])
                self._con.commit()
        return [self._item(l) for l in achados]

    @staticmethod
    def _item(linha: sqlite3.Row) -> dict:
        return {"id": linha["id"], "tipo": linha["tipo"], "texto": linha["texto"],
                "etiquetas": [e for e in linha["etiquetas"].split() if e], "origem": linha["origem"],
                "confianca": round(float(linha["confianca"]), 2), "usos": linha["usos"], "criado": linha["criado"]}

    # ------------------------------------------------------------------ prompt
    def _fatos_centrais(self) -> list[str]:
        with self._lock:
            linhas = self._con.execute(
                "SELECT texto FROM itens WHERE tipo='fato' AND ativo=1 "
                "ORDER BY (origem='usuario') DESC, usos DESC, criado LIMIT ?", (FOTO_MAX,)).fetchall()
        return sorted(l["texto"] for l in linhas)

    def renovar_foto(self) -> None:
        """Atualiza os fatos do prompt de sistema (invalida o cache uma vez; use com moderação)."""
        self._foto = self._fatos_centrais()
        self._foto_em = time.time()

    def para_prompt(self) -> str:
        return "\n".join(f"- {f}" for f in self._foto) if self._foto else "- (nenhum ainda)"

    def contexto_para(self, pedido: str, limite: int = 6) -> str:
        """O que juntar à mensagem do usuário: fatos novos e itens relevantes para o pedido."""
        foto = set(self._foto)
        recentes = [i["texto"] for i in self.itens("fato", RECENTES_MAX, desde=self._foto_em)
                    if i["texto"] not in foto]
        relevantes = [i for i in self.buscar(pedido, limite) if i["texto"] not in foto and i["texto"] not in recentes]
        if not recentes and not relevantes:
            return ""
        linhas = [f"- {t}" for t in recentes[::-1]]
        rotulo = {"fato": "fato", "licao": "lição", "conhecimento": "conhecimento"}
        linhas += [f"- ({rotulo[i['tipo']]}) {i['texto']}" for i in relevantes]
        return "<memoria_relevante>\n" + "\n".join(linhas) + "\n</memoria_relevante>"

    # ------------------------------------------------------------------ episódios
    def registrar_episodio(self, pedido: str, *, canal: str = "", caminho: str = "",
                           ferramentas: list[dict] | None = None, resposta: str = "", ms: int = 0,
                           ok: bool | None = None) -> int:
        ferramentas = [{"nome": f.get("ferramenta") or f.get("nome", ""), "ok": bool(f.get("ok", True)),
                        "resumo": str(f.get("resumo", ""))[:160]} for f in ferramentas or []]
        if ok is None:
            ok = all(f["ok"] for f in ferramentas if not f["resumo"].startswith("Confirma"))
        with self._lock:
            cur = self._con.execute(
                "INSERT INTO episodios(quando, pedido, canal, caminho, ferramentas, ok, resposta, ms) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (time.time(), pedido[:500], canal, caminho, json.dumps(ferramentas, ensure_ascii=False),
                 int(bool(ok)), (resposta or "")[:500], int(ms)))
            self._con.commit()
            return int(cur.lastrowid)

    def marcar_episodio(self, episodio_id: int, ok: bool, nota: str = "") -> None:
        with self._lock:
            self._con.execute("UPDATE episodios SET ok=?, nota=CASE WHEN ?='' THEN nota ELSE ? END WHERE id=?",
                              (int(ok), nota, nota[:300], episodio_id))
            self._con.commit()

    def episodios(self, desde: float = 0, limite: int = 200) -> list[dict]:
        with self._lock:
            linhas = self._con.execute("SELECT * FROM episodios WHERE quando>=? ORDER BY quando DESC LIMIT ?",
                                       (desde, limite)).fetchall()
        saida = []
        for l in linhas:
            d = dict(l)
            d["ferramentas"] = json.loads(d["ferramentas"] or "[]")
            d["ok"] = bool(d["ok"])
            saida.append(d)
        return saida

    def ultimo_episodio(self) -> dict | None:
        lista = self.episodios(limite=1)
        return lista[0] if lista else None

    # ------------------------------------------------------------------ aprendizado
    def consolidar(self, completar: Callable[[str, str], str] | None, desde: float | None = None) -> dict:
        """Revisão diária: extrai fatos e lições dos episódios, junta duplicados e enfraquece o que não é usado."""
        desde = desde if desde is not None else float(self._meta("consolidado_em") or 0)
        eps = self.episodios(desde, limite=300)
        novos = {"fato": 0, "licao": 0}
        if eps and completar is not None:
            linhas = []
            for e in reversed(eps):
                ferr = ", ".join(f"{f['nome']}{'' if f['ok'] else ' (FALHOU)'}" for f in e["ferramentas"])
                marca = "" if e["ok"] else " [DEU ERRADO" + (f": {e['nota']}" if e["nota"] else "") + "]"
                linhas.append(f"- {e['pedido']} → {e['resposta'][:140]}{' | ' + ferr if ferr else ''}{marca}")
            sistema = (
                "Você revisa o dia de uma assistente pessoal (a Sexta-Feira) para ela aprender. Responda SÓ com JSON: "
                '{"fatos": [...], "licoes": [...]}. fatos: coisas duradouras sobre o usuário que apareceram nos pedidos '
                "(preferências, nomes, rotina, projetos, horários), na terceira pessoa, uma frase curta cada. licoes: "
                "regras práticas para acertar da próxima vez, principalmente a partir do que deu errado ou foi "
                "corrigido pelo usuário (formato: 'Quando ..., ...'). No máximo 6 de cada; listas vazias se não houver "
                "nada que valha guardar. Não repita o que já está na lista de conhecidos.")
            conhecidos = "\n".join(f"- {t}" for t in self.listar("fato", 80) + self.listar("licao", 40))
            texto = f"Já conhecidos:\n{conhecidos or '- nada'}\n\nPedidos do período:\n" + "\n".join(linhas[-150:])
            try:
                bruto = completar(sistema, texto)
                dados = _extrair_json(bruto)
            except Exception as erro:  # noqa: BLE001
                log.warning("Consolidação da memória falhou: %s", erro)
                dados = {}
            for fato in (dados.get("fatos") or [])[:6]:
                if isinstance(fato, str) and self.aprender("fato", fato, origem="consolidacao", confianca=0.7):
                    novos["fato"] += 1
            for licao in (dados.get("licoes") or [])[:6]:
                if isinstance(licao, str) and self.aprender("licao", licao, origem="consolidacao", confianca=0.8):
                    novos["licao"] += 1
        with self._lock:
            # o que não é usado há 60 dias perde confiança; abaixo de 0,2 sai (fatos do usuário nunca saem sozinhos)
            limite = time.time() - 60 * 86400
            self._con.execute("UPDATE itens SET confianca=confianca-0.2 WHERE usado<? AND origem!='usuario'", (limite,))
            self._con.execute("UPDATE itens SET ativo=0 WHERE confianca<0.2 AND origem!='usuario'")
            excesso = self._con.execute("SELECT COUNT(*) FROM itens WHERE tipo='fato' AND ativo=1").fetchone()[0] - self.LIMITE
            if excesso > 0:
                self._con.execute("UPDATE itens SET ativo=0 WHERE id IN (SELECT id FROM itens WHERE tipo='fato' AND "
                                  "ativo=1 AND origem!='usuario' ORDER BY usos, usado LIMIT ?)", (excesso,))
            velhos = self._con.execute("SELECT COUNT(*) FROM episodios").fetchone()[0] - EPISODIOS_MAX
            if velhos > 0:
                self._con.execute("DELETE FROM episodios WHERE id IN (SELECT id FROM episodios ORDER BY quando LIMIT ?)",
                                  (velhos,))
            self._con.commit()
        self._meta("consolidado_em", str(time.time()))
        self.renovar_foto()
        return novos

    def estatisticas(self) -> dict[str, Any]:
        with self._lock:
            contagem = {t: n for t, n in self._con.execute(
                "SELECT tipo, COUNT(*) FROM itens WHERE ativo=1 GROUP BY tipo").fetchall()}
            eps = self._con.execute("SELECT COUNT(*), COALESCE(SUM(ok),0) FROM episodios").fetchone()
        consolidado = self._meta("consolidado_em")
        return {"fatos": contagem.get("fato", 0), "licoes": contagem.get("licao", 0),
                "conhecimentos": contagem.get("conhecimento", 0), "episodios": eps[0], "acertos": eps[1],
                "consolidado_em": datetime.fromtimestamp(float(consolidado)).isoformat(timespec="minutes")
                if consolidado else None}

    # ------------------------------------------------------------------ interno
    def _meta(self, chave: str, valor: str | None = None) -> str | None:
        with self._lock:
            if valor is None:
                linha = self._con.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
                return linha["valor"] if linha else None
            self._con.execute("INSERT OR REPLACE INTO meta(chave, valor) VALUES (?,?)", (chave, valor))
            self._con.commit()
            return valor

    def _migrar(self, legado: Path) -> None:
        """Traz os fatos do ``memoria.json`` antigo (uma vez)."""
        if not legado.exists() or self._meta("migrado_json"):
            return
        try:
            fatos = json.loads(legado.read_text(encoding="utf-8")).get("fatos", [])
        except (OSError, ValueError):
            fatos = []
        for f in fatos:
            if isinstance(f, dict) and f.get("texto"):
                self.aprender("fato", f["texto"], origem="usuario")
        self._meta("migrado_json", "1")

    def fechar(self) -> None:
        with self._lock:
            self._con.close()


def _extrair_json(texto: str) -> dict:
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fim <= inicio:
        return {}
    try:
        dados = json.loads(texto[inicio:fim + 1])
    except json.JSONDecodeError:
        return {}
    return dados if isinstance(dados, dict) else {}
