"""Ferramentas que a Sexta-Feira pode usar (o modelo de IA escolhe qual chamar)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from ..cerebro.ferramentas import CONFIRMAR, LIVRE, ROSTO, P, Registro
from ..util.tempo import interpretar_quando
from . import sistema_info, web, windows
from .clima import ErroClima, ServicoClima
from .hologramas import TIPOS as TIPOS_HOLOGRAMA
from .lembretes import REPETICOES
from .noticias import CATEGORIAS, ErroNoticias
from .rotinas import ACOES_SEGURAS, CONDICOES, GATILHOS

log = logging.getLogger(__name__)

TEXTO_REPETICAO = {"diario": " todos os dias", "dias_uteis": " nos dias úteis", "semanal": " toda semana"}


def _nivel_computador(args: dict) -> int:
    return ROSTO if args.get("acao") in ("desligar", "reiniciar") else CONFIRMAR if args.get("acao") == "suspender" else LIVRE


def _descrever_computador(args: dict) -> str:
    return {"desligar": "desligar o computador", "reiniciar": "reiniciar o computador",
            "suspender": "suspender o computador"}.get(args.get("acao", ""), "essa ação no computador")


def registrar_ferramentas(app, registro: Registro) -> None:
    ferramenta = registro.ferramenta

    # ------------------------------------------------------------------ clima
    @ferramenta(
        "obter_clima",
        "Consulta o clima agora e a previsão dos próximos 7 dias, e mostra o holograma do clima. "
        "Sem cidade, usa a cidade do usuário.",
        cidade=P("string", "Cidade, opcionalmente com o estado. Ex.: 'Belo Horizonte' ou 'Campinas, SP'."),
        dias=P("integer", "Quantos dias de previsão o usuário quer ouvir (1 = só hoje)."),
        salvar_como_padrao=P("boolean", "true se o usuário disse que esta é a cidade dele."),
    )
    def obter_clima(ctx, cidade: str | None = None, dias: int = 1, salvar_como_padrao: bool = False):
        prefs = app.prefs
        try:
            if cidade:
                local = app.clima.localizar(cidade)
                if salvar_como_padrao or not prefs.get("cidade"):
                    app.definir_cidade(local)
            elif prefs.get("cidade_lat") is not None:
                local = {"lat": prefs.get("cidade_lat"), "lon": prefs.get("cidade_lon"),
                         "rotulo": prefs.get("cidade_rotulo") or prefs.get("cidade")}
            elif prefs.get("cidade"):
                local = app.clima.localizar(prefs.get("cidade"))
                app.definir_cidade(local)
            else:
                return {"ok": False, "resumo": "Ainda não sei a cidade do usuário. Pergunte qual é e chame de novo "
                                               "com salvar_como_padrao=true."}
            dados = app.clima.obter(local)
        except ErroClima as erro:
            return {"ok": False, "resumo": str(erro)}
        app.hologramas.mostrar("clima", dados, titulo=dados["local"])
        return {
            "ok": True,
            "resumo": ServicoClima.resumo(dados, dias or 1),
            "local": dados["local"],
            "agora": dados["atual"],
            "previsao": [{k: d[k] for k in ("dia", "max", "min", "chuva", "descricao")} for d in dados["dias"]],
        }

    # ------------------------------------------------------------------ notícias
    @ferramenta(
        "obter_noticias",
        "Busca as manchetes mais recentes (Google Notícias, em português) e mostra o holograma de notícias.",
        assunto=P("string", "Tema específico, ex.: 'Cruzeiro', 'inteligência artificial', 'eleições'."),
        categoria=P("string", "Categoria geral, se não houver assunto específico.", enum=CATEGORIAS),
        quantidade=P("integer", "Quantas manchetes resumir (padrão 5)."),
    )
    def obter_noticias(ctx, assunto: str | None = None, categoria: str | None = None, quantidade: int = 5):
        quantidade = max(1, min(int(quantidade or 5), 10))
        try:
            itens = app.noticias.buscar(assunto, None if categoria in (None, "geral") else categoria,
                                        quantidade=max(quantidade, 8))
        except ErroNoticias as erro:
            return {"ok": False, "resumo": str(erro)}
        nomes = {"brasil": "Brasil", "mundo": "Mundo", "tecnologia": "Tecnologia", "economia": "Economia", "esportes": "Esportes",
                 "entretenimento": "Entretenimento", "ciencia": "Ciência", "saude": "Saúde"}
        titulo = f"Notícias sobre {assunto}" if assunto else f"Notícias de {nomes[categoria]}" if categoria in nomes else "Notícias em destaque"
        app.hologramas.mostrar("noticias", {"itens": itens, "assunto": assunto, "categoria": categoria}, titulo=titulo)
        if not itens:
            return {"ok": False, "resumo": "Não encontrei notícias sobre isso agora."}
        principais = itens[:quantidade]
        return {
            "ok": True,
            "resumo": "Principais manchetes: " + "; ".join(i["titulo"] for i in principais[:3]) + ".",
            "manchetes": [f"{i['titulo']} ({i['fonte']}, {i['quando']})" for i in principais],
        }

    # ------------------------------------------------------------------ apps e web
    @ferramenta(
        "abrir",
        "Abre um programa, site, pasta ou endereço no computador. Ex.: 'Spotify', 'YouTube', 'Downloads', 'github.com'.",
        direta=True,
        alvo=P("string", "O que abrir, do jeito que o usuário falou.", obrigatorio=True),
    )
    def abrir(ctx, alvo: str):
        ok, mensagem = app.apps.abrir(alvo)
        return {"ok": ok, "resumo": mensagem}

    @ferramenta(
        "fechar_programa",
        "Fecha um programa aberto (como clicar no X; o programa pode pedir para salvar).",
        direta=True, nivel=CONFIRMAR, descrever=lambda a: f"fechar {a.get('nome', 'o programa')}",
        nome=P("string", "Nome do programa, ex.: 'Chrome', 'Spotify'.", obrigatorio=True),
    )
    def fechar_programa(ctx, nome: str):
        ok, mensagem = app.apps.fechar(nome)
        return {"ok": ok, "resumo": mensagem}

    @ferramenta(
        "pesquisar",
        "Pesquisa algo na internet abrindo o navegador no Google, YouTube, Maps ou Imagens.",
        direta=True,
        termo=P("string", "O que pesquisar.", obrigatorio=True),
        onde=P("string", "Onde pesquisar (padrão google).", enum=list(web.BUSCAS)),
    )
    def pesquisar(ctx, termo: str, onde: str = "google"):
        web.pesquisar(termo, onde or "google")
        return {"ok": True, "resumo": f"Pesquisando {termo}" + ("" if onde in (None, "google") else f" no {onde}") + "."}

    @ferramenta(
        "tocar_youtube",
        "Toca uma música ou vídeo no YouTube (abre o primeiro resultado da busca no navegador).",
        direta=True,
        busca=P("string", "Música, artista ou vídeo.", obrigatorio=True),
    )
    def tocar_youtube(ctx, busca: str):
        ok, mensagem = web.tocar_youtube(busca)
        return {"ok": ok, "resumo": mensagem}

    # ------------------------------------------------------------------ mídia e volume
    @ferramenta(
        "controlar_midia",
        "Controla o que está tocando no PC (Spotify, YouTube, player): tocar/pausar, próxima, anterior, parar.",
        direta=True,
        acao=P("string", "Ação.", enum=["tocar_pausar", "proxima", "anterior", "parar"], obrigatorio=True),
    )
    def controlar_midia(ctx, acao: str):
        try:
            windows.apertar_tecla(acao)
        except windows.NaoSuportado as erro:
            return {"ok": False, "resumo": str(erro)}
        return {"ok": True, "resumo": {"tocar_pausar": "Feito.", "proxima": "Próxima.", "anterior": "Voltando.",
                                       "parar": "Parado."}[acao]}

    @ferramenta(
        "ajustar_volume",
        "Ajusta ou consulta o volume do computador.",
        direta=True,
        acao=P("string", "O que fazer.", enum=["definir", "aumentar", "diminuir", "mudo", "tirar_mudo", "consultar"],
               obrigatorio=True),
        valor=P("integer", "Porcentagem 0-100 para 'definir'; para aumentar/diminuir, quantos pontos (padrão 10)."),
    )
    def ajustar_volume(ctx, acao: str, valor: int | None = None):
        try:
            if acao == "definir":
                if valor is None:
                    return {"ok": False, "resumo": "Qual volume? Diga um número de 0 a 100."}
                return {"ok": True, "resumo": f"Volume em {windows.definir_volume(valor)}%."}
            if acao in ("aumentar", "diminuir"):
                passo = abs(int(valor or 10)) * (1 if acao == "aumentar" else -1)
                novo = windows.mudar_volume(passo)
                return {"ok": True, "resumo": f"Volume em {novo}%." if novo >= 0 else "Volume ajustado."}
            if acao == "mudo":
                windows.silenciar(True)
                return {"ok": True, "resumo": "Som desligado."}
            if acao == "tirar_mudo":
                windows.silenciar(False)
                return {"ok": True, "resumo": "Som de volta."}
            atual = windows.volume_atual()
            return {"ok": atual is not None, "resumo": f"O volume está em {atual}%." if atual is not None else "Não consegui ler o volume."}
        except windows.NaoSuportado as erro:
            return {"ok": False, "resumo": str(erro)}

    # ------------------------------------------------------------------ computador
    @ferramenta(
        "computador",
        "Ações no PC: tirar print da tela, bloquear a tela, desligar, reiniciar, suspender, cancelar um desligamento "
        "agendado, ou ver o status (CPU, memória, disco, bateria).",
        direta=True, nivel=_nivel_computador, descrever=_descrever_computador,
        acao=P("string", "Ação.", enum=["print", "bloquear", "desligar", "reiniciar", "suspender",
                                        "cancelar_desligamento", "status"], obrigatorio=True),
    )
    def computador(ctx, acao: str):
        try:
            if acao == "print":
                arquivo = windows.print_da_tela(app.pasta_prints())
                app.hologramas.mostrar("imagem", {"url": f"/api/prints/{arquivo.name}", "legenda": arquivo.name},
                                       titulo="Print da tela")
                return {"ok": True, "resumo": "Print salvo na pasta Imagens, Sexta-Feira."}
            if acao == "bloquear":
                windows.bloquear_windows()
                app.sessao.bloquear("windows")
                return {"ok": True, "resumo": "Tela bloqueada."}
            if acao in ("desligar", "reiniciar", "suspender"):
                windows.energia(acao)
                if acao == "suspender":
                    return {"ok": True, "resumo": "Suspendendo o computador."}
                return {"ok": True, "resumo": f"Vou {acao} em 30 segundos. Diga 'cancelar desligamento' se mudar de ideia."}
            if acao == "cancelar_desligamento":
                windows.energia("cancelar")
                return {"ok": True, "resumo": "Desligamento cancelado."}
            dados = sistema_info.coletar()
            app.hologramas.mostrar("sistema", dados)
            return {"ok": True, "resumo": sistema_info.resumo(dados), "dados": dados}
        except windows.NaoSuportado as erro:
            return {"ok": False, "resumo": str(erro)}

    # ------------------------------------------------------------------ lembretes
    @ferramenta(
        "criar_lembrete",
        "Cria um lembrete ou alarme. Para timers ('me avisa em 10 minutos') use quando='daqui a 10 minutos'.",
        direta=True,
        texto=P("string", "Do que lembrar, ex.: 'ligar para o João'.", obrigatorio=True),
        quando=P("string", "Quando, do jeito que o usuário falou: 'amanhã às 7h', 'daqui a 20 minutos', "
                           "'sexta às 18:30'.", obrigatorio=True),
        repetir=P("string", "Repetição.", enum=REPETICOES),
        alarme=P("boolean", "true para tocar como despertador (insiste até desligar), false para só avisar."),
    )
    def criar_lembrete(ctx, texto: str, quando: str, repetir: str = "nao", alarme: bool = False):
        momento = interpretar_quando(quando)
        if momento is None:
            return {"ok": False, "resumo": f"Não entendi o horário '{quando}'. Peça para o usuário dizer de outro jeito."}
        agora = datetime.now()
        if momento < agora - timedelta(minutes=1) and (repetir or "nao") == "nao":
            return {"ok": False, "resumo": "Esse horário já passou."}
        if repetir == "dias_uteis":
            while momento.weekday() >= 5:
                momento += timedelta(days=1)
        lembrete = app.lembretes.criar(texto, momento, repetir or "nao", bool(alarme))
        app.hologramas.mostrar("lembretes")
        tipo = "Alarme" if alarme else "Lembrete"
        return {"ok": True, "resumo": f"{tipo} criado para {lembrete['descricao']}{TEXTO_REPETICAO.get(repetir or '', '')}.",
                "quando": lembrete["quando"]}

    @ferramenta(
        "gerenciar_lembretes",
        "Lista os lembretes (todos ou só os de hoje), cancela lembretes, ou desliga um alarme que está tocando.",
        direta=True,
        acao=P("string", "Ação.", enum=["listar", "hoje", "cancelar", "cancelar_todos", "parar_alarme"], obrigatorio=True),
        alvo=P("string", "Para cancelar: parte do texto do lembrete ou o número dele."),
    )
    def gerenciar_lembretes(ctx, acao: str, alvo: str | None = None):
        lembretes = app.lembretes
        if acao == "parar_alarme":
            return {"ok": True, "resumo": "Alarme desligado." if lembretes.parar_alarme() else "Não há alarme tocando."}
        if acao == "cancelar_todos":
            n = lembretes.cancelar_todos()
            return {"ok": True, "resumo": f"{n} lembretes cancelados." if n else "Não havia lembretes."}
        if acao == "cancelar":
            if not alvo:
                return {"ok": False, "resumo": "Qual lembrete cancelar?"}
            if alvo.strip().isdigit() and lembretes.cancelar(int(alvo)):
                return {"ok": True, "resumo": "Lembrete cancelado."}
            removidos = lembretes.cancelar_por_texto(alvo)
            if not removidos:
                return {"ok": False, "resumo": f"Não achei lembrete com '{alvo}'."}
            return {"ok": True, "resumo": "Cancelei: " + "; ".join(removidos) + "."}
        itens = lembretes.do_dia() if acao == "hoje" else lembretes.listar()
        app.hologramas.mostrar("lembretes")
        if not itens:
            return {"ok": True, "resumo": "Você não tem lembretes para hoje." if acao == "hoje" else "Você não tem lembretes."}
        partes = [f"{l['texto']} ({l['descricao']})" for l in itens[:6]]
        prefixo = "Hoje você tem: " if acao == "hoje" else f"Você tem {len(itens)} lembrete{'s' if len(itens) > 1 else ''}: "
        return {"ok": True, "resumo": prefixo + "; ".join(partes) + ".",
                "lembretes": [{"id": l["id"], "texto": l["texto"], "quando": l["descricao"]} for l in itens]}

    # ------------------------------------------------------------------ rotinas
    @ferramenta(
        "rotina",
        "Protocolos e rotinas: executa, lista, apaga, ativa, desativa ou recarrega (depois de editar os arquivos de rotinas, layouts, terminal) as rotinas — sequências de ações como "
        "'modo trabalho' ou 'modo jogo'.",
        direta=True,
        acao=P("string", "Ação.", enum=["executar", "listar", "apagar", "ativar", "desativar", "recarregar"],
               obrigatorio=True),
        nome=P("string", "Nome do protocolo/rotina."),
    )
    def rotina(ctx, acao: str, nome: str | None = None):
        rotinas = app.rotinas
        if acao == "recarregar":
            rotinas.recarregar()
            app.apps.recarregar()
            app.layouts.recarregar()
            app.terminal.recarregar()
            app.jornal.recarregar()
            return {"ok": True, "resumo": f"Rotinas recarregadas: {len(rotinas.listar())} no total."}
        if acao == "listar":
            itens = rotinas.listar()
            app.hologramas.mostrar("rotinas")
            if not itens:
                return {"ok": True, "resumo": "Você ainda não tem rotinas."}
            return {"ok": True, "resumo": "Suas rotinas: " + ", ".join(r.nome for r in itens) + ".",
                    "rotinas": [r.para_dict() for r in itens]}
        if not nome:
            return {"ok": False, "resumo": "Qual rotina?"}
        alvo = rotinas.obter(nome)
        if alvo is None:
            disponiveis = ", ".join(r.nome for r in rotinas.listar()) or "nenhuma"
            return {"ok": False, "resumo": f"Não conheço a rotina '{nome}'. Disponíveis: {disponiveis}."}
        if acao in ("ativar", "desativar"):
            rotinas.definir_ativo(alvo.nome, acao == "ativar")
            return {"ok": True, "resumo": f"Protocolo {alvo.nome} {'ativado' if acao == 'ativar' else 'desativado'}."}
        if acao == "apagar":
            if rotinas.apagar(alvo.nome):
                return {"ok": True, "resumo": f"Rotina {alvo.nome} apagada."}
            return {"ok": False, "resumo": "Só consigo apagar rotinas que eu criei; as outras estão no arquivo config/rotinas.yaml."}
        rotinas.executar(alvo, ctx)
        tem_fala = any(next(iter(p)) in ("falar", "briefing") for p in alvo.passos)
        return {"ok": True, "resumo": "" if tem_fala else f"Rotina {alvo.nome} em andamento.",
                "observacao": "A rotina já anuncia o que está fazendo; confirme em no máximo 3 palavras."}

    @ferramenta(
        "criar_protocolo",
        "Cria um protocolo (automação) a pedido do usuário: 'toda vez que eu abrir o Valorant, fecha o Chrome e "
        "coloca o PC no desempenho máximo'. Gatilhos: frase, horario (HH:MM), desbloquear, app_aberto, app_fechado, "
        "bateria_baixa (%), pendrive, arquivo_novo (pasta), wifi (rede), voltar_ao_pc (minutos fora). Condições: "
        "dias (seg..dom, uteis, fim de semana), entre ('18:00-23:00'), em_reuniao (true/false), chovendo "
        "(true/false), wifi. Ações {acao, valor}: falar, notificar (no celular), abrir, fechar, layout, "
        "minimizar_tudo, volume, midia, tocar_youtube, pesquisar, plano_energia, nao_perturbe, modo_escuro, brilho, "
        "holograma, clima, noticias, briefing, lembretes, organizar_downloads, mover_arquivo (pasta; para "
        "arquivo_novo), print, bloquear, esperar. Textos podem usar {app}, {nome_arquivo}, {rede}, {bateria}. "
        "O usuário aprova antes de salvar.",
        direta=True,
        nome=P("string", "Nome curto, ex.: 'modo valorant'.", obrigatorio=True),
        gatilhos=P("array", "Quando o protocolo roda.", itens={
            "type": "object",
            "properties": {"tipo": {"type": "string", "enum": GATILHOS}, "valor": {"type": "string"},
                           "dias": {"type": "array", "items": {"type": "string"}}},
            "required": ["tipo"],
        }),
        condicoes=P("array", "Condições opcionais (todas precisam valer).", itens={
            "type": "object",
            "properties": {"tipo": {"type": "string", "enum": CONDICOES}, "valor": {"type": "string"}},
            "required": ["tipo", "valor"],
        }),
        passos=P("array", "Ações em ordem.", obrigatorio=True, itens={
            "type": "object",
            "properties": {"acao": {"type": "string", "enum": ACOES_SEGURAS}, "valor": {"type": "string"}},
            "required": ["acao"],
        }),
    )
    def criar_protocolo(ctx, nome: str, passos: list, gatilhos: list | None = None, condicoes: list | None = None):
        try:
            rascunho = app.rotinas.rascunho(nome, passos, gatilhos=gatilhos, condicoes=condicoes)
        except ValueError as erro:
            return {"ok": False, "resumo": str(erro), "_direta": False}
        if ctx.confirmado:
            salvo = app.rotinas.salvar(rascunho)
            app.hologramas.fechar(tipo="protocolo")
            app.hologramas.mostrar("rotinas")
            return {"ok": True, "resumo": f"Protocolo {salvo.nome} ativo."}
        app.hologramas.mostrar("protocolo", {"protocolo": rascunho.para_editor(), "resumo": rascunho.resumo()},
                               titulo=f"Novo protocolo: {rascunho.nome}")
        args = {"nome": nome, "passos": passos, "gatilhos": gatilhos or [], "condicoes": condicoes or []}
        app.registro.aguardar("criar_protocolo", args, f"salvar o protocolo {rascunho.nome}", ctx)
        return {"ok": False, "pendente": True,
                "resumo": f"Montei o protocolo {rascunho.nome}: {rascunho.resumo()}. Aprova?"}

    # ------------------------------------------------------------------ hologramas
    @ferramenta(
        "holograma",
        "Mostra ou fecha hologramas no HUD. Tipos: clima, noticias, sistema, relogio, globo, lembretes, rotinas, camera, "
        "atividades (registro do que a Sexta fez no PC), jornal (central de notícias com abas), texto (anotação/lista que o usuário pedir para exibir).",
        direta=True,
        acao=P("string", "Ação.", enum=["mostrar", "fechar", "fechar_todos"], obrigatorio=True),
        tipo=P("string", "Tipo do holograma.", enum=TIPOS_HOLOGRAMA),
        titulo=P("string", "Título (opcional)."),
        conteudo=P("string", "Texto do holograma (só para o tipo texto)."),
    )
    def holograma(ctx, acao: str, tipo: str | None = None, titulo: str | None = None, conteudo: str | None = None):
        h = app.hologramas
        if acao == "fechar_todos" or (acao == "fechar" and not tipo):
            h.fechar_todos()
            return {"ok": True, "resumo": "Hologramas fechados."}
        if not tipo:
            return {"ok": False, "resumo": "Qual holograma?"}
        if acao == "fechar":
            n = h.fechar(tipo=tipo)
            return {"ok": True, "resumo": "Fechado." if n else "Esse holograma não estava aberto."}
        if tipo == "clima":
            return obter_clima(ctx)
        if tipo == "noticias":
            return obter_noticias(ctx)
        if tipo == "jornal":
            h.mostrar("jornal", app.jornal.dados_holograma(), titulo="Jornal")
            return {"ok": True, "resumo": "Jornal na tela."}
        if tipo == "texto":
            h.mostrar("texto", {"texto": conteudo or ""}, titulo=titulo or "Nota")
        elif tipo == "camera":
            h.mostrar("camera", {})
            app.maos_para_hud(True)
        else:
            h.mostrar(tipo, titulo=titulo)
        return {"ok": True, "resumo": "Na tela."}

    # ------------------------------------------------------------------ memória
    @ferramenta(
        "memoria",
        "Guarda, esquece ou lista fatos sobre o usuário para lembrar em conversas futuras "
        "(ex.: time do coração, nome da namorada, preferências).",
        direta=True,
        acao=P("string", "Ação.", enum=["lembrar", "esquecer", "listar"], obrigatorio=True),
        fato=P("string", "O fato, em uma frase curta na terceira pessoa. Ex.: 'O time dele é o Cruzeiro'."),
    )
    def memoria(ctx, acao: str, fato: str | None = None):
        if acao == "listar":
            fatos = app.memoria.listar()
            return {"ok": True, "resumo": ("Eu sei que: " + "; ".join(fatos) + ".") if fatos else "Ainda não guardei nada."}
        if not fato:
            return {"ok": False, "resumo": "O que devo guardar?"}
        if acao == "lembrar":
            novo = app.memoria.lembrar(fato)
            return {"ok": True, "resumo": "Anotado." if novo else "Eu já sabia disso."}
        removidos = app.memoria.esquecer(fato)
        return {"ok": bool(removidos), "resumo": "Esquecido." if removidos else "Não achei isso na minha memória."}

    # ------------------------------------------------------------------ a própria assistente
    @ferramenta(
        "assistente",
        "Controla a própria Sexta-Feira: bloquear (modo privado: só obedece depois de reconhecer o rosto), "
        "silenciar o microfone, ligar ou desligar o controle dos hologramas pelas mãos.",
        direta=True,
        acao=P("string", "Ação.", enum=["bloquear", "silenciar_microfone", "ligar_maos", "desligar_maos"], obrigatorio=True),
    )
    def assistente(ctx, acao: str):
        if acao == "bloquear":
            if not app.sessao.protecao_ativa():
                return {"ok": False, "resumo": "Para eu me bloquear, cadastre seu rosto primeiro nas configurações do HUD."}
            app.sessao.bloquear("pedido")
            return {"ok": True, "resumo": "Modo privado ativado."}
        if acao == "silenciar_microfone":
            app.estado.definir_microfone(False)
            return {"ok": True, "resumo": "Microfone desligado. Para religar, use o HUD, o celular ou o ícone da bandeja."}
        ligar = acao == "ligar_maos"
        if ligar and not app.maos.disponivel():
            return {"ok": False, "resumo": "O modelo de rastreamento das mãos não está instalado. Rode: python -m sexta baixar."}
        app.maos_para_hud(ligar)
        return {"ok": True, "resumo": "Controle por gestos ligado. Faça uma pinça para pegar um holograma." if ligar
                else "Controle por gestos desligado."}

    registrar_ferramentas_pc(app, registro)


# ---------------------------------------------------------------------------
# Fase 1: acesso às ferramentas do computador
# ---------------------------------------------------------------------------

def _nivel_arquivos(args: dict) -> int:
    return {"apagar": ROSTO, "mover": CONFIRMAR, "renomear": CONFIRMAR, "organizar_downloads": CONFIRMAR}.get(
        args.get("acao", ""), LIVRE)


def _descrever_arquivos(args: dict) -> str:
    acao, alvo = args.get("acao", ""), args.get("alvo") or "o arquivo"
    alvo = f"o item {alvo} da busca" if str(alvo).strip().isdigit() else alvo
    return {"apagar": f"mandar {alvo} para a Lixeira", "mover": f"mover {alvo} para {args.get('destino', '?')}",
            "renomear": f"renomear {alvo} para {args.get('destino', '?')}",
            "organizar_downloads": "organizar a pasta Downloads em pastas por tipo"
            + (" e mês" if args.get("por_data") else "")}.get(acao, acao)


def _nivel_janelas(args: dict) -> int:
    return CONFIRMAR if args.get("acao") == "fechar" else LIVRE


def _nivel_processos(args: dict) -> int:
    return CONFIRMAR if args.get("acao") in ("encerrar", "fechar_travados") else LIVRE


def _descrever_processos(args: dict) -> str:
    if args.get("acao") == "fechar_travados":
        return "fechar à força os programas que não estão respondendo"
    return f"encerrar à força {args.get('nome') or 'o programa'} (o que não foi salvo se perde)"


def registrar_ferramentas_pc(app, registro: Registro) -> None:
    from . import area_transferencia, configuracoes, janelas, processos, visao
    from .arquivos import ErroArquivos
    from .configuracoes import ErroConfiguracao

    ferramenta = registro.ferramenta

    # ------------------------------------------------------------------ arquivos
    @ferramenta(
        "arquivos",
        "Arquivos do usuário: buscar (por nome, tipo e data: 'pdf do contrato de março'), abrir, mostrar_na_pasta, "
        "recentes, mover, renomear, apagar (vai para a Lixeira) e organizar_downloads (separa por tipo).",
        direta=True, nivel=_nivel_arquivos, descrever=_descrever_arquivos,
        acao=P("string", "Ação.", enum=["buscar", "abrir", "mostrar_na_pasta", "recentes", "mover", "renomear",
                                        "apagar", "organizar_downloads"], obrigatorio=True),
        alvo=P("string", "Para buscar: o que procurar, do jeito que o usuário falou. Para as outras ações: o número "
                         "do resultado da última busca ('1', '2'...), um caminho ou um nome."),
        tipo=P("string", "Filtro de tipo opcional: pdf, documento, planilha, apresentacao, imagem, video, musica, "
                         "compactado, instalador, codigo, modelo 3d."),
        destino=P("string", "Para mover: pasta de destino (ex.: 'Documentos', 'Projetos'). Para renomear: o nome novo."),
        por_data=P("boolean", "Para organizar_downloads: também separar por mês."),
    )
    def arquivos(ctx, acao: str, alvo: str | None = None, tipo: str | None = None, destino: str | None = None,
                 por_data: bool = False):
        arq = app.arquivos
        try:
            if acao in ("buscar", "recentes"):
                achados = arq.recentes(tipo=tipo) if acao == "recentes" else arq.buscar(alvo or "", tipo)
                if not achados:
                    return {"ok": False, "resumo": "Não encontrei nenhum arquivo assim.", "_direta": False}
                itens = [a.para_dict() for a in achados]
                linhas = [f"{i}. {d['nome']} ({d['modificado']})" for i, d in enumerate(itens, 1)]
                app.hologramas.mostrar("texto", {"texto": "\n".join(linhas + ["", "Diga: abre o 1, mostra o 2 na pasta..."])},
                                       titulo="Arquivos recentes" if acao == "recentes" else f"Busca: {alvo or tipo}")
                if len(itens) == 1:
                    resumo = f"Achei {itens[0]['nome']}, de {itens[0]['modificado'][:10]}. Quer que eu abra?"
                else:
                    resumo = f"Achei {len(itens)} arquivos. O primeiro é {itens[0]['nome']}. Estão na tela."
                return {"ok": True, "resumo": resumo, "arquivos": itens}
            if acao == "organizar_downloads":
                contagem = arq.organizar_downloads(bool(por_data))
                if not contagem:
                    return {"ok": True, "resumo": "A pasta Downloads já está organizada."}
                total = sum(contagem.values())
                partes = ", ".join(f"{n} em {g}" for g, n in sorted(contagem.items(), key=lambda x: -x[1])[:4])
                return {"ok": True, "resumo": f"Organizei {total} arquivos: {partes}."}
            if not alvo:
                return {"ok": False, "resumo": "Qual arquivo?"}
            if acao == "abrir":
                caminho = arq.abrir(alvo)
                return {"ok": True, "resumo": f"Abrindo {caminho.name}."}
            if acao == "mostrar_na_pasta":
                caminho = arq.mostrar_na_pasta(alvo)
                return {"ok": True, "resumo": f"Mostrando {caminho.name} na pasta."}
            if acao == "mover":
                if not destino:
                    return {"ok": False, "resumo": "Para qual pasta?"}
                final = arq.mover(alvo, destino)
                return {"ok": True, "resumo": f"Movi {final.name} para {final.parent.name}."}
            if acao == "renomear":
                if not destino:
                    return {"ok": False, "resumo": "Qual o nome novo?"}
                final = arq.renomear(alvo, destino)
                return {"ok": True, "resumo": f"Renomeado para {final.name}."}
            caminho = arq.apagar(alvo)
            return {"ok": True, "resumo": f"{caminho.name} foi para a Lixeira."}
        except (ErroArquivos, OSError, windows.NaoSuportado) as erro:
            return {"ok": False, "resumo": str(erro)}

    # ------------------------------------------------------------------ área de transferência
    @ferramenta(
        "area_transferencia",
        "Lê o texto copiado pelo usuário, ou coloca um texto na área de transferência e cola na janela em foco "
        "(para 'corrige e cola', 'traduz e cola').",
        acao=P("string", "Ação.", enum=["ler", "copiar", "colar"], obrigatorio=True),
        texto=P("string", "Para copiar/colar: o texto final."),
    )
    def area_transf(ctx, acao: str, texto: str | None = None):
        try:
            if acao == "ler":
                copiado = area_transferencia.ler().strip()
                if not copiado:
                    return {"ok": False, "resumo": "A área de transferência está vazia (ou tem uma imagem)."}
                return {"ok": True, "resumo": "Texto copiado lido.", "texto": copiado[:area_transferencia.LIMITE]}
            if not texto:
                return {"ok": False, "resumo": "Qual texto?"}
            area_transferencia.escrever(texto)
            if acao == "colar":
                area_transferencia.colar()
                return {"ok": True, "resumo": "Pronto, colei.", "_direta": True}
            return {"ok": True, "resumo": "Copiado.", "_direta": True}
        except (area_transferencia.ErroAreaTransferencia, OSError, windows.NaoSuportado) as erro:
            return {"ok": False, "resumo": str(erro)}

    # ------------------------------------------------------------------ janelas
    @ferramenta(
        "janelas",
        "Controla as janelas abertas: focar, minimizar, maximizar, restaurar, fechar, encaixar (esquerda/direita/...), "
        "mover_monitor (manda para o outro monitor), minimizar_tudo, listar, aplicar_layout e salvar_layout "
        "(ex.: 'modo trabalho' com VS Code à esquerda e navegador à direita).",
        direta=True, nivel=_nivel_janelas, descrever=lambda a: f"fechar a janela de {a.get('app', '?')}",
        acao=P("string", "Ação.", enum=["focar", "minimizar", "maximizar", "restaurar", "fechar", "encaixar",
                                        "mover_monitor", "minimizar_tudo", "listar", "aplicar_layout", "salvar_layout"],
               obrigatorio=True),
        app=P("string", "Programa ou janela, ex.: 'VS Code', 'navegador', 'Spotify'. Para layouts: o nome do layout."),
        posicao=P("string", "Para encaixar.", enum=janelas.POSICOES),
        monitor=P("integer", "Número do monitor (1 = o mais à esquerda). Opcional."),
    )
    def ferramenta_janelas(ctx, acao: str, app: str | None = None, posicao: str | None = None,
                           monitor: int | None = None):
        sexta = ctx.app
        indice = monitor - 1 if monitor else None
        try:
            if acao == "minimizar_tudo":
                janelas.minimizar_tudo()
                return {"ok": True, "resumo": "Tudo minimizado."}
            if acao == "listar":
                lista = [j for j in janelas.listar() if not j.titulo.startswith("Sexta-Feira")][:12]
                if not lista:
                    return {"ok": True, "resumo": "Nenhuma janela aberta."}
                nomes = ", ".join(dict.fromkeys(j.exe for j in lista))
                return {"ok": True, "resumo": f"Abertos agora: {nomes}.", "janelas": [j.rotulo() for j in lista],
                        "_direta": False}
            if acao == "aplicar_layout":
                if not app:
                    return {"ok": False, "resumo": "Qual layout?"}
                feitos = sexta.layouts.aplicar(app)
                return {"ok": bool(feitos), "resumo": f"Layout {app} pronto." if feitos else "Não achei as janelas do layout."}
            if acao == "salvar_layout":
                if not app:
                    return {"ok": False, "resumo": "Com que nome salvo o layout?"}
                apps_salvos = sexta.layouts.salvar_atual(app)
                return {"ok": True, "resumo": f"Layout {app} salvo com {len(apps_salvos)} janelas. Diga 'layout {app}' para voltar a ele."}
            if not app:
                return {"ok": False, "resumo": "Qual janela?"}
            janela = janelas.exigir(app)
            if acao == "focar":
                janelas.focar(janela)
                return {"ok": True, "resumo": f"{janela.exe.capitalize()} em foco."}
            if acao == "minimizar":
                janelas.mostrar(janela, janelas.SW_MINIMIZE)
                return {"ok": True, "resumo": "Minimizado."}
            if acao == "maximizar":
                janelas.mostrar(janela, janelas.SW_MAXIMIZE)
                return {"ok": True, "resumo": "Maximizado."}
            if acao == "restaurar":
                janelas.mostrar(janela, janelas.SW_RESTORE)
                return {"ok": True, "resumo": "Restaurado."}
            if acao == "fechar":
                janelas.fechar(janela)
                return {"ok": True, "resumo": f"Fechando a janela de {janela.exe}."}
            if acao == "encaixar":
                janelas.encaixar(janela, posicao or "esquerda", indice)
                janelas.focar(janela)
                return {"ok": True, "resumo": "Encaixado."}
            destino = janelas.mover_para_monitor(janela, indice)
            return {"ok": True, "resumo": f"Mandei para o monitor {destino + 1}."}
        except (janelas.ErroJanelas, windows.NaoSuportado, OSError) as erro:
            return {"ok": False, "resumo": str(erro)}

    # ------------------------------------------------------------------ visão
    @ferramenta(
        "ver",
        "Olha a tela do PC (print) ou a webcam e responde sobre o que aparece: explicar um erro, ler uma planilha, "
        "resumir um site, identificar um objeto ou ler um papel mostrado à câmera.",
        direta=True,
        fonte=P("string", "De onde olhar.", enum=["tela", "camera"], obrigatorio=True),
        pergunta=P("string", "O que o usuário quer saber, com as palavras dele.", obrigatorio=True),
    )
    def ver(ctx, fonte: str, pergunta: str):
        sexta = ctx.app
        sexta.barramento.publicar("aviso", nivel="info", texto="Analisando a tela…" if fonte == "tela" else "Olhando pela câmera…")
        try:
            imagem = visao.capturar_camera(sexta) if fonte == "camera" else visao.capturar_tela()
            b64 = visao.para_base64(imagem)
        except Exception as erro:  # noqa: BLE001
            return {"ok": False, "resumo": f"Não consegui capturar a {'câmera' if fonte == 'camera' else 'tela'}: {erro}"}
        modelo = None if sexta.cfg.usa_claude() else (sexta.cfg.ollama_modelo_visao or None)
        resposta = sexta.agente.ollama.visao(pergunta, [b64], visao.instrucao(fonte, ctx.canal), modelo=modelo)
        if fonte == "tela" and ctx.canal != "voz":
            sexta.hologramas.mostrar("texto", {"texto": resposta}, titulo="Análise da tela")
        return {"ok": bool(resposta), "resumo": resposta or "Não consegui entender a imagem."}

    # ------------------------------------------------------------------ processos
    @ferramenta(
        "processos",
        "Mostra o que está pesando no PC (por CPU, memória RAM ou placa de vídeo), lista programas travados, "
        "fecha os travados ou encerra um programa à força.",
        direta=True, nivel=_nivel_processos, descrever=_descrever_processos,
        acao=P("string", "Ação.", enum=["mais_pesados", "travados", "fechar_travados", "encerrar"], obrigatorio=True),
        ordem=P("string", "Para mais_pesados: ordenar por.", enum=["cpu", "ram", "gpu"]),
        nome=P("string", "Para encerrar: o programa."),
    )
    def ferramenta_processos(ctx, acao: str, ordem: str = "cpu", nome: str | None = None):
        if acao == "mais_pesados":
            linhas = processos.top(ordem or "cpu")
            tabela = "\n".join(
                f"{l['nome']:<22} CPU {l['cpu']:>5.1f}%   RAM {processos._mb(l['ram_mb']):>8}"
                + (f"   GPU {l['gpu']:.0f}%" if l.get("gpu") is not None else "") for l in linhas)
            ctx.app.hologramas.mostrar("texto", {"texto": tabela}, titulo="Processos")
            return {"ok": True, "resumo": processos.descrever(linhas, ordem or "cpu"), "processos": linhas}
        if acao == "travados":
            lista = processos.travados()
            if not lista:
                return {"ok": True, "resumo": "Nenhum programa travado."}
            return {"ok": True, "resumo": "Não estão respondendo: " + ", ".join(t["nome"] for t in lista) + "."}
        if acao == "fechar_travados":
            fechados = processos.fechar_travados()
            return {"ok": True, "resumo": ("Fechei: " + ", ".join(fechados) + ".") if fechados else "Nenhum programa travado."}
        if not nome:
            return {"ok": False, "resumo": "Qual programa?"}
        quantos, _ = processos.encerrar(nome)
        return {"ok": bool(quantos), "resumo": f"{nome} encerrado." if quantos else f"Não achei {nome} rodando (ou é protegido)."}

    # ------------------------------------------------------------------ configurações
    @ferramenta(
        "configuracao",
        "Ajusta o Windows: brilho (0-100, mais, menos), wifi e bluetooth (ligar/desligar), modo_escuro, "
        "plano_energia (economia, equilibrado, alto desempenho, desempenho maximo), nao_perturbe e saida_audio "
        "(trocar entre fone, caixas, monitor...).",
        direta=True,
        item=P("string", "O que ajustar.", enum=["brilho", "wifi", "bluetooth", "modo_escuro", "plano_energia",
                                                  "nao_perturbe", "saida_audio"], obrigatorio=True),
        valor=P("string", "Brilho: número, 'mais' ou 'menos'. Wifi/bluetooth/modo_escuro/nao_perturbe: 'ligar', "
                          "'desligar' ou 'consultar'. Plano: o nome. Saída de áudio: o dispositivo ou 'listar'."),
    )
    def configuracao(ctx, item: str, valor: str | None = None):
        v = (valor or "").strip().lower()
        ligar = None if v in ("", "consultar", "status") else v in ("ligar", "liga", "on", "sim", "ativar", "true", "1")
        try:
            if item == "brilho":
                if v in ("", "consultar"):
                    return {"ok": True, "resumo": f"O brilho está em {configuracoes.brilho_atual()}%."}
                if v in ("mais", "aumentar", "+"):
                    return {"ok": True, "resumo": f"Brilho em {configuracoes.mudar_brilho(15)}%."}
                if v in ("menos", "diminuir", "-"):
                    return {"ok": True, "resumo": f"Brilho em {configuracoes.mudar_brilho(-15)}%."}
                numero = int("".join(c for c in v if c.isdigit()) or "-1")
                if numero < 0:
                    return {"ok": False, "resumo": "Qual brilho? Diga um número de 0 a 100."}
                return {"ok": True, "resumo": f"Brilho em {configuracoes.definir_brilho(numero)}%."}
            if item in ("wifi", "bluetooth"):
                nome = "Wi-Fi" if item == "wifi" else "Bluetooth"
                estado = configuracoes.radio(item, ligar)
                if ligar is None:
                    return {"ok": True, "resumo": f"{nome} {'ligado' if estado == 'On' else 'desligado'}."}
                return {"ok": True, "resumo": f"{nome} {'ligado' if ligar else 'desligado'}."}
            if item == "modo_escuro":
                escuro = configuracoes.modo_escuro(ligar)
                if ligar is None:
                    return {"ok": True, "resumo": "O modo escuro está ligado." if escuro else "O modo claro está ativo."}
                return {"ok": True, "resumo": "Modo escuro ligado." if escuro else "Modo claro ligado."}
            if item == "plano_energia":
                if not v:
                    return {"ok": False, "resumo": "Qual plano? Economia, equilibrado, alto desempenho ou desempenho máximo."}
                nome = configuracoes.definir_plano(v)
                return {"ok": True, "resumo": f"Plano de energia: {nome}."}
            if item == "nao_perturbe":
                ligar = True if ligar is None else ligar
                configuracoes.nao_perturbe(ligar)
                return {"ok": True, "resumo": "Não perturbe ligado: notificações silenciadas." if ligar
                        else "Notificações de volta."}
            if v in ("", "listar", "consultar"):
                lista = configuracoes.dispositivos_saida()
                atual = next((d["nome"] for d in lista if d["padrao"]), "?")
                outros = ", ".join(d["nome"] for d in lista if not d["padrao"]) or "nenhuma outra"
                return {"ok": True, "resumo": f"Saída atual: {atual}. Outras: {outros}."}
            nome = configuracoes.definir_saida(valor or "")
            return {"ok": True, "resumo": f"Som saindo em {nome}."}
        except (ErroConfiguracao, windows.NaoSuportado, OSError) as erro:
            return {"ok": False, "resumo": str(erro), "_direta": True}

    # ------------------------------------------------------------------ terminal
    @ferramenta(
        "terminal",
        "Roda um comando no terminal do Windows (cmd) e devolve a saída. Comandos da lista permitida rodam na hora; "
        "outros exigem confirmação com rosto. Use para: IP, ping, git status, winget, versões instaladas etc.",
        nivel=lambda a: LIVRE if app.terminal.permitido(a.get("comando", "")) else ROSTO,
        descrever=lambda a: f"rodar o comando: {a.get('comando', '')}",
        comando=P("string", "O comando exato.", obrigatorio=True),
    )
    def terminal(ctx, comando: str):
        try:
            codigo, saida = app.terminal.executar(comando)
        except Exception as erro:  # noqa: BLE001 - inclui o tempo esgotado
            return {"ok": False, "resumo": f"O comando falhou: {erro}"}
        if ctx.canal != "voz" and saida:
            app.hologramas.mostrar("texto", {"texto": f"> {comando}\n\n{saida}"}, titulo="Terminal")
        return {"ok": codigo == 0, "resumo": f"Comando terminou com código {codigo}.", "saida": saida or "(sem saída)"}

    # ------------------------------------------------------------------ registro de atividades
    @ferramenta(
        "atividades",
        "Mostra o registro do que a Sexta-Feira fez no computador (holograma) ou resume o que ela fez hoje.",
        direta=True,
        acao=P("string", "Ação.", enum=["mostrar", "resumo_hoje"], obrigatorio=True),
    )
    def atividades(ctx, acao: str):
        if acao == "resumo_hoje":
            return {"ok": True, "resumo": app.atividades.resumo_de_hoje()}
        app.hologramas.mostrar("atividades")
        return {"ok": True, "resumo": "Registro de atividades na tela."}

    registrar_ferramentas_jornal(app, registro)


# ---------------------------------------------------------------------------
# Fase 3: central de notícias
# ---------------------------------------------------------------------------

LEITURA_SISTEMA = ("Você é a Sexta-Feira. Resuma a matéria abaixo para ser FALADA em voz alta, em português do Brasil, "
                   "em no máximo 5 frases claras: o fato principal, os números ou nomes importantes e por que importa. "
                   "Sem markdown, listas nem links.")


def registrar_ferramentas_jornal(app, registro: Registro) -> None:
    from .jornal import ABAS

    ferramenta = registro.ferramenta

    def achar(aba: str | None, numero: int | None):
        aba = aba if aba in ABAS else "destaques"
        return app.jornal.item(aba, int(numero or 1))

    @ferramenta(
        "jornal",
        "Central de notícias: mostrar o holograma Jornal (abas destaques, brasil, tecnologia, temas, salvas), "
        "fazer o briefing do dia agora, ler (resumir) a notícia N de uma aba, salvar a notícia N para depois, "
        "gerenciar os temas que o usuário acompanha ('me avisa quando sair notícia de RTX 60') e agendar o "
        "briefing matinal num horário.",
        direta=True,
        acao=P("string", "Ação.", enum=["mostrar", "briefing", "ler", "salvar", "temas", "adicionar_tema",
                                        "remover_tema", "agendar_briefing"], obrigatorio=True),
        aba=P("string", "Aba (padrão destaques).", enum=ABAS),
        numero=P("integer", "Para ler/salvar: posição da notícia na aba (1 = a primeira)."),
        tema=P("string", "Para os temas: o assunto, ex.: 'RTX 60', 'EA FC 27'."),
        horario=P("string", "Para agendar_briefing: HH:MM."),
        dias=P("array", "Para agendar_briefing: dias (seg..dom, uteis, todos). Padrão: todos.", itens={"type": "string"}),
    )
    def jornal(ctx, acao: str, aba: str | None = None, numero: int | None = None, tema: str | None = None,
               horario: str | None = None, dias: list | None = None):
        j = app.jornal
        if acao == "briefing":
            return {"ok": True, "resumo": app.briefing(ctx)}
        if acao == "mostrar":
            dados = j.dados_holograma(aba or "destaques")
            app.hologramas.mostrar("jornal", dados, titulo="Jornal")
            itens = dados["abas"][dados["aba"]]
            if not itens:
                return {"ok": True, "resumo": "Jornal na tela, mas não encontrei notícias agora."}
            return {"ok": True, "resumo": "Na tela. Os destaques: " + "; ".join(i["titulo"] for i in itens[:3]) + "."}
        if acao in ("ler", "salvar"):
            item = achar(aba, numero)
            if item is None:
                return {"ok": False, "resumo": "Não achei essa notícia. Abra o jornal primeiro.", "_direta": True}
            if acao == "salvar":
                novo = j.salvar(item)
                return {"ok": True, "resumo": "Salva para depois." if novo else "Essa já estava salva."}
            texto = j.texto_da_materia(item)
            resumo = ""
            if len(texto) > 200:
                try:
                    resumo = app.agente.completar(LEITURA_SISTEMA, f"Título: {item['titulo']}\n\n{texto}")
                except Exception as erro:  # noqa: BLE001
                    log.info("Resumo da matéria sem IA: %s", erro)
            resumo = resumo or f"{item['titulo']}. {texto[:400]}".strip()
            leitura = {"titulo": item["titulo"], "texto": resumo, "link": item.get("link", ""), "ts": time.time()}
            aberto = next((h for h in app.hologramas.lista() if h["tipo"] == "jornal"), None)
            if aberto:  # mostra a leitura dentro do próprio Jornal
                app.hologramas.atualizar_tipo("jornal", {**aberto["dados"], "leitura": leitura})
            else:
                app.hologramas.mostrar("texto", {"texto": f"{item['titulo']}\n\n{resumo}\n\n{item.get('link', '')}"},
                                       titulo=", ".join(item.get("fontes") or [item.get("fonte", "Notícia")]))
            return {"ok": True, "resumo": resumo}
        if acao == "temas":
            temas = [t["tema"] for t in j.temas()]
            return {"ok": True, "resumo": ("Acompanho: " + ", ".join(temas) + ".") if temas
                    else "Você ainda não pediu para eu acompanhar nenhum tema."}
        if acao in ("adicionar_tema", "remover_tema"):
            if not tema:
                return {"ok": False, "resumo": "Qual assunto?"}
            if acao == "adicionar_tema":
                novo = j.adicionar_tema(tema)
                return {"ok": True, "resumo": f"Combinado: aviso quando sair notícia sobre {tema}." if novo
                        else f"Já estou de olho em {tema}."}
            removidos = j.remover_tema(tema)
            return {"ok": bool(removidos), "resumo": f"Parei de acompanhar {', '.join(removidos)}." if removidos
                    else f"Não acompanhava {tema}."}
        # agendar_briefing: vira um protocolo de horário (dá para editar no editor de protocolos)
        from .rotinas import _hora

        hora = _hora(horario or "")
        if not hora:
            return {"ok": False, "resumo": "Em que horário? Ex.: 7:30."}
        app.rotinas.salvar(app.rotinas.rascunho(
            "briefing matinal", [{"acao": "briefing", "valor": "true"}],
            gatilhos=[{"tipo": "horario", "valor": hora, "dias": dias or ["todos"]}]))
        return {"ok": True, "resumo": f"Briefing agendado para as {hora}."}
