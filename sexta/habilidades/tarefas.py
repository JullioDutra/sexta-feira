"""Tarefas e projetos: prazo, prioridade, estimativa de tempo e quadro Kanban (a fazer / fazendo / feito).

"Anota: terminar o sistema do campeonato até sexta" -> tarefa com prazo na sexta.
Fica no mesmo banco SQLite dos lembretes (``dados/sexta.db``).
"""

from __future__ import annotations

import calendar
import logging
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from ..util.tempo import interpretar_quando
from ..util.texto import normalizar

log = logging.getLogger(__name__)

PRIORIDADES = ["alta", "media", "baixa"]
STATUS = ["a_fazer", "fazendo", "feito"]
NOMES_STATUS = {"a_fazer": "a fazer", "fazendo": "fazendo", "feito": "feito"}
DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
ESTIMATIVA_PADRAO = 60


def interpretar_prazo(texto: str | None, hoje: date | None = None) -> date | None:
    """ "sexta", "amanhã", "dia 20", "semana que vem", "fim do mês" -> data."""
    if not texto:
        return None
    hoje = hoje or date.today()
    t = normalizar(texto)
    t = re.sub(r"^(ate|para|pra|no|na|em|antes de|ate o|ate a) ", "", t).strip()
    if t in ("hoje", "hj"):
        return hoje
    if re.search(r"(fim|final) (do|desse|deste) mes", t):
        return hoje.replace(day=calendar.monthrange(hoje.year, hoje.month)[1])
    if re.search(r"(fim|final) de semana|(fim|final) da semana", t):
        return hoje + timedelta(days=(5 - hoje.weekday()) % 7 or 7) if hoje.weekday() != 5 else hoje
    if re.search(r"semana que vem|proxima semana", t):
        return hoje + timedelta(days=7 - hoje.weekday())  # a segunda da semana que vem
    if re.search(r"mes que vem|proximo mes", t):
        return (hoje.replace(day=1) + timedelta(days=32)).replace(day=1)
    # fim do dia como referência: o prazo não depende da hora em que se fala
    # ("até sexta" dito numa sexta = a próxima sexta; para hoje, diga "até hoje")
    momento = interpretar_quando(t, datetime.combine(hoje, datetime.max.time().replace(microsecond=0)))
    return momento.date() if momento else None


def descrever_prazo(prazo: date | None, hoje: date | None = None) -> str:
    if prazo is None:
        return ""
    hoje = hoje or date.today()
    dias = (prazo - hoje).days
    if dias < -1:
        return f"atrasada {-dias} dias"
    if dias == -1:
        return "era para ontem"
    if dias == 0:
        return "hoje"
    if dias == 1:
        return "amanhã"
    if dias < 7:
        return f"{DIAS_SEMANA[prazo.weekday()]}, {prazo:%d/%m}"
    return f"{prazo:%d/%m}"


