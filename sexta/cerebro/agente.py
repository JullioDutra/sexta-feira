"""O cérebro da Sexta-Feira: conversa com o modelo local e executa ferramentas.

Fluxo de um pedido:
1. se havia uma ação esperando confirmação, "sim"/"não" resolvem na hora;
2. tenta um atalho rápido (sem IA) — cobre a maioria dos comandos do dia a dia;
3. senão, manda para o Ollama com as ferramentas disponíveis;
4. executa as ferramentas pedidas. Se o resultado já é a resposta (abrir, volume,
   janelas...), fala direto, sem uma segunda ida ao modelo;
5. senão devolve os resultados ao modelo e a resposta final vai sendo falada frase a
   frase enquanto chega (streaming).

Para ser rápido, o prompt de sistema e as ferramentas não mudam entre pedidos: o
Ollama reaproveita o que já processou (cache) e só lê a parte nova da conversa. A
hora e o canal vão junto da mensagem do usuário.
"""

from __future__ import annotations

import itertools
import json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any

from ..util.tempo import data_extenso, formatar_hora
from ..util.texto import DivisorFrases, normalizar
from . import atalhos
from .ferramentas import Contexto
from .ollama import ClienteOllama, ErroOllama

log = logging.getLogger(__name__)

_IDS = itertools.count(1)

PERSONA = """Você é a Sexta-Feira, a assistente pessoal de {nome}. Você roda localmente no computador dele (Windows 11) e controla o PC por meio de ferramentas.

Personalidade: confiante, eficiente, leal e com um humor leve e seco, no estilo de uma IA de filme de super-herói. Trate o usuário por "{tratamento}". Fale sempre em português do Brasil.

Como agir:
- Use as ferramentas sempre que o pedido depender de dados reais ou exigir uma ação no computador. Nunca invente dados.
- Pedidos com várias ações ("fecha o Chrome e abre o Spotify"): chame todas as ferramentas de uma vez.
- Depois de usar uma ferramenta, responda só com o essencial — os detalhes aparecem no holograma.
- Arquivos: para achar use arquivos(acao=buscar). Para abrir direto pelo nome use arquivos(acao=abrir, alvo=<descrição>); depois de uma busca, use o número do resultado (alvo="1").
- Área de transferência: quando o pedido falar do que foi copiado, o texto já vem junto da mensagem. Para "corrige e cola" ou "traduz e cola", chame area_transferencia(acao=colar, texto=<resultado>).
- Tela: para "analisa a tela", "o que é esse erro?" ou "lê isso aqui" use ver(fonte=tela); para um objeto ou papel na frente da câmera, ver(fonte=camera).
- Lembretes: passe o horário como o usuário falou ("amanhã às 7h", "daqui a 20 minutos").
- Protocolos (automações): pedidos como "toda vez que...", "quando eu abrir...", "sempre que chegar..." viram criar_protocolo. Ele mostra o protocolo na tela e o usuário aprova com "sim".
- Ações sensíveis (fechar, mover, apagar, desligar, comandos fora da lista) pedem confirmação sozinhas: apenas chame a ferramenta. Nunca diga que fez algo que ainda espera confirmação.
- Memória: você lembra desta conversa e dos fatos abaixo. Quando o usuário contar algo pessoal e duradouro (nomes, preferências, datas, rotina, time, trabalho), guarde com memoria(acao=lembrar) sem pedir licença. Use esses fatos naturalmente nas respostas. Nunca diga que não tem memória.
- Responda primeiro o que foi perguntado, sem rodeios; nada de "como uma IA" nem repetir a pergunta.
- Se não souber algo ou não tiver ferramenta para isso, diga com franqueza.
{estilo}

Cidade do usuário: {cidade}
Protocolos e rotinas: {rotinas}
Layouts de janelas: {layouts}

Fatos que o usuário pediu para você lembrar:
{memoria}"""

ESTILO_VOZ = """- Esta resposta será FALADA em voz alta: seja breve (1 a 3 frases curtas), natural e direta. Não use markdown, listas, emojis nem links."""
ESTILO_TEXTO = """- Esta resposta será lida na tela: seja objetiva (até 5 frases). Pode usar quebras de linha, mas evite markdown pesado."""

