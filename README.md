# Sexta-Feira

Assistente pessoal para Windows 11: você fala "Sexta-Feira", ela responde com voz, controla o PC, mostra clima e notícias em hologramas que você pega e arrasta com as mãos na frente da webcam, reconhece seu rosto e acompanha você pelo celular. O cérebro pode ser o **Claude** (na nuvem: mais rápido e inteligente, pago por uso) ou um modelo local no **Ollama** (gratuito e offline).

Inspirada no projeto [vannu07/jarvis](https://github.com/vannu07/jarvis), reescrita do zero.

---

## O que ela faz

| Área | Como funciona |
|---|---|
| **Voz** | Fica esperando "Sexta-Feira" (offline, Vosk). Grava o pedido, transcreve no PC (Whisper) e responde com voz neural. Depois de responder, continua ouvindo por alguns segundos para você emendar outro pedido sem repetir o nome. Dizer "Sexta-Feira" enquanto ela fala interrompe. |
| **Cérebro** | Modelo local no Ollama (padrão `qwen3.5:9b`) com 24 ferramentas: ela decide sozinha quando consultar o clima, abrir um app, achar um arquivo etc. A maioria dos comandos do dia a dia ("abre o Spotify e coloca volume 30", "brilho 70", "coloca o VS Code na esquerda") nem passa pela IA e responde em milissegundos. Opcional: dois cérebros, um modelo pequeno para comandos e o maior para conversa e análise. |
| **Arquivos** | "Acha o PDF do contrato de março", "abre o 2", "arquivos recentes", "organiza os Downloads por data", mover, renomear e mandar para a Lixeira. |
| **Janelas** | Focar, minimizar, encaixar lado a lado, mandar para o outro monitor e layouts salvos ("layout trabalho": VS Code à esquerda, navegador à direita). |
| **Visão** | "Analisa a tela": ela tira um print e o modelo com visão explica o erro, a planilha ou o site. "O que é isso?" olha pela webcam. |
| **PC** | O que está pesando (CPU, RAM e GPU por app), fechar travados, brilho, Wi-Fi, Bluetooth, modo escuro, plano de energia, não perturbe, saída de áudio e terminal com lista de comandos permitidos. |
| **Área de transferência** | "Resume o que eu copiei", "traduz isso que copiei", "corrige o texto que copiei e cola". |
| **Segurança** | Três níveis: livre (abrir, ler), confirmação por voz (fechar, mover) e rosto + confirmação (apagar, desligar, comando fora da lista). Tudo fica no holograma **Registro de atividades**. |
| **Rosto** | Cadastro de ~20 amostras em poses diferentes (só vetores numéricos ficam salvos, nenhuma foto). Com a proteção ligada, ela só obedece a você e exige uma piscada para desbloquear, então foto não engana. |
| **Hologramas** | HUD 3D com núcleo animado e painéis: clima, notícias, sistema, relógio, globo, lembretes, rotinas, câmera, notas e prints. Você chama por voz ou pela barra lateral e mexe com as mãos, o mouse ou o toque. |
| **Automações** | Abre apps (inclusive da Microsoft Store), sites e pastas; fecha programas; controla mídia e volume; tira print; bloqueia a tela; desliga/reinicia com confirmação; pesquisa e toca no YouTube. |
| **Protocolos** | Automações com gatilho → condição → ação. Gatilhos: frase, horário, desbloquear o PC, abrir/fechar um app, bateria baixa, pendrive, arquivo novo numa pasta, rede Wi-Fi, voltar ao PC. Condições: dias, faixa de horário, em reunião, chovendo, rede. Crie por voz ("toda vez que eu abrir o Valorant, fecha o Chrome e coloca o PC no desempenho máximo"): ela mostra o protocolo e você aprova. |
| **Jornal** | Briefing matinal de até 2 minutos (clima, agenda, 5 notícias do Brasil e 5 de tecnologia). Holograma com abas Destaques / Brasil / Tecnologia / Seus temas / Salvas; a mesma notícia de várias fontes vira uma só. "Me avisa quando sair notícia de RTX 60" gera alerta por voz e no celular. |
| **Lembretes e alarmes** | "Me lembra de ligar pro João amanhã às 10h", "me acorda às 7 todo dia útil", "timer de 15 minutos". |
| **Celular** | Mesma interface no navegador do celular: segure para falar, escreva, toque nos atalhos, veja os painéis e ouça a resposta no próprio celular. |
| **Memória** | "Lembra que meu time é o Cruzeiro" — ela guarda e usa nas próximas conversas. |

---

## Instalação (Windows 11)

1. Baixe e extraia esta pasta onde quiser (ex.: `C:\Sexta-Feira`).
2. Clique duas vezes em **`instalar.bat`**. Ele:
   - instala o Python 3.12 e o Ollama pelo `winget`, se faltarem (pergunta antes);
   - cria o ambiente `.venv` e instala as bibliotecas;
   - baixa os modelos de rosto, mãos e voz (~600 MB) e o modelo de IA do Ollama (alguns GB);
   - cria o atalho **Sexta-Feira** na área de trabalho e, se você quiser, coloca ela para iniciar com o Windows.
3. Abra pelo atalho. O HUD abre numa janela do Edge e a configuração inicial pergunta seu nome, sua cidade, cadastra seu rosto e mostra o QR code para o celular.

Na primeira vez, o Windows pergunta se o Python pode usar a rede: **permita em "Redes privadas"** (é o que deixa o celular conversar com o PC).

> **Precisa:** webcam e microfone. Uma placa de vídeo com 8 GB ou mais deixa o modelo `qwen3.5:9b` rápido. Em PC mais modesto, troque para `qwen3.5:4b` no arquivo `.env` (e rode `ollama pull qwen3.5:4b`).

### Iniciar e parar

- **Atalho Sexta-Feira**: inicia sem janela; o ícone dela aparece perto do relógio do Windows (abrir HUD, ligar/desligar microfone, sair).
- **`iniciar.bat`**: inicia mostrando os registros — útil para ver o que está acontecendo.
- Rodar de novo com ela já aberta só reabre o HUD.
- No HUD, **F11** deixa em tela cheia — fica ótimo num segundo monitor ou numa TV.

---

## Escolhendo o cérebro

| | Claude (nuvem) | Ollama (local) |
|---|---|---|
| Qualidade | muito alta (Claude Opus 5.5) | depende do modelo que cabe na sua placa |
| Velocidade | rápida em qualquer PC; prompt em cache por 1 h | ótima só se o modelo couber inteiro na placa de vídeo |
| Custo | pago por uso (ver abaixo) | grátis |
| Internet | precisa | não precisa |

**Para usar o Claude:** crie uma chave em [console.anthropic.com](https://console.anthropic.com) (API Keys), coloque em `ANTHROPIC_API_KEY=` no `.env` e reinicie. Com `CEREBRO=auto` (padrão) ela passa a usar o Claude sozinha; sem chave, volta ao Ollama.

- **Dois cérebros:** comandos curtos vão para o **Claude Haiku 5.5** (rápido e baratíssimo) e conversa, análise e planejamento para o **Claude Opus 5.5** (`CLAUDE_MODELO` / `CLAUDE_MODELO_RAPIDO`).
- **Esforço:** na voz ela pensa pouco para responder rápido (`CLAUDE_ESFORCO_VOZ=low`); no texto, `medium`. Suba para `high` se preferir respostas mais elaboradas.
- **Custo aproximado:** comandos resolvidos por atalho não custam nada. Um pedido que vai ao Opus custa em torno de US$ 0,005 (com o cache); no Haiku, uma fração disso. Acompanhe o gasto no console da Anthropic e, se quiser, defina um limite mensal por lá.
- **Recusas:** se um filtro de segurança do Opus recusar um pedido, a própria API tenta de novo com o modelo recomendado (fallback automático, ligado por padrão).
- **Sem internet** os atalhos continuam funcionando; o resto avisa que o cérebro está fora.

**Se continuar no Ollama e estiver lento:** o log e o HUD agora avisam quando o modelo não coube na placa de vídeo e está rodando na memória RAM/CPU (a causa mais comum de lentidão extrema e de erros de memória). Nesse caso use um modelo menor (`qwen3.5:4b`), reduza `OLLAMA_CONTEXTO` ou passe para o Claude.

**Memória:** a conversa sobrevive a reinícios por até 6 horas (`dados/historico.json`), e ela guarda sozinha fatos pessoais duradouros ("meu time é o Cruzeiro") em `dados/memoria.json`, que entram em todas as conversas.

## Falando com ela

Diga **"Sexta-Feira"** e o pedido, numa frase só ou com uma pausa (ela responde "Pois não?"). Sem microfone por perto, aperte **espaço** no HUD para falar ou **/** para escrever. **Esc** interrompe.

| Para | Diga |
|---|---|
| Clima | "como está o tempo?", "vai chover amanhã?", "previsão para o fim de semana em Florianópolis" |
| Notícias | "quais as notícias?", "notícias de tecnologia", "o que saiu sobre o Cruzeiro?" |
| Abrir e fechar | "abre o Spotify", "abre o YouTube", "abre a pasta Downloads", "fecha o Chrome" |
| Mídia e volume | "pausa", "próxima", "volume 30", "aumenta o volume", "muta" |
| Web | "pesquisa receita de pão de queijo", "toca Legião Urbana no YouTube" |
| Computador | "tira um print", "bloqueia o computador", "como está o PC?", "desliga o computador" (ela confirma antes) |
| Lembretes | "me lembra de tomar remédio às 22h todo dia", "me acorda amanhã às 6h30", "timer de 10 minutos", "quais meus lembretes?", "cancela o lembrete do remédio" |
| Rotinas | "modo trabalho", "modo jogo", "bom dia", "cria uma rotina chamada modo estudo que abre o Notion e põe volume 20" |
| Hologramas | "mostra o globo", "mostra o sistema", "anota na tela: comprar pão, café e leite", "fecha os hologramas", "mostra o registro de atividades" |
| Arquivos | "acha o PDF do contrato de março", "abre o primeiro", "mostra o 2 na pasta", "arquivos recentes", "move o boleto para Documentos", "renomeia o 1 para boleto outubro", "organiza os Downloads" |
| Janelas | "foca no Spotify", "coloca o VS Code na esquerda", "coloca o VS Code e o Chrome lado a lado", "manda o Chrome pro outro monitor", "minimiza tudo", "layout trabalho", "salva esse layout como estudo" |
| Tela e câmera | "analisa a tela", "que erro é esse?", "o que é isso?" (segurando um objeto), "lê esse papel" |
| Área de transferência | "resume o que eu copiei", "traduz o que eu copiei para inglês", "corrige o texto que copiei e cola" |
| Processos | "o que está pesando?", "qual programa está usando mais memória?", "consumo de GPU por app", "fecha os programas travados" |
| Configurações | "brilho 70", "aumenta o brilho", "desliga o Wi-Fi", "liga o Bluetooth", "modo escuro", "não perturbe", "coloca o PC no modo desempenho máximo", "muda o som para o fone" |
| Terminal | "qual meu IP?", "roda o git status", "o winget tem atualizações?" |
| Gestos | "liga os gestos", "desliga os gestos" |
| Memória | "lembra que meu aniversário é 12 de março", "o que você sabe sobre mim?" |
| Privacidade | "modo privado" (ela se bloqueia até ver seu rosto), "para de ouvir" |

Dá para emendar comandos: "abre o Spotify e coloca volume 30", "fecha o Discord e liga o não perturbe".

Em uma sexta-feira à tarde, ela comemora.

### Segurança em três níveis

| Nível | Exemplos | O que acontece |
|---|---|---|
| **Livre** | abrir, ler, buscar, volume, janelas, brilho | executa na hora |
| **Confirma por voz** | fechar programa, mover/renomear arquivo, organizar Downloads, encerrar processo | ela pergunta "Confirma: fechar Chrome?" e espera um "sim" (ou "não") |
| **Rosto + confirmação** | apagar arquivo, desligar/reiniciar, comando fora da lista | depois do "sim", confere seu rosto pela câmera antes de fazer |

A confirmação é feita pelo próprio programa, não pelo modelo de IA, então nenhuma resposta da IA consegue "se autoconfirmar". Se você mudar de assunto ou passar 90 segundos, o pedido é descartado. Rotinas que você escreveu não pedem confirmação a cada passo. Pelo celular pareado (ou HUD do PC), o nível 3 vale com a confirmação, já que lá não há câmera. Tudo — o que foi feito, confirmado, negado ou cancelado — vai para o holograma **Registro de atividades** (e para `dados/atividades.jsonl`). "O que você fez hoje?" resume.

### Por que ela responde rápido

- **Atalhos sem IA** cobrem a maioria dos comandos (inclusive compostos) e respondem em milissegundos.
- **Prompt estável**: as instruções e as ferramentas não mudam entre pedidos, então o Ollama reaproveita o que já processou (cache) e só lê a parte nova. A hora vai junto da sua mensagem.
- **Sem segunda volta**: quando o resultado da ferramenta já é a resposta ("Volume em 30%", "Abrindo Spotify"), ela fala direto em vez de pedir ao modelo para redigir.
- **Pré-aquecimento**: ao iniciar, o modelo é carregado e o prompt de sistema já é processado; `OLLAMA_MANTER_CARREGADO=4h` evita recarregar.
- **Dois cérebros** (opcional): `OLLAMA_MODELO_RAPIDO=qwen3.5:4b` para comandos curtos; o principal fica com conversa, planejamento e análise.
- O log mostra quanto cada pedido levou e por qual caminho foi (`Pedido resolvido por atalho em 12 ms`).

---

## Hologramas com as mãos

Ligue em **Gestos** (canto superior direito) ou diga "liga os gestos". Um espelhinho da câmera aparece no canto para você se posicionar; fique a uns 50–80 cm da webcam, com a mão bem iluminada.

| Gesto | Efeito |
|---|---|
| **Pinça** (polegar + indicador) sobre um painel | pega o painel |
| Pinça e mover | arrasta |
| Pinça e aproximar/afastar a mão da câmera | traz para perto / empurra para o fundo |
| Pinça e girar o pulso | gira o painel |
| Segurando com uma mão, **pinça com a outra** e abrir/fechar as mãos | amplia/reduz e gira |
| Soltar com um "arremesso" rápido para fora | fecha o painel |
| **Mão aberta parada** sobre um painel por ~1 s | amplia no centro (repita para voltar) |
| **Apontar** com o indicador e esperar ~1 s sobre um botão ou notícia | clica |
| Pinça rápida sobre um botão | clica |
| Pinça no globo | gira o planeta |

Mouse e toque também funcionam: arrastar move, roda do mouse amplia (Shift + roda gira), dois cliques no título amplia, e no celular dois dedos ampliam e giram. As posições ficam salvas para a próxima vez. A sensibilidade das mãos está em **Ajustes**.

---

## Celular

1. No HUD: **Ajustes → Celulares → Parear um celular**.
2. Aponte a câmera do celular para o QR code (mesmo Wi-Fi do PC).
3. Na primeira vez o navegador avisa que a conexão "não é particular": toque em **Avançado → Continuar**. É o certificado gerado pelo seu próprio PC — ele é necessário porque o navegador só libera o microfone em páginas HTTPS.
4. No Chrome/Safari, use **Adicionar à tela inicial** para ter um ícone de app.

No celular você **segura o botão para falar** (a resposta toca no celular), escreve, usa os atalhos e vê os painéis. Celulares pareados podem ser removidos em Ajustes a qualquer momento.

### Fora de casa (opcional, com o Tailscale)

O [Tailscale](https://tailscale.com) cria uma rede privada entre seus aparelhos, com HTTPS válido e sem abrir portas no roteador:

1. Instale o Tailscale no PC e no celular, com a mesma conta.
2. No PC (PowerShell): `tailscale serve --bg 8765`
3. Copie o endereço mostrado (ex.: `https://meu-pc.tail1234.ts.net`) para `ENDERECO_EXTERNO=` no `.env` e reinicie a Sexta-Feira.
4. Pareie de novo escolhendo "De qualquer lugar (Tailscale)" no QR code.

---

## Rosto, bloqueio e o desbloqueio do Windows

Há dois bloqueios diferentes, e é importante entender a diferença:

**A tela de bloqueio do Windows** só aceita os métodos oficiais do sistema — nenhum programa comum consegue (nem deveria conseguir) destravá-la. Para entrar no Windows olhando para a câmera, use o **Windows Hello**:
*Configurações → Contas → Opções de entrada → Reconhecimento facial (Windows Hello)*.
Ele precisa de uma câmera com infravermelho compatível (muitos notebooks já têm; para desktop existem webcams "Windows Hello"). Sem ela, a opção **Impressão digital** (leitor USB) ou o **PIN** do Windows funcionam.

**O bloqueio da Sexta-Feira** é dela mesma. Com seu rosto cadastrado e "Só obedecer ao meu rosto" ligado:
- quando o Windows bloqueia (Win+L ou inatividade), ela também se bloqueia;
- ao você voltar e entrar no Windows, ela liga a câmera, confere seu rosto, pede uma piscada e te dá boas-vindas;
- de tempos em tempos (padrão: 30 min) ela reconfere seu rosto antes de obedecer a um comando de voz — leva menos de um segundo se você estiver de frente para a câmera;
- pelo celular pareado, um **PIN** (definido em Ajustes) desbloqueia a Sexta-Feira;
- com o PC bloqueado ela continua rodando, então pelo celular você ainda consegue pedir clima, lembretes, tocar música etc.

O reconhecimento facial da Sexta-Feira é bom para o dia a dia, mas não substitui a segurança do Windows — mantenha uma senha ou PIN forte no sistema.

---

## Jornal (central de notícias)

- **"Abre o jornal"** (ou o ícone na barra lateral): abas **Destaques**, **Brasil**, **Tecnologia**, **Seus temas** e **Salvas**. A mesma notícia dada por várias fontes aparece uma vez só, com "(3 fontes)" — e sobe nos destaques.
- **Toque ou pinça rápida numa notícia:** ela abre a matéria, resume em até 5 frases e lê em voz alta. **Arraste para o lado** (ou toque no marcador) para salvar para depois.
- Por voz: "lê a segunda notícia de tecnologia", "salva a primeira", "me avisa quando sair notícia de RTX 60", "para de me avisar sobre RTX 60", "quais temas você acompanha?".
- **Seus temas:** a cada 15 minutos ela procura novidades e avisa por voz, no HUD e no celular — só do que saiu depois que você pediu.
- **Briefing:** "bom dia" ou "briefing" — saudação, clima, agenda do dia, 5 manchetes do Brasil, 5 de tecnologia e seus temas, em até 2 minutos (a IA escreve o roteiro; sem IA, ela lê as manchetes). Para ouvir todo dia: "agenda o briefing para as 7h30 nos dias úteis" (vira um protocolo que dá para ajustar no editor).
- **Fontes** em `config/noticias.yaml`: Google Notícias e g1 (Brasil); Tecnoblog, Canaltech, Olhar Digital, The Verge, Hacker News e GitHub em alta (tecnologia). Qualquer feed RSS/Atom serve; crie outras categorias (ex.: `esportes:`) e elas entram nos Destaques.

## Protocolos (automações)

Peça por voz e aprove:

- "Sexta, toda vez que eu abrir o Valorant, fecha o Chrome e coloca o PC no desempenho máximo."
- "Quando chegar um PDF em Downloads, me avisa no celular."
- "Quando a bateria ficar abaixo de 15%, coloca no modo economia e baixa o brilho."
- "Quando eu voltar ao PC, se não estiver em reunião, me dá o resumo do dia."

Ela monta o protocolo, mostra no holograma (Quando / Se / Então) e só salva depois do seu "sim" (ou do botão **Aprovar**). Depois: "desativa o protocolo modo valorant", "apaga o protocolo...", "quais são meus protocolos?".

No arquivo (`config/rotinas.yaml`), o formato completo é:

```yaml
rotinas:
  modo valorant:
    gatilhos:
      - app_aberto: Valorant            # também: frase, horario, desbloquear, app_fechado,
    condicoes:                          # bateria_baixa, pendrive, arquivo_novo, wifi, voltar_ao_pc
      - entre: "18:00-23:59"            # também: dias, em_reuniao, chovendo, wifi
      - em_reuniao: false
    passos:
      - fechar: Chrome
      - plano_energia: desempenho maximo
      - notificar: "Modo jogo ligado"   # vai para o celular
```

Textos podem usar `{app}`, `{arquivo}`, `{nome_arquivo}`, `{rede}`, `{bateria}`. "Em reunião" = outro programa usando o microfone (Teams, Zoom, Meet, Discord). "Voltar ao PC" usa o tempo sem mexer no mouse/teclado; em **Ajustes** dá para ligar a checagem pelo rosto na câmera (`presenca_camera`). Protocolos só disparam de novo depois de 1 minuto.

**Notificar no celular:** chega nos celulares pareados com o HUD aberto. Para receber mesmo com o celular bloqueado, instale o app gratuito [ntfy](https://ntfy.sh), assine um tópico com nome difícil de adivinhar e coloque o mesmo nome em `NTFY_TOPICO` no `.env` (o texto da notificação passa pelo servidor do ntfy).

## Rotinas e apelidos

Edite `config/rotinas.yaml` (o arquivo explica todas as ações). Exemplo:

```yaml
rotinas:
  modo estudo:
    frases: ["modo estudo", "hora de estudar"]
    horario: "19:00"          # opcional: roda sozinha
    dias: [seg, ter, qua, qui]
    passos:
      - falar: "Bons estudos."
      - fechar: "Discord"
      - abrir: "Notion"
      - tocar_youtube: "lofi para estudar"
      - volume: 25
      - holograma: relogio
```

Os passos também podem ser `layout: trabalho`, `minimizar_tudo: true`, `plano_energia: desempenho maximo`, `nao_perturbe: true`, `modo_escuro: true`, `brilho: 40` e `organizar_downloads: true`. O exemplo `fantasma` ("protocolo fantasma") minimiza tudo e silencia.

**Layouts de janelas** ficam em `config/layouts.yaml` (cada app com `posicao`: esquerda, direita, cima, baixo, quartos, centro ou tela_cheia, e `monitor` opcional). Se o app estiver fechado, ela abre e espera a janela. "Salva esse layout como estudo" grava o jeito atual das janelas em `config/layouts_criados.yaml`.

**Terminal**: `config/terminal.yaml` tem a lista de comandos que ela roda sozinha (`ping *` aceita qualquer argumento; sem `*`, só o comando exato). Fora da lista, ou com `&`, `|`, `>`, ela pede confirmação com rosto.

Em `config/apps.yaml` você cria apelidos ("meu jogo" → caminho do .exe, "campeonato" → endereço do seu sistema). Depois de editar, diga "recarrega as rotinas" ou use **Ajustes → Rotinas e apelidos → Recarregar arquivos**. A ação `executar` (rodar um comando do Windows) só é aceita em rotinas que você escreve à mão — rotinas criadas por voz não podem usá-la.

---

## Configuração (`.env`)

| Variável | Para quê |
|---|---|
| `OLLAMA_MODELO` | modelo com suporte a ferramentas: `qwen3.5:9b` (padrão), `qwen3.5:4b` (PCs simples), `qwen3.6:27b` (GPUs de 24 GB) |
| `OLLAMA_MODELO_RAPIDO` | opcional: modelo menor só para comandos curtos (ex.: `qwen3.5:4b`) |
| `OLLAMA_MODELO_VISAO` | modelo com visão para "analisa a tela" (vazio = o principal) |
| `OLLAMA_MANTER_CARREGADO` | quanto tempo o modelo fica na memória sem uso (padrão `4h`; `-1` = sempre) |
| `PASTAS_ARQUIVOS` | pastas extras para a busca de arquivos, separadas por vírgula |
| `OLLAMA_PENSAR` | `sim` deixa o modelo "pensar" antes de responder (mais lento) |
| `WHISPER_MODELO` | `small` (padrão), `base` (mais rápido), `large-v3-turbo` (melhor, com GPU NVIDIA) |
| `VOZ_MOTOR` | `edge` (voz neural, online) ou `windows` (100% offline) |
| `VOZ`, `VOZ_VELOCIDADE` | voz e ritmo da fala |
| `ATIVACAO_FRASES` | palavras de ativação, separadas por vírgula (ex.: `sexta feira, ei sexta`) |
| `MICROFONE`, `ALTO_FALANTE` | número ou parte do nome do dispositivo (`iniciar.bat microfones` lista) |
| `CAMERA_INDICE`, `CAMERA_BACKEND` | qual webcam usar; troque o backend para `msmf` se a câmera não abrir |
| `PORTA`, `PORTA_CELULAR`, `LIBERAR_CELULAR` | portas do HUD e do acesso pelo celular |
| `ENDERECO_EXTERNO` | endereço do Tailscale |

Preferências do dia a dia (nome, cidade, tema âmbar/ciano, segurança, voz, sensibilidade das mãos) ficam no próprio HUD, em **Ajustes**.

### Palavra de ativação mais precisa (opcional)

Como "sexta-feira" também é um dia da semana, ela só ativa quando o nome é a primeira coisa dita depois de uma pausa. Se quiser ainda mais precisão, treine a palavra "Sexta-Feira" em português no [console da Picovoice](https://console.picovoice.ai) (gratuito para uso pessoal), rode `.venv\Scripts\pip install pvporcupine` e preencha `ATIVACAO_MOTOR=porcupine`, `PORCUPINE_CHAVE`, `PORCUPINE_ARQUIVO` (o `.ppn`) e `PORCUPINE_MODELO` (o `porcupine_params_pt.pv`).

---

## Privacidade

Roda no seu PC: ativação por voz, transcrição, reconhecimento facial e de mãos, lembretes, rotinas, memória e — com o Ollama — o cérebro. Saem para a internet apenas:

- **cérebro Claude** (se você usar) — o texto dos pedidos que não são atalhos, o histórico recente da conversa, os fatos da memória e os resultados das ferramentas; em "analisa a tela"/"o que é isso?", a imagem; em "resume o que eu copiei", o texto copiado. Tudo vai para a API da Anthropic;

- **clima** — coordenadas da cidade para o Open-Meteo;
- **notícias** — o Jornal baixa os feeds das fontes de `config/noticias.yaml`, os temas que você acompanha são pesquisados no Google Notícias e, ao ler uma matéria, a página dela é aberta;
- **voz neural** — o texto de cada resposta vai para o serviço de voz da Microsoft (use `VOZ_MOTOR=windows` para ficar 100% offline);
- **YouTube e pesquisas** — quando você pede.

Seus dados ficam na pasta `dados/` (apague a pasta para zerar tudo). O acesso ao HUD exige uma chave que a própria Sexta-Feira gera, então sites abertos no navegador não conseguem mandar comandos para ela.

---

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| "Não consegui falar com o Ollama" | Abra o Ollama (ícone da lhama) e confira com `ollama list` se o modelo do `.env` está baixado. |
| Ela não ouve o nome | `iniciar.bat testar-ativacao` mostra quando ela ouve. Confira o microfone padrão do Windows ou `MICROFONE=` no `.env`. |
| Responde devagar | Veja no log por qual caminho o pedido foi e quanto levou. Se o seu `.env` é antigo, troque `OLLAMA_MANTER_CARREGADO=30m` por `4h`. Use `OLLAMA_MODELO_RAPIDO=qwen3.5:4b` (dois cérebros), `WHISPER_MODELO=base`, ou uma GPU NVIDIA. |
| "Não enxerga imagens" | Defina `OLLAMA_MODELO_VISAO` com um modelo de visão (ex.: `qwen2.5vl:7b` ou `gemma3:12b`) e rode `ollama pull` dele. |
| Brilho não muda | Monitores de PC de mesa normalmente não aceitam ajuste de brilho pelo Windows (só notebooks). |
| Câmera não abre | Feche outros apps que usam a câmera; tente `CAMERA_BACKEND=msmf` ou outro `CAMERA_INDICE`. |
| Celular não conecta | Mesmo Wi-Fi; permita o Python no firewall em "Redes privadas"; use o endereço `https://` do QR code. |
| Sem voz | Sem internet a voz neural falha e ela usa a do Windows; instale a voz "Português (Brasil)" em Configurações → Hora e idioma → Fala. |
| Diagnóstico completo | `iniciar.bat diagnostico` ou **Ajustes → Diagnóstico** |

Os registros ficam em `dados/logs/sexta.log`.

---

## Como é por dentro

```
 microfone ─► Vosk ("Sexta-Feira") ─► gravação ─► Whisper ─┐
 celular (áudio/texto) ─────────────────────────────────────┤
 HUD (texto/botões) ────────────────────────────────────────┤
                                                            ▼
                        atalhos rápidos ──► Agente ◄──► Ollama (qwen3.5)
                                              │ ferramentas
        ┌──────────┬──────────┬──────────┬───┴──────┬───────────┬──────────┐
     clima     notícias   Windows    lembretes   rotinas    hologramas  memória
                                                                  │
 webcam ─► câmera ─┬─► rosto (YuNet + SFace + piscada) ─► bloqueio da Sexta
                   └─► mãos (MediaPipe) ──────────────────────┐
                                                              ▼
  voz (edge-tts) ◄── frases        servidor FastAPI + WebSocket ─► HUD (React + Three.js)
```

| Pasta | Conteúdo |
|---|---|
| `sexta/cerebro` | agente, cliente do Ollama, ferramentas, atalhos, memória |
| `sexta/voz` | microfone, ativação, transcrição, fala |
| `sexta/visao` | câmera compartilhada, rosto, mãos, prévia MJPEG |
| `sexta/habilidades` | clima, notícias, Windows, apps, rotinas, lembretes, hologramas, arquivos, janelas, visão, processos, configurações, área de transferência, terminal |
| `sexta/atividades.py` | registro de atividades (holograma e `dados/atividades.jsonl`) |
| `sexta/servidor.py` | API, WebSocket, segurança de acesso, HTTPS do celular |
| `hud/` | interface (React + TypeScript + Tailwind + Three.js); `hud/dist` já vem compilado |
| `config/` | rotinas, apelidos, layouts de janelas e comandos permitidos no terminal |
| `dados/` | criado na primeira execução: preferências, rosto, lembretes, logs, modelos |

### Desenvolvimento

```bat
.venv\Scripts\pip install pytest
.venv\Scripts\python -m pytest tests
```

Para mexer no HUD (precisa do Node.js): `cd hud`, `npm install`, `npm run dev` (abre em `localhost:5173` com a Sexta-Feira rodando) e `npm run build` para gerar `hud/dist`.

Comandos úteis: `iniciar.bat baixar`, `iniciar.bat diagnostico`, `iniciar.bat microfones`, `iniciar.bat testar-voz "olá"`, `iniciar.bat testar-ativacao`, `iniciar.bat pin`, `iniciar.bat dispositivos`, `iniciar.bat abrir`.