class Tarefas:
    def __init__(self, app, arquivo: Path) -> None:
        self.app = app
        self._db = sqlite3.connect(str(arquivo), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(
                """CREATE TABLE IF NOT EXISTS tarefas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    titulo TEXT NOT NULL,
                    projeto TEXT NOT NULL DEFAULT '',
                    prazo TEXT,
                    prioridade TEXT NOT NULL DEFAULT 'media',
                    estimativa INTEGER,
                    status TEXT NOT NULL DEFAULT 'a_fazer',
                    criado REAL NOT NULL,
                    concluido REAL,
                    ordem REAL NOT NULL DEFAULT 0)""")
            self._db.commit()

    # -- conversão ----------------------------------------------------------------------
    @staticmethod
    def _dict(linha: sqlite3.Row, hoje: date | None = None) -> dict:
        hoje = hoje or date.today()
        prazo = date.fromisoformat(linha["prazo"]) if linha["prazo"] else None
        return {
            "id": linha["id"], "titulo": linha["titulo"], "projeto": linha["projeto"],
            "prazo": prazo.isoformat() if prazo else None, "prazo_texto": descrever_prazo(prazo, hoje),
            "atrasada": bool(prazo and prazo < hoje and linha["status"] != "feito"),
            "prioridade": linha["prioridade"], "estimativa": linha["estimativa"], "status": linha["status"],
            "concluido": datetime.fromtimestamp(linha["concluido"]).isoformat(timespec="minutes") if linha["concluido"] else None,
        }

    # -- escrita ---------------------------------------------------------------------------
    def criar(self, titulo: str, prazo: date | None = None, prioridade: str = "media", estimativa: int | None = None,
              projeto: str = "") -> dict:
        titulo = titulo.strip().rstrip(".")
        if not titulo:
            raise ValueError("A tarefa precisa de um título.")
        prioridade = prioridade if prioridade in PRIORIDADES else "media"
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO tarefas (titulo, projeto, prazo, prioridade, estimativa, criado, ordem) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (titulo[0].upper() + titulo[1:], projeto.strip(), prazo.isoformat() if prazo else None, prioridade,
                 int(estimativa) if estimativa else None, time.time(), time.time()))
            self._db.commit()
            linha = self._db.execute("SELECT * FROM tarefas WHERE id = ?", (cur.lastrowid,)).fetchone()
        self._mudou()
        return self._dict(linha)

    def atualizar(self, id_: int, **campos) -> dict | None:
        permitidos = {"titulo", "projeto", "prazo", "prioridade", "estimativa", "status"}
        valores = {k: v for k, v in campos.items() if k in permitidos}
        if "status" in valores:
            if valores["status"] not in STATUS:
                raise ValueError("Situação inválida.")
            valores["concluido"] = time.time() if valores["status"] == "feito" else None
            valores["ordem"] = time.time()
        if "prioridade" in valores and valores["prioridade"] not in PRIORIDADES:
            raise ValueError("Prioridade inválida.")
        if isinstance(valores.get("prazo"), date):
            valores["prazo"] = valores["prazo"].isoformat()
        if not valores:
            return self.obter(id_)
        with self._lock:
            sets = ", ".join(f"{k} = ?" for k in valores)
            self._db.execute(f"UPDATE tarefas SET {sets} WHERE id = ?", (*valores.values(), id_))  # noqa: S608 - chaves filtradas
            self._db.commit()
        self._mudou()
        return self.obter(id_)

    def apagar(self, id_: int) -> bool:
        with self._lock:
            n = self._db.execute("DELETE FROM tarefas WHERE id = ?", (id_,)).rowcount
            self._db.commit()
        if n:
            self._mudou()
        return bool(n)

    # -- leitura ------------------------------------------------------------------------------
    def obter(self, id_: int) -> dict | None:
        with self._lock:
            linha = self._db.execute("SELECT * FROM tarefas WHERE id = ?", (id_,)).fetchone()
        return self._dict(linha) if linha else None

    def listar(self, status: str | None = None, incluir_feitas_dias: int = 3) -> list[dict]:
        """Pendentes ordenadas por urgência; feitas só as recentes (o quadro não cresce para sempre)."""
        limite = time.time() - incluir_feitas_dias * 86400
        with self._lock:
            linhas = self._db.execute(
                "SELECT * FROM tarefas WHERE status != 'feito' OR concluido >= ? ORDER BY ordem", (limite,)).fetchall()
        hoje = date.today()
        itens = [self._dict(l, hoje) for l in linhas]
        if status:
            itens = [i for i in itens if i["status"] == status]
        return sorted(itens, key=chave_urgencia)

    def pendentes(self) -> list[dict]:
        return [t for t in self.listar() if t["status"] != "feito"]

    def feitas_em(self, dia: date) -> list[dict]:
        inicio = datetime.combine(dia, datetime.min.time()).timestamp()
        with self._lock:
            linhas = self._db.execute("SELECT * FROM tarefas WHERE status = 'feito' AND concluido >= ? AND concluido < ?",
                                      (inicio, inicio + 86400)).fetchall()
        return [self._dict(l) for l in linhas]

    def encontrar(self, texto: str) -> dict | None:
        """Pelo número ("2"), pela posição na lista ou por parte do título (aproximado)."""
        texto = (texto or "").strip()
        if texto.isdigit():
            return self.obter(int(texto))
        from rapidfuzz import fuzz

        alvo = normalizar(texto)
        melhor, nota = None, 0.0
        for t in self.listar():
            n = max(fuzz.partial_ratio(alvo, normalizar(t["titulo"])), fuzz.token_set_ratio(alvo, normalizar(t["titulo"])))
            if t["status"] == "feito":
                n -= 10
            if n > nota:
                melhor, nota = t, n
        return melhor if nota >= 70 else None

    def quadro(self) -> dict:
        itens = self.listar()
        return {"colunas": {s: [t for t in itens if t["status"] == s] for s in STATUS},
                "projetos": sorted({t["projeto"] for t in itens if t["projeto"]})}

    def _mudou(self) -> None:
        barramento = getattr(self.app, "barramento", None)
        if barramento is None:
            return
        hologramas = getattr(self.app, "hologramas", None)
        if hologramas is not None and hologramas.aberto("tarefas"):
            hologramas.atualizar_tipo("tarefas", self.quadro())