# pedidos que pedem o cérebro maior (quando há dois)
_COMPLEXO = re.compile(
    r"\b(planej|analis|explica|expliq|por que|porque|compar|escrev|redig|resum|traduz|corrig|ideia|sugest|"
    r"cri[ae] uma rotina|o que (voce )?acha|como (eu )?(faco|posso)|me ajuda|estrategia|calcul)"
)
_AREA_TRANSFERENCIA = re.compile(
    r"\b(copiei|copiado|copiada|area de transferencia|clipboard|o que (eu )?copi|texto que (eu )?copi|isso que copi)"
)
_SIM = re.compile(r"^(sim|s|pode|confirmo|confirma|confirmado|isso|claro|manda ver|manda|faz|faca|pode fazer|"
                  r"aprovo|aprova|aprovado|aprovada|pode salvar|salva|salvar|pode ativar|ativa|"
                  r"pode sim|sim pode|positivo|com certeza|ok|okay|pode ir|vai|vai la|autorizo|autorizado|"
                  r"certo|beleza|bora|uhum|aham)( sim| pode| por favor| sexta feira| confirmo)?$")
_NAO = re.compile(r"^(nao|n|cancela|cancelar|negativo|deixa|deixa pra la|esquece|nao precisa|melhor nao|"
                  r"nem pensar|para|pare|nao faz isso|nao pode)( nao| obrigad[oa])?$")


