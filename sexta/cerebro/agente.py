"""O cérebro da Sexta-Feira: conversa com o modelo local e executa ferramentas.

Fluxo de um pedido:
1. tenta um atalho rápido (sem IA);
2. senão, manda para o Ollama com as ferramentas disponíveis;
3. executa as ferramentas pedidas e devolve os resultados ao modelo;
4. a resposta final vai sendo falada frase a frase enquanto chega (streaming).
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
import time
from datetime import datetime
from typing import Any

from ..util.tempo import data_extenso, formatar_hora
from ..util.texto import DivisorFrases
from . import atalhos
from .ferramentas import Contexto
from .ollama import ClienteOllama, ErroOllama

log = logging.getLogger(__name__)

_IDS = itertools.count(1)

PERSONA = """Você é a Sexta-Feira, a assistente pessoal de {nome}. Você roda localmente no computador dele (Windows 11) e controla o PC por meio de ferramentas.

Personalidade: confiante, eficiente, leal e com um humor leve e seco, no estilo de uma IA de filme de super-herói. Trate o usuário por "{tratamento}". Fale sempre em português do Brasil.

Como agir:
- Use as ferramentas sempre que o pedido depender de dados reais (clima, notícias, lembretes, rotinas, estado do PC) ou exigir uma ação no computador. Nunca invente esses dados.
- Depois de usar uma ferramenta, responda com o essencial do resultado — os detalhes já aparecem no holograma.
- Para pedidos de horário em lembretes, passe o horário como o usuário falou (ex.: "amanhã às 7h", "daqui a 20 minutos").
- Para desligar, reiniciar ou suspender o PC, confirme com o usuário antes; só chame a ferramenta com confirmado=true depois que ele confirmar.
- Se não souber algo ou não tiver ferramenta para isso, diga com franqueza.
{estilo}

Contexto atual:
- Agora: {agora}
- Cidade do usuário: {cidade}
- Rotinas disponíveis: {rotinas}
- Canal: {canal}

