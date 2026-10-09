"""Ferramentas que a Sexta-Feira pode usar (o modelo de IA escolhe qual chamar)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..cerebro.ferramentas import P, Registro
from ..util.tempo import interpretar_quando
from . import sistema_info, web, windows
from .clima import ErroClima, ServicoClima
from .hologramas import TIPOS as TIPOS_HOLOGRAMA
from .lembretes import REPETICOES
from .noticias import CATEGORIAS, ErroNoticias
from .rotinas import ACOES_SEGURAS

log = logging.getLogger(__name__)

TEXTO_REPETICAO = {"diario": " todos os dias", "dias_uteis": " nos dias úteis", "semanal": " toda semana"}


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
        alvo=P("string", "O que abrir, do jeito que o usuário falou.", obrigatorio=True),
    )
    def abrir(ctx, alvo: str):
        ok, mensagem = app.apps.abrir(alvo)
        return {"ok": ok, "resumo": mensagem}

    @ferramenta(
        "fechar_programa",
        "Fecha um programa aberto (como clicar no X; o programa pode pedir para salvar).",
        nome=P("string", "Nome do programa, ex.: 'Chrome', 'Spotify'.", obrigatorio=True),
    )
    def fechar_programa(ctx, nome: str):
        ok, mensagem = app.apps.fechar(nome)
        return {"ok": ok, "resumo": mensagem}

    @ferramenta(
        "pesquisar",
        "Pesquisa algo na internet abrindo o navegador no Google, YouTube, Maps ou Imagens.",
        termo=P("string", "O que pesquisar.", obrigatorio=True),
        onde=P("string", "Onde pesquisar (padrão google).", enum=list(web.BUSCAS)),
    )
    def pesquisar(ctx, termo: str, onde: str = "google"):
        web.pesquisar(termo, onde or "google")
        return {"ok": True, "resumo": f"Pesquisando {termo}" + ("" if onde in (None, "google") else f" no {onde}") + "."}

    @ferramenta(
        "tocar_youtube",
        "Toca uma música ou vídeo no YouTube (abre o primeiro resultado da busca no navegador).",
        busca=P("string", "Música, artista ou vídeo.", obrigatorio=True),
    )
    def tocar_youtube(ctx, busca: str):
        ok, mensagem = web.tocar_youtube(busca)
        return {"ok": ok, "resumo": mensagem}

    # ------------------------------------------------------------------ mídia e volume
    @ferramenta(
        "controlar_midia",
        "Controla o que está tocando no PC (Spotify, YouTube, player): tocar/pausar, próxima, anterior, parar.",
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
        acao=P("string", "Ação.", enum=["print", "bloquear", "desligar", "reiniciar", "suspender",
                                        "cancelar_desligamento", "status"], obrigatorio=True),
        confirmado=P("boolean", "Para desligar/reiniciar/suspender: true SOMENTE depois que o usuário confirmar."),
    )
    def computador(ctx, acao: str, confirmado: bool = False):
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
                if not confirmado:
                    return {"ok": False, "resumo": f"Antes de {acao}, pergunte ao usuário se ele confirma."}
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
        "Executa, lista, apaga ou recarrega (depois de editar o arquivo) as rotinas — sequências de ações como "
        "'modo trabalho' ou 'modo jogo'.",
        acao=P("string", "Ação.", enum=["executar", "listar", "apagar", "recarregar"], obrigatorio=True),
        nome=P("string", "Nome da rotina."),
    )
    def rotina(ctx, acao: str, nome: str | None = None):
        rotinas = app.rotinas
        if acao == "recarregar":
            rotinas.recarregar()
            app.apps.recarregar()
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
        if acao == "apagar":
            if rotinas.apagar(alvo.nome):
                return {"ok": True, "resumo": f"Rotina {alvo.nome} apagada."}
            return {"ok": False, "resumo": "Só consigo apagar rotinas que eu criei; as outras estão no arquivo config/rotinas.yaml."}
        rotinas.executar(alvo, ctx)
        tem_fala = any(next(iter(p)) in ("falar", "briefing") for p in alvo.passos)
        return {"ok": True, "resumo": "" if tem_fala else f"Rotina {alvo.nome} em andamento.",
                "observacao": "A rotina já anuncia o que está fazendo; confirme em no máximo 3 palavras."}

    @ferramenta(
        "criar_rotina",
        "Cria uma rotina nova a pedido do usuário. Cada passo é {acao, valor}. Ações: falar (texto), abrir (app/site), "
        "fechar (programa), tocar_youtube (busca), pesquisar (termo), volume (0-100 ou 'mudo'), midia "
        "(tocar_pausar/proxima/anterior), esperar (segundos), clima, noticias, briefing, lembretes, holograma (tipo), "
        "print, bloquear.",
        nome=P("string", "Nome curto, ex.: 'modo estudo'.", obrigatorio=True),
        passos=P("array", "Passos em ordem.", obrigatorio=True, itens={
            "type": "object",
            "properties": {"acao": {"type": "string", "enum": ACOES_SEGURAS}, "valor": {"type": "string"}},
            "required": ["acao"],
        }),
        frases=P("array", "Frases que disparam a rotina (além do nome).", itens={"type": "string"}),
        horario=P("string", "Horário HH:MM para rodar sozinha (opcional)."),
        dias=P("array", "Dias da semana para o horário: seg, ter, qua, qui, sex, sab, dom.", itens={"type": "string"}),
    )
    def criar_rotina(ctx, nome: str, passos: list, frases: list | None = None, horario: str | None = None,
                     dias: list | None = None):
        try:
            nova = app.rotinas.criar(nome, passos, frases, horario, dias)
        except ValueError as erro:
            return {"ok": False, "resumo": str(erro)}
        app.hologramas.mostrar("rotinas")
        quando = f" Ela roda sozinha às {horario}." if horario else ""
        return {"ok": True, "resumo": f"Rotina {nova.nome} criada com {len(nova.passos)} passos.{quando}"}

    # ------------------------------------------------------------------ hologramas
    @ferramenta(
        "holograma",
        "Mostra ou fecha hologramas no HUD. Tipos: clima, noticias, sistema, relogio, globo, lembretes, rotinas, camera, "
        "texto (anotação/lista que o usuário pedir para exibir).",
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
