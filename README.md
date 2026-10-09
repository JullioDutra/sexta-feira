# Sexta-Feira

Assistente pessoal para Windows 11: você fala "Sexta-Feira", ela responde com voz, controla o PC, mostra clima e notícias em hologramas que você pega e arrasta com as mãos na frente da webcam, reconhece seu rosto e acompanha você pelo celular. O cérebro roda no seu computador com o Ollama — sem mensalidade.

Inspirada no projeto [vannu07/jarvis](https://github.com/vannu07/jarvis), reescrita do zero.

---

## O que ela faz

| Área | Como funciona |
|---|---|
| **Voz** | Fica esperando "Sexta-Feira" (offline, Vosk). Grava o pedido, transcreve no PC (Whisper) e responde com voz neural. Depois de responder, continua ouvindo por alguns segundos para você emendar outro pedido sem repetir o nome. Dizer "Sexta-Feira" enquanto ela fala interrompe. |
| **Cérebro** | Modelo local no Ollama (padrão `qwen3.5:9b`) com 16 ferramentas: ela decide sozinha quando consultar o clima, abrir um app, criar um lembrete etc. Comandos simples ("pausa", "volume 40", "modo jogo") nem passam pela IA e respondem na hora. |
| **Rosto** | Cadastro de ~20 amostras em poses diferentes (só vetores numéricos ficam salvos, nenhuma foto). Com a proteção ligada, ela só obedece a você e exige uma piscada para desbloquear, então foto não engana. |
| **Hologramas** | HUD 3D com núcleo animado e painéis: clima, notícias, sistema, relógio, globo, lembretes, rotinas, câmera, notas e prints. Você chama por voz ou pela barra lateral e mexe com as mãos, o mouse ou o toque. |
| **Automações** | Abre apps (inclusive da Microsoft Store), sites e pastas; fecha programas; controla mídia e volume; tira print; bloqueia a tela; desliga/reinicia com confirmação; pesquisa e toca no YouTube. |
| **Rotinas** | "Modo trabalho", "modo jogo", "bom dia"... sequências de ações num arquivo YAML, disparadas por frase ou por horário. Você também cria rotinas por voz. |
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
| Hologramas | "mostra o globo", "mostra o sistema", "anota na tela: comprar pão, café e leite", "fecha os hologramas" |
| Gestos | "liga os gestos", "desliga os gestos" |
| Memória | "lembra que meu aniversário é 12 de março", "o que você sabe sobre mim?" |
| Privacidade | "modo privado" (ela se bloqueia até ver seu rosto), "para de ouvir" |

Em uma sexta-feira à tarde, ela comemora.

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

Em `config/apps.yaml` você cria apelidos ("meu jogo" → caminho do .exe, "campeonato" → endereço do seu sistema). Depois de editar, diga "recarrega as rotinas" ou use **Ajustes → Rotinas e apelidos → Recarregar arquivos**. A ação `executar` (rodar um comando do Windows) só é aceita em rotinas que você escreve à mão — rotinas criadas por voz não podem usá-la.

---

## Configuração (`.env`)

| Variável | Para quê |
|---|---|
| `OLLAMA_MODELO` | modelo com suporte a ferramentas: `qwen3.5:9b` (padrão), `qwen3.5:4b` (PCs simples), `qwen3.6:27b` (GPUs de 24 GB) |
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

Roda no seu PC: ativação por voz, transcrição, cérebro (Ollama), reconhecimento facial e de mãos, lembretes, rotinas e memória. Saem para a internet apenas:

- **clima** — coordenadas da cidade para o Open-Meteo;
- **notícias** — o assunto pesquisado no Google Notícias;
- **voz neural** — o texto de cada resposta vai para o serviço de voz da Microsoft (use `VOZ_MOTOR=windows` para ficar 100% offline);
- **YouTube e pesquisas** — quando você pede.

Seus dados ficam na pasta `dados/` (apague a pasta para zerar tudo). O acesso ao HUD exige uma chave que a própria Sexta-Feira gera, então sites abertos no navegador não conseguem mandar comandos para ela.

---

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| "Não consegui falar com o Ollama" | Abra o Ollama (ícone da lhama) e confira com `ollama list` se o modelo do `.env` está baixado. |
| Ela não ouve o nome | `iniciar.bat testar-ativacao` mostra quando ela ouve. Confira o microfone padrão do Windows ou `MICROFONE=` no `.env`. |
| Responde devagar | Use `qwen3.5:4b` e `WHISPER_MODELO=base`, ou uma GPU NVIDIA. |
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
| `sexta/habilidades` | clima, notícias, Windows, apps, rotinas, lembretes, hologramas |
| `sexta/servidor.py` | API, WebSocket, segurança de acesso, HTTPS do celular |
| `hud/` | interface (React + TypeScript + Tailwind + Three.js); `hud/dist` já vem compilado |
| `config/` | rotinas e apelidos |
| `dados/` | criado na primeira execução: preferências, rosto, lembretes, logs, modelos |

### Desenvolvimento

```bat
.venv\Scripts\pip install pytest
.venv\Scripts\python -m pytest tests
```

Para mexer no HUD (precisa do Node.js): `cd hud`, `npm install`, `npm run dev` (abre em `localhost:5173` com a Sexta-Feira rodando) e `npm run build` para gerar `hud/dist`.

Comandos úteis: `iniciar.bat baixar`, `iniciar.bat diagnostico`, `iniciar.bat microfones`, `iniciar.bat testar-voz "olá"`, `iniciar.bat testar-ativacao`, `iniciar.bat pin`, `iniciar.bat dispositivos`, `iniciar.bat abrir`.