def chave_urgencia(t: dict) -> tuple:
    """Atrasadas primeiro, depois por prazo, prioridade e as mais curtas."""
    prazo = date.fromisoformat(t["prazo"]) if t.get("prazo") else date.max
    return (t["status"] == "feito", not t.get("atrasada"), prazo, PRIORIDADES.index(t.get("prioridade") or "media"),
            t.get("estimativa") or ESTIMATIVA_PADRAO)


_PRIORIDADE = re.compile(r"\b(urgente|prioridade (alta|maxima)|importante|prioridade baixa|sem pressa|quando der)\b")
_ESTIMATIVA = re.compile(r"\b(?:leva|levo|demora|dura|vai levar|uns|umas|cerca de)?\s*(\d+(?:[.,]\d+)?|meia|uma|duas|tres)\s*"
                         r"(h|hora|horas|min|minuto|minutos)\b")
_PRAZO = re.compile(r"\s+(?:ate|para|pra)\s+(?:o |a )?(hoje|amanha|depois de amanha|segunda|terca|quarta|quinta|sexta|sabado|"
                    r"domingo|dia \d{1,2}(?: de \w+)?|\d{1,2}/\d{1,2}|semana que vem|proxima semana|fim do mes|final do mes|"
                    r"fim da semana|final da semana|mes que vem)(?:[ -]feira)?\b")
_PRAZO_SOLTO = re.compile(r"\s+(?:na |no |pra |para |de )?(hoje|amanha|depois de amanha|segunda|terca|quarta|quinta|sexta|sabado|"
                          r"domingo)(?:[ -]feira)?\s*$")
_INICIO = re.compile(r"^(?:que |pra |para )?(?:eu )?(?:preciso|tenho que|tenho de|devo|lembrar de|nao esquecer de)\s+")
_PROJETO = re.compile(r"\s+(?:no|do|para o) projeto\s+(.+?)(?=\s+(?:ate|para|pra)\s|$)")
_NUMEROS = {"meia": 0.5, "uma": 1, "duas": 2, "tres": 3}


def interpretar_tarefa(texto: str, hoje: date | None = None) -> dict:
    """ "terminar o sistema do campeonato até sexta, urgente, leva 3 horas" -> campos da tarefa."""
    original = texto.strip().rstrip(".")
    t = normalizar(original)
    campos: dict = {}
    if m := _PRIORIDADE.search(t):
        campos["prioridade"] = "baixa" if m.group(1) in ("prioridade baixa", "sem pressa", "quando der") else "alta"
        t = t.replace(m.group(0), " ")
    if m := _ESTIMATIVA.search(t):
        n = _NUMEROS.get(m.group(1)) or float(m.group(1).replace(",", "."))
        campos["estimativa"] = round(n * 60 if m.group(2).startswith("h") else n)
        t = t.replace(m.group(0), " ")
    if m := _PROJETO.search(t):
        campos["projeto"] = m.group(1).strip()
        t = t.replace(m.group(0), " ")
    if m := _PRAZO.search(t):
        campos["prazo"] = interpretar_prazo(m.group(1), hoje)
        t = t[: m.start()] + t[m.end():]
    t = re.sub(r"\s+", " ", t).strip(" ,.-")
    if "prazo" not in campos and (m := _PRAZO_SOLTO.search(t)):
        campos["prazo"] = interpretar_prazo(m.group(1), hoje)
        t = t[: m.start()]
    t = _INICIO.sub("", t)
    titulo_normalizado = re.sub(r"\s+", " ", t).strip(" ,.-")
    campos["titulo"] = _recuperar_acentos(original, titulo_normalizado)
    if campos.get("projeto"):
        campos["projeto"] = _recuperar_acentos(original, campos["projeto"])
    return campos


def _recuperar_acentos(original: str, normalizado: str) -> str:
    """Devolve o trecho do texto original (com acentos e maiúsculas) que corresponde ao título limpo."""
    palavras_orig = re.findall(r"[\wÀ-ÿ'-]+", original)
    alvo = normalizado.split()
    for i in range(len(palavras_orig)):
        janela = palavras_orig[i:i + len(alvo)]
        if [normalizar(p) for p in janela] == alvo:
            return " ".join(janela)
    return normalizado
