"""Extensão "tarefas_aprendidas": ela aprende tarefas e depois as executa sozinha.

Três jeitos de aprender:

- **Ensinando** ("aprende a tarefa relatório semanal: abre o Excel, ..."): o cérebro transforma a explicação num
  roteiro (objetivo, passos, que agente usar e frases para chamar).
- **Mostrando** ("começa a gravar a tarefa arrumar a mesa" … comandos … "termina a gravação"): os pedidos feitos
  durante a gravação que deram certo viram uma sequência que ela repete igualzinho, sem IA.
- **Pelos agentes**: quando um agente termina uma tarefa com sucesso (conferência ✓), o caminho que deu certo vira
  um roteiro guardado na memória; "salva isso como a tarefa X" o transforma numa tarefa aprendida.

Para executar: "faz a tarefa X", "executa X" ou uma das frases da tarefa. Tarefa gravada → repete os comandos em
segundo plano, conferindo cada um. Tarefa ensinada → um agente trabalha nela com o roteiro. No fim ela diz se deu
certo; cada execução conta acertos e erros, e o roteiro melhora com a última execução bem-sucedida. Para rodar
sozinha: "faz a tarefa X toda segunda às 9h" (vira um protocolo de horário).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from ..util.texto import normalizar

log = logging.getLogger(__name__)

HOLOGRAMAS = {"tarefas_aprendidas": "Tarefas aprendidas"}
PREFERENCIAS = {"tarefas_aprender_dos_agentes": True}

MAX_COMANDOS = 40
TIPOS_AGENTE = ("automacao", "navegador", "pesquisador", "programador", "engenharia_reversa", "video")

SISTEMA_ENSINO = """Você transforma a explicação de uma tarefa (dita por voz, em português do Brasil) num roteiro para uma \
assistente pessoal que controla o PC executar sozinha depois. Responda SÓ com JSON:
{"nome": "nome curto da tarefa (2 a 5 palavras, minúsculas)",
 "frases": ["2 a 4 jeitos curtos de pedir a tarefa", ...],
 "objetivo": "o que precisa estar pronto no fim, numa frase",
 "passos": ["passo 1 no imperativo", ...],
 "agente": "automacao | navegador | pesquisador | programador | engenharia_reversa | video",
 "conferir": "como saber que deu certo (evidência objetiva)"}