Fatos que o usuário pediu para você lembrar:
{memoria}"""

ESTILO_VOZ = """- Esta resposta será FALADA em voz alta: seja breve (1 a 3 frases curtas), natural e direta. Não use markdown, listas, emojis nem links."""
ESTILO_TEXTO = """- Esta resposta será lida no celular: seja objetiva (até 5 frases). Pode usar quebras de linha, mas evite markdown pesado."""


class FiltroTags:
    """Remove blocos <think>…</think> e captura <tool_call>…</tool_call> do texto em streaming."""

    TAGS = ("think", "tool_call")

    def __init__(self) -> None:
        self.buffer = ""
        self.dentro: str | None = None
        self.capturado: list[str] = []
        self._atual = ""

    def alimentar(self, pedaco: str) -> str:
        self.buffer += pedaco
        visivel = []
        while self.buffer:
            if self.dentro is None:
                inicio = self.buffer.find("<")
                if inicio == -1:
                    visivel.append(self.buffer)
                    self.buffer = ""
                    break
                visivel.append(self.buffer[:inicio])
                self.buffer = self.buffer[inicio:]
                abriu = next((t for t in self.TAGS if self.buffer.startswith(f"<{t}>")), None)
                if abriu:
                    self.dentro = abriu
                    self.buffer = self.buffer[len(abriu) + 2:]
                    self._atual = ""
                    continue
                if any(f"<{t}>".startswith(self.buffer) for t in self.TAGS):
                    break  # pode ser o começo de uma tag: espera mais texto
                visivel.append(self.buffer[0])
                self.buffer = self.buffer[1:]
            else:
                fim = self.buffer.find(f"</{self.dentro}>")
                if fim == -1:
                    seguro = max(0, len(self.buffer) - len(self.dentro) - 3)
                    self._atual += self.buffer[:seguro]
                    self.buffer = self.buffer[seguro:]
                    break
                self._atual += self.buffer[:fim]
                if self.dentro == "tool_call":
                    self.capturado.append(self._atual)
                self.buffer = self.buffer[fim + len(self.dentro) + 3:]
                self.dentro = None
        return "".join(visivel)

    def finalizar(self) -> str:
        resto = "" if self.dentro else self.buffer
        self.buffer = ""
        return resto

    def chamadas(self) -> list[dict[str, Any]]:
        saida = []
        for bloco in self.capturado:
            try:
                dados = json.loads(bloco.strip())
                saida.append({"nome": dados.get("name", ""), "argumentos": dados.get("arguments") or {}})
            except (json.JSONDecodeError, AttributeError):
                continue
        return saida


class SaidaFala:
    """Manda frases completas para a voz conforme o texto chega."""

    def __init__(self, fala) -> None:
        self.fala = fala
        self.divisor = DivisorFrases()
        self.falou = False

    def alimentar(self, texto: str) -> None:
        for frase in self.divisor.alimentar(texto):
            self.fala.falar(frase)
            self.falou = True

    def finalizar(self) -> None:
        for frase in self.divisor.finalizar():
            self.fala.falar(frase)
            self.falou = True


class Agente:
    MAX_RODADAS = 5
    HISTORICO_MAX = 16
    OCIOSO_REINICIA = 15 * 60

    def __init__(self, app, cliente: ClienteOllama | None = None) -> None:
        self.app = app
        cfg = app.cfg
        self.ollama = cliente or ClienteOllama(
            cfg.ollama_url, cfg.ollama_modelo, pensar=cfg.ollama_pensar, contexto=cfg.ollama_contexto,
            temperatura=cfg.ollama_temperatura, manter_carregado=cfg.ollama_manter_carregado,
        )
        self.historico: list[dict[str, str]] = []
        self._lock = threading.Lock()
        self._cancelar = threading.Event()
        self._ultima_interacao = 0.0

    # ------------------------------------------------------------------
    def cancelar(self) -> None:
        self._cancelar.set()
        self.app.fala.parar()

    def ocupado(self) -> bool:
        return self._lock.locked()

    def limpar_historico(self) -> None:
        self.historico.clear()

    def processar(self, texto: str, canal: str = "voz", cliente=None, falar: bool = True) -> dict[str, Any]:
        """Processa um pedido do usuário e devolve ``{"texto", "resultados", "id"}``."""
        texto = (texto or "").strip()
        resposta_id = next(_IDS)
        bus = self.app.barramento
        if not texto:
            return {"texto": "", "resultados": [], "id": resposta_id}

        with self._lock:
            self._cancelar.clear()
            if time.time() - self._ultima_interacao > self.OCIOSO_REINICIA:
                self.historico.clear()
            self._ultima_interacao = time.time()
            bus.publicar("conversa", papel="usuario", texto=texto, canal=canal, id=resposta_id)
            self.app.estado.definir("pensando")
            ctx = Contexto(self.app, canal=canal, cliente=cliente)
            try:
                final = None
                if self.app.prefs.get("atalhos_rapidos"):
                    final = atalhos.tentar(texto, ctx)
                if final is None:
                    final = self._conversar(texto, ctx, resposta_id, falar)
                else:
                    if falar and final:
                        self.app.fala.falar(final)
                    self._registrar(texto, final)
            except ErroOllama as erro:
                log.error("%s", erro)
                final = str(erro)
                bus.publicar("aviso", nivel="erro", texto=final)
                if falar:
                    self.app.fala.falar("Não consegui acessar meu cérebro local. Veja o aviso na tela.")
            except Exception:  # noqa: BLE001
                log.exception("Erro processando pedido")
                final = "Tive um problema ao processar isso."
                if falar:
                    self.app.fala.falar(final)
            finally:
                if not self.app.fala.falando_ou_na_fila():
                    self.app.estado.definir("inativa")
            bus.publicar("conversa", papel="assistente", texto=final, canal=canal, id=resposta_id,
                         ferramentas=[r["ferramenta"] for r in ctx.resultados])
            return {"texto": final, "resultados": ctx.resultados, "id": resposta_id}

    # ------------------------------------------------------------------
    def _conversar(self, texto: str, ctx: Contexto, resposta_id: int, falar: bool) -> str:
        bus = self.app.barramento
        mensagens: list[dict[str, Any]] = [{"role": "system", "content": self._sistema(ctx)}]
        mensagens += self.historico[-self.HISTORICO_MAX:]
        mensagens.append({"role": "user", "content": texto})
        saida = SaidaFala(self.app.fala) if falar else None
        texto_final = ""
        assinaturas: set[str] = set()

        for _rodada in range(self.MAX_RODADAS):
            filtro = FiltroTags()
            partes: list[str] = []
            chamadas: list[dict[str, Any]] = []
            for evento in self.ollama.conversar(mensagens, self.app.registro.esquemas(), self._cancelar.is_set):
                if evento["tipo"] == "texto":
                    visivel = filtro.alimentar(evento["texto"])
                    if visivel:
                        partes.append(visivel)
                        bus.publicar("resposta.parcial", texto=visivel, id=resposta_id)
                        if saida:
                            saida.alimentar(visivel)
                elif evento["tipo"] == "ferramentas":
                    chamadas = evento["chamadas"]
            resto = filtro.finalizar()
            if resto:
                partes.append(resto)
                if saida:
                    saida.alimentar(resto)
            chamadas = chamadas or filtro.chamadas()
            texto_rodada = "".join(partes).strip()
            if self._cancelar.is_set():
                break
            if not chamadas:
                texto_final = texto_rodada
                break

            mensagens.append({
                "role": "assistant",
                "content": texto_rodada,
                "tool_calls": [{"function": {"name": c["nome"], "arguments": c["argumentos"]}} for c in chamadas],
            })
            repetida = False
            for chamada in chamadas:
                assinatura = chamada["nome"] + json.dumps(chamada["argumentos"], sort_keys=True, ensure_ascii=False)
                repetida = repetida or assinatura in assinaturas
                assinaturas.add(assinatura)
                bus.publicar("ferramenta", nome=chamada["nome"], argumentos=chamada["argumentos"], id=resposta_id)
                log.info("Ferramenta: %s %s", chamada["nome"], chamada["argumentos"])
                resultado = self.app.registro.executar(chamada["nome"], chamada["argumentos"], ctx)
                conteudo = {k: v for k, v in resultado.items() if not k.startswith("_")}
                mensagens.append({"role": "tool", "tool_name": chamada["nome"],
                                  "content": json.dumps(conteudo, ensure_ascii=False, default=str)})
            if repetida:
                break

        if not texto_final:
            resumos = [r["resumo"] for r in ctx.resultados if r.get("resumo")]
            texto_final = " ".join(resumos[-2:]) if resumos else ("Cancelado." if self._cancelar.is_set() else "Pronto.")
            if saida and not saida.falou:
                saida.alimentar(texto_final + " ")
        if saida:
            saida.finalizar()
        self._registrar(texto, texto_final)
        return texto_final

    def _registrar(self, pergunta: str, resposta: str) -> None:
        self.historico.append({"role": "user", "content": pergunta})
        self.historico.append({"role": "assistant", "content": resposta or "(ação executada)"})
        self.historico = self.historico[-self.HISTORICO_MAX:]

    def _sistema(self, ctx: Contexto) -> str:
        prefs = self.app.prefs
        agora = datetime.now()
        nome = prefs.get("nome") or "seu usuário"
        rotinas = ", ".join(r.nome for r in self.app.rotinas.listar()) or "nenhuma"
        canal = {"voz": "voz (microfone do PC)", "texto": "texto no HUD do PC", "celular": "celular"}.get(ctx.canal, ctx.canal)
        return PERSONA.format(
            nome=nome,
            tratamento=prefs.get("tratamento") or "chefe",
            estilo=ESTILO_VOZ if ctx.canal == "voz" else ESTILO_TEXTO,
            agora=f"{data_extenso(agora)}, {formatar_hora(agora)}",
            cidade=prefs.get("cidade_rotulo") or prefs.get("cidade") or "não definida (pergunte se precisar)",
            rotinas=rotinas,
            canal=canal,
            memoria=self.app.memoria.para_prompt(),
        )
