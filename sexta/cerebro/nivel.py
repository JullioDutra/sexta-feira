"""Quanto um pedido exige, decidido na hora (sem IA, em microssegundos).

- ``simples``: pergunta curta ou comando que os atalhos não pegaram → cérebro rápido, sem pensar;
- ``complexo``: análise, planejamento, explicação, texto longo, código → cérebro principal pensando,
  e ela fala um "deixa eu ver" na hora para o silêncio não parecer travamento.
"""

from __future__ import annotations

import re

from ..util.texto import normalizar

SIMPLES, COMPLEXO = "simples", "complexo"

_COMPLEXO = re.compile(
    r"\b(planej|analis|explica|expliq|por que|porque|compar|escrev|redig|resum|traduz|corrig|ideia|sugest|"
    r"cri[ae] uma rotina|o que (voce )?acha|como (eu )?(faco|posso|funciona)|me ajuda|estrategia|calcul|"
    r"codigo|programa(r|cao)|script|funcao|bug|erro no|debug|arquitetura|projeto|engenharia|seguranca|"
    r"vulnerab|investig|pesquis(a|e) (a fundo|sobre)|estud|aprend|ensina|diferenca entre|vale a pena|"
    r"melhor (opcao|forma|jeito|maneira)|pros e contras|passo a passo|detalh|revis[ae]|otimiz|melhor[ae])"
)
_AREA_TRANSFERENCIA = re.compile(
    r"\b(copiei|copiado|copiada|area de transferencia|clipboard|o que (eu )?copi|texto que (eu )?copi|isso que copi)"
)
_SO_ACAO = re.compile(r"^(abre|abra|fecha|feche|toca|toque|liga|ligue|desliga|desligue|aumenta|diminui|muda|"
                      r"coloca|poe|mostra|mostre|minimiza|maximiza|pausa|para|silencia|lembra|me lembra|anota)\b")


def classificar(texto: str) -> str:
    t = normalizar(texto)
    t = re.sub(r"^(sexta feira |sexta )", "", t)
    palavras = len(t.split())
    if _AREA_TRANSFERENCIA.search(t):
        return COMPLEXO
    if _SO_ACAO.match(t) and palavras <= 16:
        return SIMPLES
    if palavras > 22 or _COMPLEXO.search(t):
        return COMPLEXO
    return SIMPLES