Escolha o agente pelo tipo de trabalho: PC/programas/arquivos = automacao; sites = navegador; pesquisa com fontes = \
pesquisador; código = programador. Não invente passos que o usuário não pediu."""

SISTEMA_ROTEIRO = """Você resume, para uso futuro, como um agente autônomo conseguiu cumprir um objetivo. Recebe o \
objetivo e os passos que ele deu (ferramentas e resultados). Responda SÓ com JSON: {"passos": ["passo reaproveitável \
no imperativo", ...], "conferir": "como saber que deu certo"}. No máximo 10 passos, sem detalhes que só valiam daquela \
vez (ids, horários), mantendo nomes de sites, programas e pastas."""


def _agora() -> float:
    return time.time()


def _ler_json(texto: str) -> dict:
    inicio, fim = (texto or "").find("{"), (texto or "").rfind("}")
    if inicio == -1 or fim <= inicio:
        return {}
    try:
        dados = json.loads(texto[inicio:fim + 1])
    except json.JSONDecodeError:
        return {}
    return dados if isinstance(dados, dict) else {}


class TarefasAprendidas:
    def __init__(self, app, arquivo: Path) -> None:
        self.app = app
        self.arquivo = arquivo
        self._lock = threading.RLock()
        self.tarefas: list[dict] = self._carregar()
        self.gravando: dict | None = None
        self.execucoes: dict[str, dict] = {}   # id da tarefa -> execução em andamento
        self._agentes: dict[str, str] = {}     # id do agente -> id da tarefa
        self._ultimo_agente: Any = None

    # -- persistência --------------------------------------------------------------------
    def _carregar(self) -> list[dict]:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [t for t in dados.get("tarefas", []) if isinstance(t, dict) and t.get("nome")]

    def _salvar(self) -> None:
        with self._lock:
            try:
                tmp = self.arquivo.with_suffix(".tmp")
                tmp.write_text(json.dumps({"tarefas": self.tarefas}, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(tmp, self.arquivo)
            except OSError as erro:
                log.warning("Não consegui salvar as tarefas aprendidas: %s", erro)
        self._atualizar_holograma()

    def _atualizar_holograma(self) -> None:
        hologramas = getattr(self.app, "hologramas", None)
        if hologramas is not None and hologramas.aberto("tarefas_aprendidas"):
            hologramas.atualizar_tipo("tarefas_aprendidas", self.dados())

    def dados(self) -> dict:
        with self._lock:
            tarefas = [dict(t) for t in self.tarefas]
        for t in tarefas:
            t["executando"] = t["id"] in self.execucoes
        return {"tarefas": tarefas, "gravando": (self.gravando or {}).get("nome"),
                "comandos_gravados": len((self.gravando or {}).get("comandos", []))}

    # -- consulta ------------------------------------------------------------------------
    def encontrar(self, nome: str) -> dict | None:
        alvo = normalizar(nome or "").strip()
        alvo = re.sub(r"^(a |o |de |da |do )", "", alvo)
        if not alvo:
            return None
        with self._lock:
            for t in self.tarefas:
                if normalizar(t["nome"]) == alvo or alvo in (normalizar(f) for f in t.get("frases", [])):
                    return t
            for t in self.tarefas:  # começo do nome ("relatório" acha "relatório semanal")
                if normalizar(t["nome"]).startswith(alvo) and len(alvo) >= 4:
                    return t
        return None

    def por_frase(self, t: str) -> dict | None:
        with self._lock:
            for tarefa in self.tarefas:
                if t in (normalizar(f) for f in tarefa.get("frases", [])):
                    return tarefa
        return None

    # -- aprender ------------------------------------------------------------------------
    def _guardar(self, tarefa: dict) -> dict:
        tarefa.setdefault("id", f"t{int(_agora() * 1000) % 10**10}")
        tarefa.setdefault("criada", _agora())
        tarefa.setdefault("execucoes", 0)
        tarefa.setdefault("sucessos", 0)
        tarefa.setdefault("ultima", None)
        tarefa["frases"] = [f for f in dict.fromkeys(str(f).strip() for f in tarefa.get("frases", [])) if f][:6]
        with self._lock:
            self.tarefas = [t for t in self.tarefas if normalizar(t["nome"]) != normalizar(tarefa["nome"])]
            self.tarefas.append(tarefa)
        self._salvar()
        memoria = getattr(self.app, "memoria", None)
        if memoria is not None:
            try:
                resumo = f"Tarefa aprendida '{tarefa['nome']}': {tarefa.get('objetivo') or ''}".strip()
                memoria.aprender("conhecimento", resumo, etiquetas=["tarefa_aprendida", tarefa["origem"]],
                                 origem="tarefas_aprendidas")
            except Exception:  # noqa: BLE001
                log.debug("Memória não guardou a tarefa", exc_info=True)
        return tarefa

    def ensinar(self, explicacao: str, nome: str | None = None) -> dict:
        """O usuário explicou a tarefa: o cérebro escreve o roteiro."""
        explicacao = (explicacao or "").strip()
        if len(explicacao) < 8:
            raise ValueError("Me explica a tarefa: o que fazer e como.")
        bruto = self.app.agente.completar(SISTEMA_ENSINO, (f"Nome dado pelo usuário: {nome}\n" if nome else "")
                                          + f"Explicação: {explicacao}", rapido=False)
        dados = _ler_json(bruto)
        passos = [str(p).strip() for p in dados.get("passos") or [] if str(p).strip()]
        if not passos:
            raise ValueError("Não consegui transformar isso num roteiro. Tenta explicar passo a passo.")
        agente = str(dados.get("agente") or "automacao").strip()
        nome_final = (nome or str(dados.get("nome") or "")).strip().lower() or passos[0][:40].lower()
        return self._guardar({
            "nome": nome_final, "origem": "ensinada", "explicacao": explicacao[:2000],
            "objetivo": str(dados.get("objetivo") or explicacao)[:500], "passos": passos[:20],
            "agente": agente if agente in TIPOS_AGENTE else "automacao",
            "conferir": str(dados.get("conferir") or "")[:300],
            "frases": [nome_final, *[str(f) for f in dados.get("frases") or []]],
        })

    def comecar_gravacao(self, nome: str) -> str:
        nome = (nome or "").strip().lower()
        if not nome:
            raise ValueError("Qual o nome da tarefa que vou gravar?")
        self.gravando = {"nome": nome, "comandos": [], "inicio": _agora()}
        self._atualizar_holograma()
        return (f"Gravando a tarefa {nome}. Pode ir pedindo as coisas normalmente; quando acabar, diga "
                f"\"termina a gravação\".")

    def ouvir_pedido(self, pedido: str, ctx, caminho: str, resposta: str) -> None:
        """Ouvinte do aprendizado: durante a gravação, guarda os pedidos que fizeram algo e deram certo."""
        gravando = self.gravando
        if gravando is None or caminho in ("confirmacao", "aprendizado"):
            return
        if _CONTROLE.search(normalizar(pedido)):
            return
        resultados = [r for r in ctx.resultados if not str(r.get("resumo", "")).startswith("Confirma")]
        if not resultados or not all(r.get("ok", True) for r in resultados):
            return
        if len(gravando["comandos"]) < MAX_COMANDOS:
            gravando["comandos"].append(pedido.strip())
            self._atualizar_holograma()

    def terminar_gravacao(self, cancelar: bool = False) -> str:
        gravando, self.gravando = self.gravando, None
        if gravando is None:
            return "Eu não estava gravando nenhuma tarefa."
        if cancelar:
            self._atualizar_holograma()
            return "Gravação descartada."
        if not gravando["comandos"]:
            self._atualizar_holograma()
            return "Não gravei nenhum comando que deu certo, então não salvei a tarefa."
        tarefa = self._guardar({
            "nome": gravando["nome"], "origem": "gravada", "comandos": gravando["comandos"],
            "objetivo": "; ".join(gravando["comandos"])[:500], "frases": [gravando["nome"]],
        })
        n = len(tarefa["comandos"])
        return (f"Aprendi a tarefa {tarefa['nome']}, com {n} passo{'s' if n > 1 else ''}. "
                f"É só dizer \"faz a tarefa {tarefa['nome']}\".")

    def agente_terminou(self, agente) -> None:
        """Ouvinte do gerente de agentes: guarda o roteiro do que deu certo."""
        tarefa_id = self._agentes.pop(agente.id, None)
        self._ultimo_agente = agente
        if tarefa_id:
            self._fim_execucao_agente(tarefa_id, agente)
        if agente.status != "concluido" or not self.app.prefs.get("tarefas_aprender_dos_agentes", True):
            return
        threading.Thread(target=self._guardar_roteiro_do_agente, args=(agente, tarefa_id), daemon=True,
                         name="roteiro-agente").start()

    def _roteiro_do_agente(self, agente) -> dict:
        passos = "\n".join(f"- [{p['tipo']}{'' if p.get('ok') is None else (' ok' if p['ok'] else ' falhou')}] "
                           f"{p['texto']}" for p in agente.passos if p["tipo"] in ("ferramenta", "resultado"))[-6000:]
        bruto = self.app.agente.completar(SISTEMA_ROTEIRO, f"Objetivo: {agente.objetivo}\n\nPassos:\n{passos}")
        return _ler_json(bruto)

    def _guardar_roteiro_do_agente(self, agente, tarefa_id: str | None) -> None:
        try:
            dados = self._roteiro_do_agente(agente)
        except Exception as erro:  # noqa: BLE001
            log.info("Sem roteiro do agente %s: %s", agente.id, erro)
            return
        passos = [str(p).strip() for p in dados.get("passos") or [] if str(p).strip()][:10]
        if not passos:
            return
        agente.roteiro = {"passos": passos, "conferir": str(dados.get("conferir") or "")}
        objetivo = agente.objetivo.split("\n\n", 1)[0].removeprefix("Tarefa aprendida: ")
        memoria = getattr(self.app, "memoria", None)
        if memoria is not None:
            try:
                memoria.aprender("conhecimento", f"Como fiz '{objetivo[:120]}': " + " → ".join(passos),
                                 etiquetas=["roteiro", agente.tipo.nome], origem=f"agente {agente.id}")
            except Exception:  # noqa: BLE001
                log.debug("Memória não guardou o roteiro", exc_info=True)
        if tarefa_id:  # a tarefa melhora com a última execução que deu certo
            with self._lock:
                for t in self.tarefas:
                    if t["id"] == tarefa_id and t.get("origem") != "gravada":
                        t["passos"] = passos
                        if agente.roteiro["conferir"]:
                            t["conferir"] = agente.roteiro["conferir"]
            self._salvar()

    def salvar_ultimo_agente(self, nome: str) -> str:
        agente = self._ultimo_agente
        if agente is None:
            return "Nenhum agente terminou ainda para eu aprender com ele."
        if agente.status != "concluido":
            return "O último agente não terminou com sucesso; prefiro não aprender com ele."
        roteiro = getattr(agente, "roteiro", None)
        if not roteiro:
            try:
                dados = self._roteiro_do_agente(agente)
            except Exception as erro:  # noqa: BLE001
                return f"Não consegui resumir o que o agente fez: {erro}"
            roteiro = {"passos": [str(p) for p in dados.get("passos") or []][:10],
                       "conferir": str(dados.get("conferir") or "")}
        if not roteiro["passos"]:
            return "Não consegui tirar um roteiro do que o agente fez."
        nome = (nome or "").strip().lower() or agente.objetivo[:40].lower()
        objetivo = agente.objetivo.split("\n\n", 1)[0].removeprefix("Tarefa aprendida: ")
        self._guardar({"nome": nome, "origem": "agente", "objetivo": objetivo[:500], "passos": roteiro["passos"],
                       "agente": agente.tipo.nome, "conferir": roteiro["conferir"], "frases": [nome]})
        return f"Salvei como a tarefa {nome}. Da próxima vez é só pedir."

    def esquecer(self, nome: str) -> str:
        tarefa = self.encontrar(nome)
        if tarefa is None:
            return f"Não conheço a tarefa {nome}."
        with self._lock:
            self.tarefas = [t for t in self.tarefas if t["id"] != tarefa["id"]]
        self._salvar()
        return f"Esqueci a tarefa {tarefa['nome']}."

    # -- executar ------------------------------------------------------------------------
    def executar(self, nome_ou_tarefa, origem: str = "voz") -> str:
        tarefa = nome_ou_tarefa if isinstance(nome_ou_tarefa, dict) else self.encontrar(nome_ou_tarefa)
        if tarefa is None:
            nomes = ", ".join(t["nome"] for t in self.tarefas[:5])
            return f"Não conheço essa tarefa." + (f" Sei fazer: {nomes}." if nomes else
                                                    " Me ensine com \"aprende a tarefa ...\".")
        if tarefa["id"] in self.execucoes:
            return f"A tarefa {tarefa['nome']} já está em andamento."
        if tarefa.get("comandos"):
            self.execucoes[tarefa["id"]] = {"inicio": _agora(), "modo": "repetir"}
            threading.Thread(target=self._repetir, args=(tarefa, origem), daemon=True,
                             name=f"tarefa-{tarefa['id']}").start()
            self._atualizar_holograma()
            return f"Fazendo a tarefa {tarefa['nome']}."
        gerente = getattr(self.app, "agentes", None)
        if gerente is None:
            return "Para essa tarefa preciso dos agentes, e eles não estão disponíveis."
        roteiro = "\n".join(f"{i}. {p}" for i, p in enumerate(tarefa.get("passos") or [], 1))
        objetivo = (f"Tarefa aprendida: {tarefa.get('objetivo') or tarefa['nome']}\n\n"
                    f"Roteiro que já deu certo (siga, adaptando se algo mudou):\n{roteiro}")
        if tarefa.get("conferir"):
            objetivo += f"\n\nComo conferir no fim: {tarefa['conferir']}"
        try:
            agente = gerente.iniciar(tarefa.get("agente") or "automacao", objetivo, origem)
        except ValueError as erro:
            return str(erro)
        self.execucoes[tarefa["id"]] = {"inicio": _agora(), "modo": "agente", "agente": agente.id}
        self._agentes[agente.id] = tarefa["id"]
        self._atualizar_holograma()
        return f"Pode deixar: o agente {agente.tipo.rotulo.lower()} está fazendo a tarefa {tarefa['nome']}."

    def _repetir(self, tarefa: dict, origem: str) -> None:
        """Repete os comandos gravados, um por vez, conferindo cada um."""
        agente = self.app.agente
        ok, falha = True, ""
        for i, comando in enumerate(tarefa["comandos"], 1):
            for _ in range(600):  # espera o pedido que disparou a tarefa terminar
                if not agente.ocupado():
                    break
                time.sleep(0.1)
            self.app.barramento.publicar("tarefa_aprendida", nome=tarefa["nome"], passo=i,
                                         total=len(tarefa["comandos"]), comando=comando)
            resultado = agente.processar(comando, canal="texto", falar=False)
            erros = [r for r in resultado.get("resultados", []) if not r.get("ok", True)
                     and not str(r.get("resumo", "")).startswith("Confirma")]
            pendente = any(str(r.get("resumo", "")).startswith("Confirma") for r in resultado.get("resultados", []))
            if pendente:  # repetir não aprova nada sozinho: para e avisa
                ok, falha = False, f"o passo \"{comando}\" pediu confirmação"
                self.app.registro.cancelar_pendente()
                break
            if erros:
                ok, falha = False, f"o passo \"{comando}\" falhou: {erros[0].get('resumo', '')}"
                break
        self._terminar(tarefa, ok, falha, origem)

    def _fim_execucao_agente(self, tarefa_id: str, agente) -> None:
        with self._lock:
            tarefa = next((t for t in self.tarefas if t["id"] == tarefa_id), None)
        if tarefa is None:
            self.execucoes.pop(tarefa_id, None)
            return
        ok = agente.status == "concluido"
        falha = "" if ok else (agente.evidencia or agente.resumo or agente.status)
        # o gerente de agentes já avisa o fim; aqui só contabiliza
        self._terminar(tarefa, ok, falha, origem=None)

    def _terminar(self, tarefa: dict, ok: bool, falha: str, origem: str | None) -> None:
        self.execucoes.pop(tarefa["id"], None)
        with self._lock:
            for t in self.tarefas:
                if t["id"] == tarefa["id"]:
                    t["execucoes"] = int(t.get("execucoes") or 0) + 1
                    t["sucessos"] = int(t.get("sucessos") or 0) + (1 if ok else 0)
                    t["ultima"] = {"quando": _agora(), "ok": ok, "falha": falha[:300]}
        self._salvar()
        memoria = getattr(self.app, "memoria", None)
        if not ok and memoria is not None:
            try:
                memoria.aprender("licao", f"Na tarefa '{tarefa['nome']}', cuidado: {falha}"[:400],
                                 etiquetas=["tarefa_aprendida"], origem="tarefas_aprendidas")
            except Exception:  # noqa: BLE001
                log.debug("Memória não guardou a falha", exc_info=True)
        if origem is None:
            return
        texto = (f"Tarefa {tarefa['nome']} concluída." if ok else f"A tarefa {tarefa['nome']} parou: {falha}.")
        self.app.barramento.publicar("aviso", nivel="sucesso" if ok else "alerta", texto=texto)
        if origem == "voz":
            self.app.fala.falar(texto)
        elif origem == "celular":
            try:
                from ..habilidades.notificacoes import notificar

                notificar(self.app, texto, titulo="Tarefa aprendida")
            except Exception:  # noqa: BLE001
                log.debug("Notificação da tarefa falhou", exc_info=True)

    def agendar(self, nome: str, horario: str, dias: list[str] | None) -> str:
        tarefa = self.encontrar(nome)
        if tarefa is None:
            return f"Não conheço a tarefa {nome}."
        from ..habilidades.rotinas import _hora

        hora = _hora(horario or "")
        if not hora:
            return "Em que horário? Ex.: 9h, 18:30."
        rotina = self.app.rotinas.rascunho(f"tarefa {tarefa['nome']}", [{"tarefa": tarefa["nome"]}],
                                           gatilhos=[{"tipo": "horario", "valor": hora, "dias": dias or ["todos"]}])
        self.app.rotinas.salvar(rotina)
        quando = "todo dia" if not dias or dias == ["todos"] else ", ".join(dias)
        return f"Combinado: faço a tarefa {tarefa['nome']} {quando} às {hora}."


# -- ganchos da extensão ------------------------------------------------------------------

def instalar(app) -> None:
    app.tarefas_aprendidas = TarefasAprendidas(app, app.cfg.dados / "tarefas_aprendidas.json")
    aprendizado = getattr(app, "aprendizado", None)
    if aprendizado is not None and hasattr(aprendizado, "ouvintes"):
        aprendizado.ouvintes.append(app.tarefas_aprendidas.ouvir_pedido)
    gerente = getattr(app, "agentes", None)
    if gerente is not None and hasattr(gerente, "ao_terminar"):
        gerente.ao_terminar.append(app.tarefas_aprendidas.agente_terminou)


def _acao_tarefa(app, valor, ctx, variaveis) -> None:
    servico = getattr(app, "tarefas_aprendidas", None)
    if servico is not None and str(valor or "").strip():
        texto = servico.executar(str(valor), origem="protocolo")
        app.barramento.publicar("aviso", nivel="info", texto=texto)


ACOES_PROTOCOLO = {
    "tarefa": {"rotulo": "Fazer tarefa aprendida", "entrada": "texto", "dica": "nome da tarefa aprendida",
               "executar": _acao_tarefa},
}

_DIAS = {"segunda": "seg", "terca": "ter", "quarta": "qua", "quinta": "qui", "sexta": "sex", "sabado": "sab",
         "domingo": "dom"}

_ENSINAR = re.compile(r"^(aprende|aprenda|aprender) (a fazer |a )?(tarefa |a tarefa )?(?P<nome>[^:]{2,60}?)\s*[:,]\s*(?P<explicacao>.{8,})$")
_GRAVAR = re.compile(r"^(comeca|começa|inicia|iniciar|comecar) a gravar (a )?(tarefa )?(?P<nome>.{2,60})$|"
                     r"^grava (a )?tarefa (?P<nome2>.{2,60})$")
_PARAR_GRAVACAO = re.compile(r"^(termina|terminar|para|parar|pare|finaliza|finalizar|encerra|encerrar)( a)?( de)? "
                             r"(gravar|gravacao)( da tarefa)?$|^fim da gravacao$")
_DESCARTAR = re.compile(r"^(cancela|descarta|joga fora) a gravacao$")
_FAZER = re.compile(r"^(faz|faca|fazer|executa|execute|executar|roda|rode) a tarefa (?P<nome>.{2,60})$")
_AGENDAR = re.compile(r"^(faz|faca|executa|roda) a tarefa (?P<nome>.{2,50}?) (?P<quando>todo dia|todos os dias|"
                      r"toda (segunda|terca|quarta|quinta|sexta|sabado|domingo)|todo (sabado|domingo)|"
                      r"(nos )?dias uteis) (as|a) (?P<hora>\d{1,2}(h\d{0,2}|:\d{2})?)( horas)?$")
_LISTAR = re.compile(r"^(quais|que) tarefas (voce )?(sabe fazer|aprendeu|conhece)$|^(mostra|abre|lista) (as )?"
                     r"tarefas aprendidas$")
_SALVAR_AGENTE = re.compile(r"^(salva|guarda|aprende) (isso|o que o agente fez|o que voce fez) como (a )?tarefa "
                            r"(?P<nome>.{2,60})$")
_ESQUECER = re.compile(r"^(esquece|apaga|desaprende) a tarefa (?P<nome>.{2,60})$")
_CONTROLE = re.compile(r"gravar|gravacao|tarefa aprendida|faz a tarefa|aprende a tarefa")


def _grafia_original(nome: str, original: str | None) -> str:
    """O nome como o usuário escreveu/falou (com acentos), achado no texto original; senão, o normalizado."""
    if not original:
        return nome
    palavras = re.findall(r"[\w'-]+", original)
    alvo = nome.split()
    for i in range(len(palavras) - len(alvo) + 1):
        if [normalizar(p) for p in palavras[i:i + len(alvo)]] == alvo:
            return " ".join(palavras[i:i + len(alvo)]).lower()
    return nome


def _original_depois(original: str | None, separador: str = ":") -> str:
    if not original or separador not in original:
        return ""
    return original.split(separador, 1)[1].strip()


def atalho(t: str, ctx, rodar, original):
    app = ctx.app
    servico: TarefasAprendidas | None = getattr(app, "tarefas_aprendidas", None)
    if servico is None:
        return None
    if _PARAR_GRAVACAO.match(t):
        return lambda: servico.terminar_gravacao()
    if _DESCARTAR.match(t):
        return lambda: servico.terminar_gravacao(cancelar=True)
    if m := _GRAVAR.match(t):
        nome = _grafia_original((m.group("nome") or m.group("nome2")).strip(), original)
        return lambda: servico.comecar_gravacao(nome)
    if m := _ENSINAR.match(t):
        nome = _grafia_original(m.group("nome").strip(), original)
        explicacao = _original_depois(original) or m.group("explicacao")

        def ensinar() -> str:
            try:
                tarefa = servico.ensinar(explicacao, nome=nome)
            except ValueError as erro:
                return str(erro)
            except Exception as erro:  # noqa: BLE001 - sem cérebro
                return f"Não consegui aprender agora: {erro}"
            app.hologramas.mostrar("tarefas_aprendidas", servico.dados())
            n = len(tarefa["passos"])
            return f"Aprendi a tarefa {tarefa['nome']}, em {n} passo{'s' if n > 1 else ''}. É só dizer \"faz a tarefa {tarefa['nome']}\"."
        return ensinar
    if m := _AGENDAR.match(t):
        quando = m.group("quando")
        dias = None
        if "uteis" in quando:
            dias = ["uteis"]
        elif "toda" in quando or "todo s" in quando or quando.startswith("todo sabado") or quando.startswith("todo domingo"):
            dias = [_DIAS[quando.split()[-1]]]
        hora = m.group("hora")
        return lambda: servico.agendar(m.group("nome"), hora, dias)
    if m := _FAZER.match(t):
        return lambda: servico.executar(m.group("nome"), origem=ctx.canal)
    if _LISTAR.match(t):
        def listar() -> str:
            app.hologramas.mostrar("tarefas_aprendidas", servico.dados())
            nomes = [x["nome"] for x in servico.tarefas]
            return ("Sei fazer: " + ", ".join(nomes[:6]) + ".") if nomes else \
                "Ainda não aprendi nenhuma tarefa. Diga \"aprende a tarefa X: ...\" ou \"começa a gravar a tarefa X\"."
        return listar
    if m := _SALVAR_AGENTE.match(t):
        return lambda: servico.salvar_ultimo_agente(_grafia_original(m.group("nome").strip(), original))
    if m := _ESQUECER.match(t):
        return lambda: servico.esquecer(m.group("nome"))
    tarefa = servico.por_frase(t)
    if tarefa is not None:
        return lambda: servico.executar(tarefa, origem=ctx.canal)
    return None


def registrar(app, registro) -> None:
    from ..cerebro.ferramentas import P

    @registro.ferramenta(
        "tarefa_aprendida",
        "Tarefas que o usuário ensinou para você fazer sozinha. executar: faz a tarefa (por nome); ensinar: aprende "
        "uma tarefa nova a partir da explicação do usuário; listar; agendar (horário e dias); salvar_agente: salva "
        "o que o último agente fez com sucesso como tarefa; esquecer.",
        direta=True,
        acao=P("string", "Ação.", enum=["executar", "ensinar", "listar", "agendar", "salvar_agente", "esquecer"],
               obrigatorio=True),
        nome=P("string", "Nome da tarefa."),
        explicacao=P("string", "Para ensinar: a explicação do usuário, completa."),
        horario=P("string", "Para agendar: HH:MM."),
        dias=P("array", "Para agendar: seg..dom, uteis ou todos.", itens={"type": "string"}),
    )
    def tarefa_aprendida(ctx, acao: str, nome: str | None = None, explicacao: str | None = None,
                         horario: str | None = None, dias: list | None = None):
        servico: TarefasAprendidas = app.tarefas_aprendidas
        if acao == "listar":
            app.hologramas.mostrar("tarefas_aprendidas", servico.dados())
            nomes = [t["nome"] for t in servico.tarefas]
            return {"ok": True, "resumo": ("Sei fazer: " + ", ".join(nomes) + ".") if nomes else "Nenhuma tarefa aprendida ainda."}
        if acao == "ensinar":
            try:
                tarefa = servico.ensinar(explicacao or "", nome=nome)
            except ValueError as erro:
                return {"ok": False, "resumo": str(erro)}
            return {"ok": True, "resumo": f"Aprendi a tarefa {tarefa['nome']}."}
        if acao == "salvar_agente":
            texto = servico.salvar_ultimo_agente(nome or "")
            return {"ok": texto.startswith("Salvei"), "resumo": texto}
        if not nome:
            return {"ok": False, "resumo": "Qual tarefa?"}
        if acao == "executar":
            texto = servico.executar(nome, origem=ctx.canal)
            return {"ok": not texto.startswith("Não conheço"), "resumo": texto}
        if acao == "agendar":
            texto = servico.agendar(nome, horario or "", dias)
            return {"ok": texto.startswith("Combinado"), "resumo": texto}
        texto = servico.esquecer(nome)
        return {"ok": texto.startswith("Esqueci"), "resumo": texto}


def dados_holograma(app, tipo: str) -> dict | None:
    if tipo == "tarefas_aprendidas" and getattr(app, "tarefas_aprendidas", None) is not None:
        return app.tarefas_aprendidas.dados()
    return None


def rotas(api, app, autenticado, so_pc) -> None:
    import asyncio

    from fastapi import Depends, HTTPException, Request

    @api.get("/api/tarefas_aprendidas")
    def listar(_=Depends(autenticado)):
        return app.tarefas_aprendidas.dados()

    @api.post("/api/tarefas_aprendidas/{tarefa_id}/executar")
    def executar(tarefa_id: str, _=Depends(autenticado)):
        tarefa = next((t for t in app.tarefas_aprendidas.tarefas if t["id"] == tarefa_id), None)
        if tarefa is None:
            raise HTTPException(404, "Tarefa não encontrada.")
        return {"texto": app.tarefas_aprendidas.executar(tarefa, origem="texto"), **app.tarefas_aprendidas.dados()}

    @api.post("/api/tarefas_aprendidas")
    async def ensinar(request: Request, _=Depends(so_pc)):
        corpo = await request.json()
        try:
            await asyncio.to_thread(app.tarefas_aprendidas.ensinar, str(corpo.get("explicacao") or ""),
                                    str(corpo.get("nome") or "").strip() or None)
        except ValueError as erro:
            raise HTTPException(400, str(erro)) from erro
        return app.tarefas_aprendidas.dados()

    @api.delete("/api/tarefas_aprendidas/{tarefa_id}")
    def apagar(tarefa_id: str, _=Depends(so_pc)):
        servico = app.tarefas_aprendidas
        tarefa = next((t for t in servico.tarefas if t["id"] == tarefa_id), None)
        if tarefa is None:
            raise HTTPException(404, "Tarefa não encontrada.")
        servico.esquecer(tarefa["nome"])
        return servico.dados()
