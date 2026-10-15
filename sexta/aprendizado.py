"""Aprendizado: episódios, correções, verificação das ações e a consolidação diária da memória.

- Todo pedido vira um episódio na memória (o que foi pedido, ferramentas, deu certo ou não).
- Correções do usuário ("não era isso", "você errou") marcam o último episódio como errado e
  viram uma lição (escrita pelo cérebro rápido, em segundo plano).
- Ações com verificação (abrir um programa, fechar, volume) são conferidas alguns segundos depois,
  em segundo plano: se não aconteceu, ela avisa e o episódio fica marcado como falho.
- Às 3h (ou na partida, se passou mais de um dia), a memória é consolidada.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable

from .util.texto import normalizar

log = logging.getLogger(__name__)

HORA_CONSOLIDAR = 3

_CORRECAO = re.compile(
    r"^(nao )?(era|e) (isso )?nao\b|^nao (era|e) (isso|esse|essa|o que eu (pedi|falei|queria))|"
    r"^(voce|vc) (errou|se enganou|fez errado|entendeu errado)|^(ta|esta|ficou) errado|^errado\b|"
    r"^nao foi isso|^nao (abriu|funcionou|deu certo|fechou|mudou)|^(isso )?nao funcionou|"
    r"^nao,? (eu )?(pedi|falei|disse|quis dizer)\b|^(eu )?(pedi|falei|disse) (outra coisa|pra |para )"
)
_APRENDE = re.compile(r"^(aprende|aprenda|lembra|lembre) (que |isso: |isso )?(quando|sempre que|toda vez que) (.+)$")


def e_correcao(texto: str) -> bool:
    t = normalizar(texto)
    t = re.sub(r"^(sexta feira |sexta )", "", t)
    return bool(_CORRECAO.search(t))


class Aprendizado:
    def __init__(self, app) -> None:
        self.app = app
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self.ultimo_episodio: int | None = None
        # extensões que querem ver cada pedido resolvido: funcao(pedido, ctx, caminho, resposta)
        self.ouvintes: list = []

    # ------------------------------------------------------------------ episódios
    def registrar(self, pedido: str, ctx, caminho: str, resposta: str, ms: int) -> None:
        memoria = self.app.memoria
        try:
            episodio = memoria.registrar_episodio(pedido, canal=ctx.canal, caminho=caminho,
                                                  ferramentas=ctx.resultados, resposta=resposta, ms=ms)
        except Exception:  # noqa: BLE001 - a memória nunca pode quebrar um pedido
            log.exception("Não consegui registrar o episódio")
            return
        self.ultimo_episodio = episodio
        for ouvinte in list(self.ouvintes):
            try:
                ouvinte(pedido, ctx, caminho, resposta)
            except Exception:  # noqa: BLE001
                log.exception("Erro num ouvinte do aprendizado")
        for r in ctx.resultados:
            verificacao = r.get("_verificar")
            if callable(verificacao):
                self._conferir_depois(episodio, r.get("ferramenta", ""), verificacao, ctx.canal)

    def corrigir(self, texto: str) -> None:
        """O usuário disse que a última resposta estava errada: marca e aprende (em segundo plano)."""
        memoria = self.app.memoria
        anterior = memoria.ultimo_episodio()
        if not anterior:
            return
        memoria.marcar_episodio(anterior["id"], False, nota=f"usuário corrigiu: {texto}")

        def escrever_licao() -> None:
            ferr = ", ".join(f"{f['nome']} ({'ok' if f['ok'] else 'falhou'})" for f in anterior["ferramentas"]) or "nenhuma"
            sistema = ("Você ajuda uma assistente pessoal a aprender com os erros. Escreva UMA lição curta e prática "
                       "(uma frase, no formato 'Quando o usuário pedir ..., ...') para ela acertar da próxima vez. "
                       "Responda só com a frase. Se não der para tirar uma lição útil, responda NADA.")
            texto_ia = (f"Pedido: {anterior['pedido']}\nO que ela fez: {anterior['resposta']}\nFerramentas: {ferr}\n"
                        f"Correção do usuário: {texto}")
            try:
                licao = self.app.agente.completar(sistema, texto_ia).strip().strip('"')
            except Exception as erro:  # noqa: BLE001
                log.info("Sem lição desta correção: %s", erro)
                return
            if licao and "NADA" not in licao.upper()[:8] and len(licao) < 400:
                memoria.aprender("licao", licao, etiquetas=[f["nome"] for f in anterior["ferramentas"]],
                                 origem="correcao")
                self.app.barramento.publicar("aprendizado", categoria="licao", texto=licao)

        threading.Thread(target=escrever_licao, name="licao", daemon=True).start()

    def regra_do_usuario(self, texto: str) -> str | None:
        """'Aprende que quando eu falar X, é Y' vira uma lição na hora."""
        t = normalizar(texto)
        t = re.sub(r"^(sexta feira |sexta )", "", t)
        m = _APRENDE.match(t)
        if not m:
            return None
        # guarda com a grafia original (sem o começo "aprende que")
        original = re.sub(r"^\s*(sexta[- ]feira,?\s*)?(aprende|aprenda|lembra|lembre)\s+(que\s+|isso:?\s+)?", "",
                          texto.strip(), flags=re.I)
        self.app.memoria.aprender("licao", original[0].upper() + original[1:], origem="usuario")
        return "Aprendido. Vou fazer assim daqui para frente."

    # ------------------------------------------------------------------ verificação
    def _conferir_depois(self, episodio: int, ferramenta: str, verificacao: Callable[[], tuple[bool, str] | None],
                         canal: str) -> None:
        def conferir() -> None:
            try:
                resultado = verificacao()
            except Exception as erro:  # noqa: BLE001
                log.info("Verificação de %s falhou: %s", ferramenta, erro)
                return
            if not resultado:
                return
            ok, motivo = resultado
            self.app.atividades.anotar({"ferramenta": ferramenta, "situacao": "conferida" if ok else "nao_confirmada",
                                        "resumo": motivo, "canal": canal, "argumentos": {}})
            if ok:
                return
            self.app.memoria.marcar_episodio(episodio, False, nota=motivo)
            self.app.barramento.publicar("aviso", nivel="alerta", texto=motivo)
            if canal == "voz" and not self.app.fala.falando_ou_na_fila():
                self.app.fala.falar(motivo)

        threading.Thread(target=conferir, name=f"conferir-{ferramenta}", daemon=True).start()

    # ------------------------------------------------------------------ consolidação
    def iniciar(self) -> None:
        self._thread = threading.Thread(target=self._laco, name="consolidar-memoria", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()

    def _laco(self) -> None:
        if self._parar.wait(120):
            return
        while not self._parar.is_set():
            ultima = float(self.app.memoria._meta("consolidado_em") or 0)
            agora = datetime.now()
            atrasada = time.time() - ultima > 30 * 3600
            hora_certa = agora.hour == HORA_CONSOLIDAR and time.time() - ultima > 20 * 3600
            if (hora_certa or atrasada) and not self.app.agente.ocupado():
                self.consolidar()
            if self._parar.wait(600):
                return

    def consolidar(self) -> dict[str, Any]:
        log.info("Consolidando a memória")
        try:
            novos = self.app.memoria.consolidar(lambda s, t: self.app.agente.completar(s, t, rapido=False))
        except Exception:  # noqa: BLE001
            log.exception("Consolidação da memória falhou")
            return {}
        log.info("Memória consolidada: %s", novos)
        self.app.barramento.publicar("aprendizado", categoria="consolidacao", novos=novos)
        return novos

    def resumo_do_dia(self) -> str:
        """'O que você aprendeu hoje?'"""
        inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        memoria = self.app.memoria
        itens = memoria.itens(desde=inicio, limite=30)
        eps = memoria.episodios(inicio, limite=500)
        partes = []
        if eps:
            erros = sum(1 for e in eps if not e["ok"])
            partes.append(f"Hoje atendi {len(eps)} pedido{'s' if len(eps) > 1 else ''}"
                          + (f", {erros} com problema" if erros else ", todos certos") + ".")
        por_tipo = {"fato": [], "licao": [], "conhecimento": []}
        for i in itens:
            por_tipo[i["tipo"]].append(i["texto"])
        if por_tipo["fato"]:
            partes.append("Sobre você: " + "; ".join(por_tipo["fato"][:3]) + ".")
        if por_tipo["licao"]:
            partes.append("Lições: " + "; ".join(por_tipo["licao"][:3]) + ".")
        if por_tipo["conhecimento"]:
            partes.append(f"E guardei {len(por_tipo['conhecimento'])} conhecimento"
                          f"{'s' if len(por_tipo['conhecimento']) > 1 else ''} novo"
                          f"{'s' if len(por_tipo['conhecimento']) > 1 else ''}: " + por_tipo["conhecimento"][0] + ".")
        if len(partes) <= 1:
            partes.append("Nada de novo aprendido hoje ainda.")
        return " ".join(partes)

    def o_que_fez(self, limite: int = 5) -> tuple[str, list[dict]]:
        """'O que você fez?' / 'deu certo?': últimas ações com o resultado."""
        eps = [e for e in self.app.memoria.episodios(limite=limite + 3) if e["ferramentas"]][:limite]
        if not eps:
            return "Ainda não fiz nenhuma ação por aqui.", []
        ultimo = eps[0]
        nomes = ", ".join(f["nome"] for f in ultimo["ferramentas"])
        if ultimo["ok"]:
            texto = f"O último pedido, \"{ultimo['pedido']}\", deu certo ({nomes})."
        else:
            texto = f"O último pedido, \"{ultimo['pedido']}\", não deu certo" + (f": {ultimo['nota']}" if ultimo["nota"] else ".")
        falhas = [e for e in eps[1:] if not e["ok"]]
        if falhas:
            texto += f" Antes disso, {len(falhas)} com problema: {falhas[0]['pedido']}."
        return texto, eps
