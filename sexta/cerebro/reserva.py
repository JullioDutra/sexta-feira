"""Cérebro com reserva: se o principal falha (sem crédito, limite, rede), o reserva responde.

A troca só acontece quando o principal falha *antes* de mandar qualquer texto, para a resposta não
sair pela metade de um e pela metade de outro. Depois de uma falha, o principal fica de lado por
alguns minutos e os pedidos vão direto para o reserva.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterator

from .ollama import ErroOllama

log = logging.getLogger(__name__)

PAUSA_S = 180


class CerebroComReserva:
    def __init__(self, principal, reserva, modelo_rapido_reserva: str = "") -> None:
        self.principal = principal
        self.reserva = reserva
        self.modelo_rapido_reserva = modelo_rapido_reserva
        self._pausado_ate = 0.0

    # o resto (modelo, url, nome, aquecer, verificar...) é do principal
    def __getattr__(self, nome: str) -> Any:
        return getattr(self.principal, nome)

    @property
    def usando_reserva(self) -> bool:
        return time.time() < self._pausado_ate

    def _falhou(self, erro: Exception) -> None:
        log.warning("Cérebro principal falhou (%s); usando o reserva por %d min", erro, PAUSA_S // 60)
        self._pausado_ate = time.time() + PAUSA_S

    def _modelo_reserva(self, modelo: str | None) -> str | None:
        # o modelo rápido do principal não existe no reserva
        if modelo and modelo != getattr(self.principal, "modelo", None):
            return self.modelo_rapido_reserva or None
        return None

    def conversar(self, mensagens: list[dict[str, Any]], ferramentas=None, cancelado=lambda: False, *,
                  modelo: str | None = None, max_tokens: int | None = None, pensar: bool = False
                  ) -> Iterator[dict[str, Any]]:
        if not self.usando_reserva:
            houve_texto = False
            try:
                for evento in self.principal.conversar(mensagens, ferramentas, cancelado, modelo=modelo,
                                                       max_tokens=max_tokens, pensar=pensar):
                    if evento["tipo"] == "texto":
                        houve_texto = True
                    yield evento
                return
            except ErroOllama as erro:
                if houve_texto:
                    raise
                self._falhou(erro)
        yield from self.reserva.conversar(mensagens, ferramentas, cancelado, modelo=self._modelo_reserva(modelo),
                                          max_tokens=max_tokens, pensar=pensar)

    def _com_reserva(self, metodo: str, *args, modelo: str | None = None, **kwargs):
        if not self.usando_reserva:
            try:
                return getattr(self.principal, metodo)(*args, modelo=modelo, **kwargs)
            except ErroOllama as erro:
                self._falhou(erro)
        return getattr(self.reserva, metodo)(*args, modelo=self._modelo_reserva(modelo), **kwargs)

    def completar(self, sistema: str, texto: str, modelo: str | None = None) -> str:
        return self._com_reserva("completar", sistema, texto, modelo=modelo)

    def visao(self, pergunta: str, imagens_b64: list[str], sistema: str = "", modelo: str | None = None) -> str:
        return self._com_reserva("visao", pergunta, imagens_b64, sistema, modelo=modelo)

    # o formato da volta das ferramentas depende de quem respondeu: os dois cérebros com
    # formato da API do Claude (Claude e FreeLLMAPI) são compatíveis; Ollama como reserva
    # de Claude só serve para respostas sem ferramentas (veja Agente).
    def mensagem_assistente(self, texto: str, chamadas: list[dict], bruto: Any) -> dict[str, Any]:
        alvo = self.reserva if self.usando_reserva else self.principal
        return alvo.mensagem_assistente(texto, chamadas, bruto)

    def mensagens_resultados(self, chamadas: list[dict], conteudos: list[dict]) -> list[dict[str, Any]]:
        alvo = self.reserva if self.usando_reserva else self.principal
        return alvo.mensagens_resultados(chamadas, conteudos)