def interpretar_confirmacao(texto: str) -> bool | None:
    t = normalizar(texto)
    t = re.sub(r"^(sexta feira |sexta )", "", t)
    if _SIM.match(t):
        return True
    if _NAO.match(t):
        return False
    return None


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
    MAX_RODADAS = 6
    HISTORICO_MAX = 24
    OCIOSO_REINICIA = 6 * 3600  # depois de 6 h parada, a conversa recomeça (os fatos da memória ficam)

    def __init__(self, app, cliente=None) -> None:
        self.app = app
        cfg = app.cfg
        usa_claude = cliente is None and cfg.usa_claude()
        if cliente is not None:
            self.ollama = cliente
        elif usa_claude:
            from .claude import ClienteClaude

            self.ollama = ClienteClaude(cfg.claude_modelo, esforco_voz=cfg.claude_esforco_voz,
                                        esforco_texto=cfg.claude_esforco_texto)
        else:
            self.ollama = ClienteOllama(
                cfg.ollama_url, cfg.ollama_modelo, pensar=cfg.ollama_pensar, contexto=cfg.ollama_contexto,
                temperatura=cfg.ollama_temperatura, manter_carregado=cfg.ollama_manter_carregado,
            )
        self.nome_cerebro = "Claude" if usa_claude else "Ollama"
        self.modelo_rapido = (cfg.claude_modelo_rapido if usa_claude else getattr(cfg, "ollama_modelo_rapido", "")) or ""
        self.max_tokens_voz = int(getattr(cfg, "ollama_max_tokens_voz", 400) or 0)
        self._arquivo_historico = cfg.dados / "historico.json"
        self.historico: list[dict[str, str]] = self._carregar_historico()
        self._lock = threading.Lock()
        self._cancelar = threading.Event()
        self._ultima_interacao = time.time() if self.historico else 0.0

    # ------------------------------------------------------------------
    def cancelar(self) -> None:
        self._cancelar.set()
        self.app.fala.parar()

    def ocupado(self) -> bool:
        return self._lock.locked()

    def aquecer(self) -> None:
        """Carrega o(s) modelo(s) e já processa o prompt de sistema + ferramentas (cache do Ollama)."""
        ctx = Contexto(self.app, canal="voz")
        mensagens = [{"role": "system", "content": self._sistema(ctx)}, {"role": "user", "content": "oi"}]
        ferramentas = self.app.registro.esquemas()
        self.ollama.aquecer(mensagens, ferramentas)
        if self.modelo_rapido and self.modelo_rapido != self.ollama.modelo:
            self.ollama.aquecer(mensagens, ferramentas, modelo=self.modelo_rapido)

    def processar(self, texto: str, canal: str = "voz", cliente=None, falar: bool = True) -> dict[str, Any]:
        """Processa um pedido do usuário e devolve ``{"texto", "resultados", "id"}``."""
        texto = (texto or "").strip()
        resposta_id = next(_IDS)
        bus = self.app.barramento
        if not texto:
            return {"texto": "", "resultados": [], "id": resposta_id}

        with self._lock:
            inicio = time.perf_counter()
            self._cancelar.clear()
            if self.historico and time.time() - self._ultima_interacao > self.OCIOSO_REINICIA:
                self.limpar_historico()
            self._ultima_interacao = time.time()
            bus.publicar("conversa", papel="usuario", texto=texto, canal=canal, id=resposta_id)
            self.app.estado.definir("pensando")
            ctx = Contexto(self.app, canal=canal, cliente=cliente)
            caminho = "ia"
            try:
                final = self._resolver_confirmacao(texto, ctx)
                if final is not None:
                    caminho = "confirmacao"
                elif self.app.prefs.get("atalhos_rapidos"):
                    final = atalhos.tentar(texto, ctx)
                    caminho = "atalho"
                if final is None:
                    caminho = "ia"
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
                    self.app.fala.falar("Não consegui acessar meu cérebro. Veja o aviso na tela.")
            except Exception:  # noqa: BLE001
                log.exception("Erro processando pedido")
                final = "Tive um problema ao processar isso."
                if falar:
                    self.app.fala.falar(final)
            finally:
                if not self.app.fala.falando_ou_na_fila():
                    self.app.estado.definir("inativa")
            duracao = round((time.perf_counter() - inicio) * 1000)
            log.info("Pedido resolvido por %s em %d ms", caminho, duracao)
            bus.publicar("conversa", papel="assistente", texto=final, canal=canal, id=resposta_id,
                         ferramentas=[r["ferramenta"] for r in ctx.resultados], caminho=caminho, ms=duracao)
            return {"texto": final, "resultados": ctx.resultados, "id": resposta_id, "caminho": caminho, "ms": duracao}

    # ------------------------------------------------------------------
    def _resolver_confirmacao(self, texto: str, ctx: Contexto) -> str | None:
        registro = self.app.registro
        pendente = registro.pendente()
        if pendente is None:
            return None
        resposta = interpretar_confirmacao(texto)
        if resposta is not True:
            registro.cancelar_pendente()  # "não", ou o usuário mudou de assunto
            if pendente.nome == "criar_protocolo":
                self.app.hologramas.fechar(tipo="protocolo")
            return "Tudo bem, cancelado." if resposta is False else None
        resultado = registro.confirmar(ctx, self.app.verificar_para_acao)
        return resultado.get("resumo") or "Feito."

    def _escolher_modelo(self, texto: str) -> str | None:
        """Dois cérebros: comandos curtos vão para o modelo rápido; o resto, para o principal."""
        if not self.modelo_rapido:
            return None
        t = normalizar(texto)
        if len(t.split()) > 14 or _COMPLEXO.search(t) or _AREA_TRANSFERENCIA.search(t):
            return None
        return self.modelo_rapido

    def _mensagem_usuario(self, texto: str, ctx: Contexto) -> str:
        agora = datetime.now()
        canal = {"voz": "voz", "texto": "texto no HUD", "celular": "celular"}.get(ctx.canal, ctx.canal)
        partes = [f"[{data_extenso(agora)}, {formatar_hora(agora)} · canal: {canal}]"]
        if _AREA_TRANSFERENCIA.search(normalizar(texto)):
            from ..habilidades import area_transferencia

            try:
                copiado = area_transferencia.ler().strip()
            except Exception as erro:  # noqa: BLE001
                copiado = ""
                log.warning("Não consegui ler a área de transferência: %s", erro)
            if copiado:
                limite = area_transferencia.LIMITE
                partes.append(f"<area_de_transferencia>\n{copiado[:limite]}\n</area_de_transferencia>")
            else:
                partes.append("(a área de transferência está vazia ou não tem texto)")
        partes.append(texto)
        return "\n".join(partes)

    def _conversar(self, texto: str, ctx: Contexto, resposta_id: int, falar: bool) -> str:
        bus = self.app.barramento
        mensagens: list[dict[str, Any]] = [{"role": "system", "content": self._sistema(ctx)}]
        mensagens += self.historico[-self.HISTORICO_MAX:]
        mensagens.append({"role": "user", "content": self._mensagem_usuario(texto, ctx)})
        saida = SaidaFala(self.app.fala) if falar else None
        texto_final = ""
        direto = False
        assinaturas: set[str] = set()
        modelo = self._escolher_modelo(texto)
        max_tokens = self.max_tokens_voz if ctx.canal == "voz" else None
        ferramentas = self.app.registro.esquemas()
        inicio = time.perf_counter()
        primeiro_texto: float | None = None

        for _rodada in range(self.MAX_RODADAS):
            filtro = FiltroTags()
            partes: list[str] = []
            chamadas: list[dict[str, Any]] = []
            bruto: Any = None
            for evento in self.ollama.conversar(mensagens, ferramentas, self._cancelar.is_set,
                                                modelo=modelo, max_tokens=max_tokens):
                if evento["tipo"] == "texto":
                    visivel = filtro.alimentar(evento["texto"])
                    if visivel:
                        if primeiro_texto is None:
                            primeiro_texto = time.perf_counter()
                        partes.append(visivel)
                        bus.publicar("resposta.parcial", texto=visivel, id=resposta_id)
                        if saida:
                            saida.alimentar(visivel)
                elif evento["tipo"] == "ferramentas":
                    chamadas = evento["chamadas"]
                elif evento["tipo"] == "fim":
                    bruto = evento.get("bruto")
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

            mensagens.append(self.ollama.mensagem_assistente(texto_rodada, chamadas, bruto))
            repetida = False
            resultados_rodada = []
            conteudos = []
            for chamada in chamadas:
                assinatura = chamada["nome"] + json.dumps(chamada["argumentos"], sort_keys=True, ensure_ascii=False)
                repetida = repetida or assinatura in assinaturas
                assinaturas.add(assinatura)
                bus.publicar("ferramenta", nome=chamada["nome"], argumentos=chamada["argumentos"], id=resposta_id)
                log.info("Ferramenta: %s %s", chamada["nome"], chamada["argumentos"])
                resultado = self.app.registro.executar(chamada["nome"], chamada["argumentos"], ctx)
                resultados_rodada.append(resultado)
                conteudos.append({k: v for k, v in resultado.items() if not k.startswith("_")})
            mensagens += self.ollama.mensagens_resultados(chamadas, conteudos)
            if resultados_rodada and all(r.get("_direta") for r in resultados_rodada):
                # o resultado já é a resposta: fala direto, sem outra ida ao modelo
                direto = True
                texto_final = " ".join(r["resumo"].strip() for r in resultados_rodada if r.get("resumo", "").strip())
                if saida and texto_final:
                    saida.alimentar(" " + texto_final + " ")
                if texto_rodada and texto_final:
                    texto_final = f"{texto_rodada} {texto_final}"
                elif texto_rodada:
                    texto_final = texto_rodada
                break
            if repetida:
                break

        if not texto_final and not direto:
            resumos = [r["resumo"] for r in ctx.resultados if r.get("resumo")]
            texto_final = " ".join(resumos[-2:]) if resumos else ("Cancelado." if self._cancelar.is_set() else "Pronto.")
            if saida and not saida.falou:
                saida.alimentar(texto_final + " ")
        if saida:
            saida.finalizar()
        if primeiro_texto is not None:
            log.info("%s (%s): primeiro texto em %d ms", self.nome_cerebro, modelo or self.ollama.modelo,
                     round((primeiro_texto - inicio) * 1000))
        self._registrar(texto, texto_final)
        return texto_final

    def _registrar(self, pergunta: str, resposta: str) -> None:
        self.historico.append({"role": "user", "content": pergunta})
        self.historico.append({"role": "assistant", "content": resposta or "(ação executada)"})
        self.historico = self.historico[-self.HISTORICO_MAX:]
        self._salvar_historico()

    def _carregar_historico(self) -> list[dict[str, str]]:
        """A conversa sobrevive a reinícios (o histórico vale por algumas horas)."""
        try:
            dados = json.loads(self._arquivo_historico.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if time.time() - float(dados.get("atualizado", 0)) > self.OCIOSO_REINICIA:
            return []
        mensagens = [m for m in dados.get("mensagens", []) if m.get("role") in ("user", "assistant")
                     and isinstance(m.get("content"), str)]
        return mensagens[-self.HISTORICO_MAX:]

    def _salvar_historico(self) -> None:
        try:
            tmp = self._arquivo_historico.with_suffix(".tmp")
            tmp.write_text(json.dumps({"atualizado": time.time(), "mensagens": self.historico}, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(self._arquivo_historico)
        except OSError as erro:
            log.warning("Não consegui salvar o histórico da conversa: %s", erro)

    def limpar_historico(self) -> None:
        self.historico.clear()
        self._salvar_historico()

    def _sistema(self, ctx: Contexto) -> str:
        """Prompt de sistema estável (sem hora): permite o cache de prompt do Ollama."""
        prefs = self.app.prefs
        nome = prefs.get("nome") or "seu usuário"
        rotinas = ", ".join(r.nome for r in self.app.rotinas.listar()) or "nenhuma"
        layouts = getattr(self.app, "layouts", None)
        return PERSONA.format(
            nome=nome,
            tratamento=prefs.get("tratamento") or "chefe",
            estilo=ESTILO_VOZ if ctx.canal == "voz" else ESTILO_TEXTO,
            cidade=prefs.get("cidade_rotulo") or prefs.get("cidade") or "não definida (pergunte se precisar)",
            rotinas=rotinas,
            layouts=", ".join(layouts.nomes()) if layouts else "nenhum",
            memoria=self.app.memoria.para_prompt(),
        )
