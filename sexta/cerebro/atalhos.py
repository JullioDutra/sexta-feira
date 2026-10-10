"""Atalhos rápidos: comandos frequentes resolvidos sem passar pela IA.

Respondem em milissegundos ("pausa", "volume 40", "abre o Spotify", "fecha o Chrome",
"brilho 70", "liga o Wi-Fi", "coloca o VS Code na esquerda", "analisa a tela"...).
Pedidos compostos também valem: "abre o Spotify e coloca volume 30" — desde que
cada parte seja um atalho; senão o pedido inteiro vai para a IA (nada roda pela metade).
Tudo que não casar aqui segue para o modelo de linguagem.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable

from ..util.tempo import data_extenso, formatar_hora
from ..util.texto import normalizar

Plano = Callable[[], str]

_ART = r"(?:o |a |os |as |no |na |do |da )?"

_PAUSAR = re.compile(r"^(pausa|pausar|pause|da pause|continua|continuar|retoma|retomar|play|despausa|solta o som)"
                     r"( a| o)?( musica| video| som| midia)?$")
_PROXIMA = re.compile(r"^(proxima|proximo|pula|pular|passa|avanca)( a| o)?( musica| faixa| video)?$")
_ANTERIOR = re.compile(r"^(anterior|volta|voltar)( a| o)?( musica| faixa| video)?( anterior)?$")
_VOLUME_N = re.compile(r"^(?:coloca |deixa |poe |bota |muda )?(?:o )?volume (?:em |para |pra |no |a )?(\d{1,3})(?: por cento|%)?$")
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

# -- Fase 1 --------------------------------------------------------------------------
_HOLOGRAMA = re.compile(r"^(mostra|abre|mostrar|abrir|exibe) " + _ART +
                        r"(globo|relogio|sistema|lembretes|rotinas|camera|noticias|clima|atividades|registro de atividades)$")
_ATIVIDADES = re.compile(r"^(o que voce fez( hoje)?|o que voce fez no (pc|computador)( hoje)?)$")
_ABRIR = re.compile(r"^(abre|abrir|abra|inicia|iniciar|inicie|executa|abre pra mim|abre para mim) " + _ART + r"(.+)$")
_FECHAR = re.compile(r"^(fecha|fechar|feche|encerra|encerrar|sai do|sair do) " + _ART + r"(.+)$")
_FECHAR_TRAVADOS = re.compile(r"^(fecha|fechar|mata|encerra)( os| o| as)? (programas? )?(travados?|que (travou|travaram|nao responde.*))$")
_FECHAR_JANELA = re.compile(r"^(fecha|fechar) a janela (do |da |de )?(.+)$")
_PESQUISAR = re.compile(r"^(pesquisa|pesquisar|pesquise|busca no google|procura no google|googla|joga no google) (?:sobre |por )?(.+?)"
                        r"(?: no (google|youtube|maps|mapa|imagens))?$")
_TOCAR_YT = re.compile(r"^(toca|tocar|coloca|bota|poe) (.+?) no youtube$")
_TOCAR = re.compile(r"^(toca|tocar|toque) (?:a musica |musica |um |uma |o |a )?(.+)$")
_MINIMIZAR_TUDO = re.compile(r"^(minimiza|minimizar|esconde) (tudo|todas as janelas)$|^(mostra|mostrar|vai pra|vai para) (a )?area de trabalho$")
_JANELA_ACAO = re.compile(r"^(minimiza|minimizar|maximiza|maximizar|foca|focar|foca no|foca na|traz|traga|"
                          r"restaura|restaurar) " + _ART + r"(.+?)( pra frente| para frente)?$")
_ENCAIXAR = re.compile(r"^(coloca|poe|bota|joga|manda|encaixa|move|deixa) " + _ART + r"(.+?) (na|a|para a|pra|pro|no lado|do lado) "
                       r"(esquerda|direita|cima|baixo|lado esquerdo|lado direito)$")
_LADO_A_LADO = re.compile(r"^(coloca|poe|bota|deixa|encaixa) " + _ART + r"(.+?) e " + _ART + r"(.+?) lado a lado$")
_MONITOR = re.compile(r"^(manda|joga|move|passa|leva|coloca) " + _ART + r"(.+?) (pro|para o|no|ao|pra) "
                      r"(outro|segundo|proximo|primeiro|terceiro) monitor$")
_SALVAR_LAYOUT = re.compile(r"^(salva|salvar|guarda|grava) (esse|este|o|as janelas como|a disposicao como)? ?layout (como |de nome |chamado )?(.+)$")
_LAYOUT = re.compile(r"^(layout|modo|ativa o layout|aplica o layout) (.+)$")
_BRILHO_N = re.compile(r"^(?:coloca |deixa |poe |bota |muda )?(?:o )?brilho (?:em |para |pra |no |a )?(\d{1,3})(?: por cento|%)?$")
_BRILHO_MAIS = re.compile(r"^(aumenta|sobe|aumentar)( o)? brilho( da tela)?$|^(mais claro|tela mais clara)$")
_BRILHO_MENOS = re.compile(r"^(abaixa|diminui|baixa|diminuir)( o)? brilho( da tela)?$|^(mais escuro|tela mais escura)$")
_RADIO = re.compile(r"^(liga|ligar|ativa|ativar|desliga|desligar|desativa|desativar|conecta|desconecta)( o| a)? (wi ?fi|wifi|internet sem fio|bluetooth)$")
_ESCURO = re.compile(r"^((liga|ativa|coloca|ativar|ligar|poe|bota)( o)? )?(modo|tema) (escuro|noturno|dark)$")
_CLARO = re.compile(r"^((liga|ativa|coloca|volta( para| pro| pra)?)( o)? )?(modo|tema) claro$|^(desliga|desativa)( o)? (modo|tema) (escuro|noturno|dark)$")
_PERTURBE = re.compile(r"^((liga|ativa|ligar|ativar|coloca)( o)? )?(modo )?nao (perturbe|incomode|incomodar)$|^silencia( as)? notificacoes$")
_PERTURBE_OFF = re.compile(r"^(desliga|desativa|tira)( o)? (modo )?nao (perturbe|incomode|incomodar)$|^(volta|liga)( as)? notificacoes$")
_PLANO = re.compile(r"^(?:coloca |poe |deixa |muda |ativa |liga )?(?:o pc |o computador )?(?:em |no |para |pra |o )?"
                    r"(?:modo |plano |plano de energia )(desempenho maximo|maximo desempenho|alto desempenho|desempenho|"
                    r"economia de energia|economia|economico|equilibrado|balanceado|turbo)$")
_SAIDA_AUDIO = re.compile(r"^(muda|troca|passa|coloca|joga|manda)( o)? (som|audio|saida( de audio| de som)?) (para|pro|pra|no|na|nos|nas) "
                          + _ART + r"(.+)$")
_PESADO = re.compile(r"^(o que (esta|ta) (pesando|travando|deixando o (pc|computador) lento|consumindo)( mais)?( o pc| no pc| a memoria| a ram| o processador| a cpu| a gpu| a placa de video)?|"
                     r"(qual|quais) (programa|programas|app|apps) (esta|estao|ta|tao) (pesando|consumindo|usando)( mais)?( memoria| ram| cpu| processador| gpu| placa de video)?|"
                     r"consumo de (memoria|ram|cpu|processador|gpu|placa de video)( por app| por programa)?|"
                     r"o que (esta|ta) usando( mais)? (a )?(memoria|ram|cpu|processador|gpu|placa de video))$")
_RECENTES = re.compile(r"^((mostra|quais|lista|abre)( os| meus)? )?(arquivos|documentos) recentes$|^(o que|que) eu baixei( hoje| recentemente)?$|"
                       r"^(ultimos|meus ultimos) (arquivos|downloads)$")
_ORGANIZAR = re.compile(r"^(organiza|organizar|arruma|arrumar|ajeita)( a| minha)?( pasta)?( de)? downloads( por (tipo|data|mes))?$")
_TELA = re.compile(r"^(analisa|analise|olha|ve|le|leia|explica|examina)( pra mim)? (a |minha |essa |esta |o que tem na |o que ta na )?tela$|"
                   r"^o que (tem|esta|ta|aparece) na (minha )?tela$|^(que|qual) (erro|e esse erro|erro e esse)( e esse| na tela)?$")
_CAMERA = re.compile(r"^(o que e isso|que objeto e esse|o que eu (to|estou) segurando|"
                     r"(le|leia) (esse|este|o) (papel|documento|bilhete|texto)( aqui)?)$")
_FECHAR_HOLO = re.compile(r"^(fecha|fechar|esconde|tira) " + _ART +
                          r"(globo|relogio|sistema|lembretes|rotinas|camera|noticias|clima|atividades|registro de atividades)$")
_NAO_TOCAR = {"proxima", "anterior", "musica", "de novo", "novamente", "o som", "som"}
_JORNAL = re.compile(r"^((abre|mostra|abrir|mostrar|traz) (o )?)?(jornal|central de noticias)( de hoje)?$")
_TEMA_ADD = re.compile(r"^(me )?(avisa|avise|alerta|notifica)( me)? (quando|se|assim que) (sair|tiver|aparecer|publicarem) "
                       r"(alguma |uma )?(noticia|novidade|novidades|noticias) (de|do|da|dos|das|sobre) (.+)$")
_TEMA_DEL = re.compile(r"^(para|pare|deixa) de (me )?(avisar|acompanhar|alertar) (sobre |de |do |da )?(.+)$")
_NUMEROS = {"primeira": 1, "1": 1, "segunda": 2, "2": 2, "terceira": 3, "3": 3, "quarta": 4, "4": 4, "quinta": 5,
            "5": 5, "sexta": 6, "6": 6}
_NOTICIA_N = re.compile(r"^(le|leia|ler|resume|salva|salvar|guarda) (a )?(primeira|segunda|terceira|quarta|quinta|sexta|[1-6]|"
                        r"noticia (?:numero )?[1-6])( noticia)?( de| da| do| em)?( tecnologia| brasil| destaques| temas| salvas)?$")
_TAREFA_NOVA = re.compile(r"^(anota|anotar|adiciona (a |uma )?tarefa|cria (a |uma )?tarefa|nova tarefa|tarefa)(:| que| pra mim| para mim)? (?!na tela)(.+)$")
_TAREFAS_VER = re.compile(r"^(quais (sao )?(as )?minhas tarefas|minhas tarefas|o que (eu )?tenho (pra|para) fazer( hoje)?|"
                          r"(mostra|abre) (o |as |meu |minhas )?(quadro|tarefas|kanban))$")
_TAREFA_FEITA = re.compile(r"^(conclui|concluir|terminei|finalizei|acabei|marca como feita|marca como feito|feito|ja fiz)( a tarefa| o| a)? (.+?)( como feita| como feito)?$")
_PLANEJA = re.compile(r"^(planeja|planejar|organiza|monta) (o |meu |o meu )?dia$")
_REVISAO = re.compile(r"^(revisao do dia|faz a revisao do dia|como foi (o meu|meu) dia)$")
_SEMANA = re.compile(r"^(plano da semana|planeja (a |minha )?semana|como esta (a |minha )?semana)$")
_FOCO = re.compile(r"^(pomodoro|modo foco|foco)( de| por)? ?(\d{1,3})? ?(min|minutos)?$")
_FOCO_FIM = re.compile(r"^(encerra|encerrar|para|parar|termina|terminar|sai do|sair do|desliga) (o )?(foco|pomodoro|modo foco)$")
_FOCO_PAUSA = re.compile(r"^(pausa|pausar) (o )?(foco|pomodoro)$")
_FOCO_RETOMA = re.compile(r"^(retoma|retomar|continua|continuar|volta) (o |ao )?(foco|pomodoro)$")
_FOCO_STATUS = re.compile(r"^(quanto (tempo )?falta( do| no| pro)? (foco|pomodoro)|quanto falta)$")
_PALAVRAS_ARQUIVO = re.compile(r"\b(pdf|arquivo|arquivos|planilha|documento|foto|fotos|imagem|video|contrato|apresentacao)\b")


def _janela_aberta(nome: str) -> bool:
    from ..habilidades import janelas, windows

    try:
        return janelas.encontrar(nome) is not None
    except (windows.NaoSuportado, OSError):
        return False


def tentar(texto: str, ctx) -> str | None:
    """Retorna a resposta falada se o comando foi resolvido aqui; senão ``None``."""
    t = normalizar(texto).replace(" por favor", "").strip()
    t = re.sub(r"^(sexta feira|sexta) ", "", t)
    if not t:
        return None
    plano = _casar(t, ctx, texto)
    if plano is not None:
        return plano()
    partes = [p.strip() for p in re.split(r" e depois | depois | e tambem | e ", t) if p.strip()]
    if len(partes) < 2:
        return None
    planos = [_casar(p, ctx) for p in partes]
    if not all(planos):
        return None
    respostas = [p() for p in planos]  # type: ignore[misc]
    pendentes = [r for r in respostas if r.startswith("Confirma")]
    texto_final = " ".join(r for r in respostas if r and r not in pendentes)
    return (texto_final + " " + " ".join(pendentes)).strip() if pendentes else texto_final


def _sem_comando(original: str) -> str:
    """ "Sexta-Feira, anota: terminar o Sistema até sexta" -> "terminar o Sistema até sexta" (com acentos)."""
    return re.sub(r"^\W*(?:(?:ei\W+)?sexta(?:[\s-]*feira)?\W+)?(?:anota|anotar|adiciona(?: a| uma)? tarefa|cria(?: a| uma)? tarefa|"
                  r"nova tarefa|tarefa)(?:\s*:|\s+que|\s+pra mim|\s+para mim)?\s*", "", original, flags=re.I).strip()


def _casar(t: str, ctx, original: str | None = None) -> Plano | None:
    """Reconhece o comando e devolve uma função que o executa (sem executar nada ainda)."""
    app = ctx.app
    tratamento = app.prefs.get("tratamento") or "chefe"
    reg = app.registro

    def rodar(nome: str, args: dict | None = None, padrao: str | None = None) -> Plano:
        def fazer() -> str:
            resultado = reg.executar(nome, args or {}, ctx)
            return padrao if padrao is not None and resultado.get("ok") else resultado.get("resumo", "")
        return fazer

    def falar(texto: str) -> Plano:
        return lambda: texto

    if _CANCELAR.match(t):
        def parar() -> str:
            app.fala.parar()
            return ""
        return parar
    if _OBRIGADO.match(t):
        return falar(f"Às ordens, {tratamento}.")
    if _HORAS.match(t):
        return lambda: f"São {formatar_hora(datetime.now())}."
    if _DATA.match(t):
        return lambda: f"Hoje é {data_extenso(datetime.now())}."
    if _PAUSAR.match(t):
        return rodar("controlar_midia", {"acao": "tocar_pausar"}, "")
    if _PROXIMA.match(t):
        return rodar("controlar_midia", {"acao": "proxima"}, "")
    if _ANTERIOR.match(t):
        return rodar("controlar_midia", {"acao": "anterior"}, "")
    if m := _VOLUME_N.match(t):
        return rodar("ajustar_volume", {"acao": "definir", "valor": int(m.group(1))})
    if _VOLUME_MAIS.match(t):
        return rodar("ajustar_volume", {"acao": "aumentar"})
    if _VOLUME_MENOS.match(t):
        return rodar("ajustar_volume", {"acao": "diminuir"})
    if _MUDO.match(t):
        return rodar("ajustar_volume", {"acao": "mudo"})
    if _DESMUDO.match(t):
        return rodar("ajustar_volume", {"acao": "tirar_mudo"})
    if _PRINT.match(t):
        return rodar("computador", {"acao": "print"})
    if _BLOQUEAR.match(t):
        return rodar("computador", {"acao": "bloquear"})
    if _LIMPAR.match(t):
        return rodar("holograma", {"acao": "fechar_todos"}, "Tela limpa.")
    if _CLIMA.match(t) and app.prefs.get("cidade"):
        return rodar("obter_clima", {})

    rotina = app.rotinas.encontrar_por_frase(t)
    if rotina is not None:
        return rodar("rotina", {"acao": "executar", "nome": rotina.nome})

    from .. import extensoes  # comandos das extensões (Fases 5 e 6)

    plano = extensoes.atalho(t, ctx, rodar, original)
    if plano is not None:
        return plano

    # -- hologramas e registro
    if m := _HOLOGRAMA.match(t):
        tipo = "atividades" if "atividades" in m.group(2) else m.group(2)
        return rodar("holograma", {"acao": "mostrar", "tipo": tipo})
    if m := _FECHAR_HOLO.match(t):
        tipo = "atividades" if "atividades" in m.group(2) else m.group(2)
        return rodar("holograma", {"acao": "fechar", "tipo": tipo})
    if _ATIVIDADES.match(t):
        return rodar("atividades", {"acao": "resumo_hoje"})

    # -- planejamento
    if m := _TAREFA_NOVA.match(t):
        from ..habilidades.tarefas import interpretar_tarefa

        campos = interpretar_tarefa(_sem_comando(original) if original else m.group(5))
        args = {"acao": "criar", "titulo": campos["titulo"]}
        if campos.get("prazo"):
            args["prazo"] = campos["prazo"].isoformat()
        for chave in ("prioridade", "estimativa", "projeto"):
            if campos.get(chave):
                args[chave] = campos[chave]
        return rodar("tarefas", args)
    if _TAREFAS_VER.match(t):
        return rodar("tarefas", {"acao": "mostrar_quadro"})
    if m := _TAREFA_FEITA.match(t):
        return rodar("tarefas", {"acao": "concluir", "alvo": m.group(3)})
    if _PLANEJA.match(t):
        return rodar("planejar", {"acao": "dia"})
    if _REVISAO.match(t):
        return rodar("planejar", {"acao": "revisao_dia"})
    if _SEMANA.match(t):
        return rodar("planejar", {"acao": "semana"})
    if _FOCO_FIM.match(t):
        return rodar("foco", {"acao": "encerrar"})
    if _FOCO_PAUSA.match(t):
        return rodar("foco", {"acao": "pausar"})
    if _FOCO_RETOMA.match(t):
        return rodar("foco", {"acao": "retomar"})
    if _FOCO_STATUS.match(t) and app.foco.estado():
        return rodar("foco", {"acao": "status"})
    if (m := _FOCO.match(t)) and m.group(3):  # "modo foco" sem minutos fica com o protocolo "modo foco"
        return rodar("foco", {"acao": "iniciar", "minutos": int(m.group(3))})

    # -- jornal
    if _JORNAL.match(t):
        return rodar("jornal", {"acao": "mostrar"})
    if m := _TEMA_ADD.match(t):
        return rodar("jornal", {"acao": "adicionar_tema", "tema": m.group(9)})
    if m := _TEMA_DEL.match(t):
        return rodar("jornal", {"acao": "remover_tema", "tema": m.group(5)})
    if m := _NOTICIA_N.match(t):
        numero = _NUMEROS.get(m.group(3).split()[-1], 1)
        aba = (m.group(6) or " destaques").strip()
        acao = "salvar" if m.group(1).startswith(("salva", "guarda")) else "ler"
        return rodar("jornal", {"acao": acao, "aba": aba, "numero": numero})

    # -- configurações
    if m := _BRILHO_N.match(t):
        return rodar("configuracao", {"item": "brilho", "valor": m.group(1)})
    if _BRILHO_MAIS.match(t):
        return rodar("configuracao", {"item": "brilho", "valor": "mais"})
    if _BRILHO_MENOS.match(t):
        return rodar("configuracao", {"item": "brilho", "valor": "menos"})
    if m := _RADIO.match(t):
        ligar = not m.group(1).startswith(("des",))
        item = "bluetooth" if "bluetooth" in m.group(3) else "wifi"
        return rodar("configuracao", {"item": item, "valor": "ligar" if ligar else "desligar"})
    if _CLARO.match(t):
        return rodar("configuracao", {"item": "modo_escuro", "valor": "desligar"})
    if _ESCURO.match(t):
        return rodar("configuracao", {"item": "modo_escuro", "valor": "ligar"})
    if _PERTURBE_OFF.match(t):
        return rodar("configuracao", {"item": "nao_perturbe", "valor": "desligar"})
    if _PERTURBE.match(t):
        return rodar("configuracao", {"item": "nao_perturbe", "valor": "ligar"})
    if m := _PLANO.match(t):
        return rodar("configuracao", {"item": "plano_energia", "valor": m.group(1)})
    if m := _SAIDA_AUDIO.match(t):
        return rodar("configuracao", {"item": "saida_audio", "valor": m.group(6)})

    # -- processos
    if m := _PESADO.match(t):
        ordem = "gpu" if re.search(r"gpu|placa de video", t) else "ram" if re.search(r"memoria|ram", t) else "cpu"
        return rodar("processos", {"acao": "mais_pesados", "ordem": ordem})
    if _FECHAR_TRAVADOS.match(t):
        return rodar("processos", {"acao": "fechar_travados"})

    # -- arquivos
    if _RECENTES.match(t):
        return rodar("arquivos", {"acao": "recentes"})
    if m := _ORGANIZAR.match(t):
        return rodar("arquivos", {"acao": "organizar_downloads", "por_data": bool(m.group(6) and m.group(6) != "tipo")})

    # -- visão
    if _TELA.match(t):
        return rodar("ver", {"fonte": "tela", "pergunta": "O que está na tela? Se houver um erro, explique."})
    if _CAMERA.match(t):
        pergunta = "Leia o essencial do papel." if t.startswith("le") else "O que é isso que estou mostrando?"
        return rodar("ver", {"fonte": "camera", "pergunta": pergunta})

    # -- janelas
    if _MINIMIZAR_TUDO.match(t):
        return rodar("janelas", {"acao": "minimizar_tudo"})
    if m := _SALVAR_LAYOUT.match(t):
        return rodar("janelas", {"acao": "salvar_layout", "app": m.group(4).strip()})
    if (m := _LAYOUT.match(t)) and app.layouts.obter(m.group(2)) is not None:
        return rodar("janelas", {"acao": "aplicar_layout", "app": m.group(2)})
    if m := _LADO_A_LADO.match(t):
        esquerda, direita = m.group(2), m.group(3)

        def lado_a_lado() -> str:
            r1 = reg.executar("janelas", {"acao": "encaixar", "app": esquerda, "posicao": "esquerda"}, ctx)
            r2 = reg.executar("janelas", {"acao": "encaixar", "app": direita, "posicao": "direita"}, ctx)
            if r1.get("ok") and r2.get("ok"):
                return "Lado a lado."
            return " ".join(r["resumo"] for r in (r1, r2) if not r.get("ok"))
        return lado_a_lado
    if m := _ENCAIXAR.match(t):
        posicao = m.group(4).replace("lado ", "").replace("esquerdo", "esquerda").replace("direito", "direita")
        return rodar("janelas", {"acao": "encaixar", "app": m.group(2), "posicao": posicao})
    if m := _MONITOR.match(t):
        args = {"acao": "mover_monitor", "app": m.group(2)}
        numero = {"primeiro": 1, "segundo": 2, "terceiro": 3}.get(m.group(4))
        if numero:
            args["monitor"] = numero
        return rodar("janelas", args)
    if m := _FECHAR_JANELA.match(t):
        return rodar("janelas", {"acao": "fechar", "app": m.group(3)})
    if (m := _JANELA_ACAO.match(t)) and not _PALAVRAS_ARQUIVO.search(m.group(2)):
        verbo = m.group(1)
        acao = ("minimizar" if verbo.startswith("minimiz") else "maximizar" if verbo.startswith("maximiz")
                else "restaurar" if verbo.startswith("restaur") else "focar")
        # "traz as notícias" não é uma janela: "focar" só vira atalho se a janela existe
        if acao != "focar" or _janela_aberta(m.group(2)):
            return rodar("janelas", {"acao": acao, "app": m.group(2)})

    # -- apps, web e mídia
    if m := _PESQUISAR.match(t):
        onde = {"mapa": "maps"}.get(m.group(3) or "", m.group(3) or "google")
        return rodar("pesquisar", {"termo": m.group(2), "onde": onde})
    if m := _TOCAR_YT.match(t):
        return rodar("tocar_youtube", {"busca": m.group(2)})
    if m := _FECHAR.match(t):
        alvo = m.group(2)
        if not _PALAVRAS_ARQUIVO.search(alvo) and app.apps.conhece_processo(alvo):
            return rodar("fechar_programa", {"nome": alvo})
    if m := _ABRIR.match(t):
        alvo = m.group(2)
        if not _PALAVRAS_ARQUIVO.search(alvo) and app.apps.resolver(alvo) is not None:
            return rodar("abrir", {"alvo": alvo})
    if (m := _TOCAR.match(t)) and len(m.group(2).split()) <= 8 and m.group(2) not in _NAO_TOCAR:
        return rodar("tocar_youtube", {"busca": m.group(2)})
    return None
