"""Atalhos rápidos: comandos curtos e frequentes resolvidos sem passar pela IA.

Respondem em milissegundos ("pausa", "volume 40", "que horas são", "modo trabalho").
Tudo que não casar aqui segue para o modelo de linguagem.
"""

from __future__ import annotations

import re
from datetime import datetime

from ..util.tempo import data_extenso, formatar_hora
from ..util.texto import normalizar

_PAUSAR = re.compile(r"^(pausa|pausar|pause|da pause|continua|continuar|retoma|retomar|play|despausa|solta o som)"
                     r"( a| o)?( musica| video| som| midia)?$")
_PROXIMA = re.compile(r"^(proxima|proximo|pula|pular|passa|avanca)( a| o)?( musica| faixa| video)?$")
_ANTERIOR = re.compile(r"^(anterior|volta|voltar)( a| o)?( musica| faixa| video)?( anterior)?$")
_VOLUME_N = re.compile(r"^(?:coloca |deixa |poe |bota )?(?:o )?volume (?:em |para |pra |no |a )?(\d{1,3})(?: por cento|%)?$")
_VOLUME_MAIS = re.compile(r"^(aumenta|sobe|aumentar|subir)( o)? (volume|som)( um pouco)?$|^mais alto$")
_VOLUME_MENOS = re.compile(r"^(abaixa|diminui|baixa|abaixar|diminuir)( o)? (volume|som)( um pouco)?$|^mais baixo$")
_MUDO = re.compile(r"^(muta|mutar|silencia|silenciar|mudo|tira o som)( o pc| o computador| o som)?$")
_DESMUDO = re.compile(r"^(desmuta|desmutar|tira do mudo|tira o mudo|volta o som)$")
_HORAS = re.compile(r"^(que horas sao|que hora e|me diz as horas|horas|que horas e agora|sabe que horas sao)$")
_DATA = re.compile(r"^(que dia e hoje|qual a data de hoje|qual e a data|que dia e|data de hoje|hoje e que dia)$")
_PRINT = re.compile(r"^(tira|tirar|faz|fazer|da) (um |uma )?(print|captura)( da tela)?$|^(print|captura de tela|printa a tela)$")
_BLOQUEAR = re.compile(r"^(bloqueia|bloquear|trava|travar)( o)? (computador|pc|tela)$")
_LIMPAR = re.compile(r"^(fecha|fechar|limpa|limpar|some com|esconde)( os| todos os)? (hologramas|a tela|paineis)$")
_CANCELAR = re.compile(r"^(cancela|cancelar|esquece|deixa pra la|deixa|para|pare|chega|silencio|nada nao|nada)$")
_OBRIGADO = re.compile(r"^(obrigad[oa]|valeu|brigad[oa]|muito obrigad[oa]|obrigado sexta feira|valeu sexta feira)$")
_CLIMA = re.compile(r"^(clima|tempo|previsao do tempo|como esta o tempo|como ta o tempo|como esta o clima|qual o clima|"
                    r"como esta o tempo hoje|previsao)( hoje| agora)?$")


def tentar(texto: str, ctx) -> str | None:
    """Retorna a resposta falada se o comando foi resolvido aqui; senão ``None``."""
    app = ctx.app
    t = normalizar(texto).replace(" por favor", "").strip()
    if not t:
        return None
    tratamento = app.prefs.get("tratamento") or "chefe"
    executar = app.registro.executar

    if _CANCELAR.match(t):
        app.fala.parar()
        return ""
    if _OBRIGADO.match(t):
        return f"Às ordens, {tratamento}."
    if _HORAS.match(t):
        agora = datetime.now()
        return f"São {formatar_hora(agora)}."
    if _DATA.match(t):
        return f"Hoje é {data_extenso(datetime.now())}."
    if _PAUSAR.match(t):
        executar("controlar_midia", {"acao": "tocar_pausar"}, ctx)
        return ""
    if _PROXIMA.match(t):
        executar("controlar_midia", {"acao": "proxima"}, ctx)
        return ""
    if _ANTERIOR.match(t):
        executar("controlar_midia", {"acao": "anterior"}, ctx)
        return ""
    m = _VOLUME_N.match(t)
    if m:
        return executar("ajustar_volume", {"acao": "definir", "valor": int(m.group(1))}, ctx)["resumo"]
    if _VOLUME_MAIS.match(t):
        return executar("ajustar_volume", {"acao": "aumentar"}, ctx)["resumo"]
    if _VOLUME_MENOS.match(t):
        return executar("ajustar_volume", {"acao": "diminuir"}, ctx)["resumo"]
    if _MUDO.match(t):
        return executar("ajustar_volume", {"acao": "mudo"}, ctx)["resumo"]
    if _DESMUDO.match(t):
        return executar("ajustar_volume", {"acao": "tirar_mudo"}, ctx)["resumo"]
    if _PRINT.match(t):
        return executar("computador", {"acao": "print"}, ctx)["resumo"]
    if _BLOQUEAR.match(t):
        return executar("computador", {"acao": "bloquear"}, ctx)["resumo"]
    if _LIMPAR.match(t):
        executar("holograma", {"acao": "fechar_todos"}, ctx)
        return "Tela limpa."
    if _CLIMA.match(t) and app.prefs.get("cidade"):
        return executar("obter_clima", {}, ctx)["resumo"]

    rotina = app.rotinas.encontrar_por_frase(t)
    if rotina is not None:
        return executar("rotina", {"acao": "executar", "nome": rotina.nome}, ctx)["resumo"]
    return None
