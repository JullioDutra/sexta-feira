# Fase 7 — Sexta-Feira autônoma: agentes, engenharia reversa, memória que aprende

Objetivo: ela responde na hora, pensa só quando precisa, lembra e aprende com o que faz,
sabe se o que fez deu certo, e consegue trabalhar sozinha (agentes) no PC, no navegador,
em projetos, em vídeos e em análise de segurança/engenharia reversa.

## 1. Resposta em milissegundos, pensamento só no que é complexo

| Nível | Exemplo | Caminho | Tempo |
|---|---|---|---|
| 0 — atalho | "abre o Spotify", "volume 30" | regex local, sem IA | ~5 ms |
| 1 — simples | "quanto é 15% de 80?", "quem é o presidente da França?" | modelo rápido, sem pensamento, esforço baixo | 1º som em ~400 ms |
| 2 — complexo | "analisa esse contrato", "planeja minha semana" | modelo principal com pensamento adaptativo; **reconhecimento falado na hora** ("Deixa eu ver isso…") a partir de áudio pré-gerado | 1º som em ~50 ms |
| 3 — trabalho | "coloca um agente para…" | agente em segundo plano; ela confirma na hora e avisa quando terminar | ~50 ms |

- Classificador local (`cerebro/nivel.py`): regras + tamanho + verbos, sem chamar IA.
- Frases de reconhecimento sintetizadas uma vez na partida e guardadas em cache (variadas, conforme a personalidade).
- Pensamento (`thinking: adaptive`) ligado só no nível 2 e nos agentes; nível 1 sem pensamento.

## 2. Memória e aprendizado

Banco único `dados/memoria.db` (SQLite + FTS5, busca em milissegundos, nada sai do PC):

- **Fatos** (semântica): o que ela sabe sobre você. Categoria, fonte, confiança, uso e último uso.
- **Episódios**: cada pedido — o que foi pedido, ferramentas usadas, resultado (ok/erro), tempo.
- **Lições** (procedural): "quando X, faça Y / não faça Z", nascem de erros, correções suas
  ("não era isso", "você errou") e dos relatórios dos agentes.
- **Conhecimento**: o que ela aprendeu em análises (engenharia reversa, segurança, pesquisas dos
  agentes), com etiquetas e origem.

Uso:
- O prompt de sistema (em cache) leva só os fatos centrais. A cada pedido, a busca FTS5 junta os
  fatos, lições e conhecimentos relevantes **na mensagem do usuário** (o cache continua valendo).
- Consolidação diária ("sonho", 3h): o modelo revisa os episódios do dia, extrai fatos e lições,
  junta duplicados e enfraquece o que nunca é usado.
- Por voz: "o que você aprendeu hoje?", "o que você sabe sobre mim?", "esquece que…".
- A memória antiga (`memoria.json`) migra sozinha.

## 3. Saber o que fez e se deu certo

- Cada ferramenta devolve `ok`/erro e, quando dá, uma **verificação** depois da ação (janela
  abriu? arquivo está no destino? volume mudou?). O resultado vai para os episódios e para o
  registro de atividades com ✓/✗.
- Se a verificação falha, ela diz isso em vez de "pronto".
- "Deu certo?", "o que você fez?" listam as últimas ações com o resultado.
- Os agentes terminam com uma etapa de conferência (o objetivo foi cumprido? com que evidência?).

## 4. Agentes que ela controla

`sexta/extensoes/agentes.py` — gerente de agentes em segundo plano (vários ao mesmo tempo):
loop com o modelo principal + ferramentas, limite de passos/tempo, eventos ao vivo no
holograma **Agentes**, cancelar, relatório final, conferência e lição salva na memória.
Ações sensíveis continuam pedindo confirmação (no HUD/celular).

| Agente | Ferramentas | Fonte |
|---|---|---|
| Navegador | `agent-browser` (CLI) e Chrome DevTools MCP | vercel-labs/agent-browser, ChromeDevTools/chrome-devtools-mcp |
| Pesquisador | web + navegador, resumo com fontes | — |
| Engenharia reversa / segurança | REA (MCP): binários, Electron/JS, .NET, APK, sites, capturas de rede | morluto/rea |
| Programador | Claude Code em modo headless na pasta do projeto, com o método Superpowers (plano → testes → verificação) | obra/superpowers |
| Vídeo | HyperFrames (HTML → MP4) e ffmpeg (cortar, juntar, legendas com o Whisper) | heygen-com/hyperframes |
| Automação do PC | ferramentas do núcleo + terminal | — |

Cliente MCP genérico (`config/mcp.yaml`): qualquer servidor MCP vira ferramenta dos agentes.

## 5. Engenharia reversa como base do aprendizado

- Cada análise do REA gera **conhecimento** na memória (como o app faz X, evidências, limites).
- Modo assistente: "como o app tal faz a busca?", "cria isso no meu projeto" (REA + programador).
- Modo segurança: "esse executável é seguro?", "o que esse programa acessa na rede?",
  "revisa a segurança do PC" (portas abertas, programas na inicialização, processos sem assinatura).
- Só analisa o que é seu ou que você tem direito de analisar; nada é executado sem confirmação.

## 6. Notícias de TI e IA do dia

Nova aba **IA** no Jornal (fontes em `config/noticias.yaml`) e o comando
"notícias de TI e IA de hoje": abre o Jornal nessas abas, só as do dia, e lê as 3 principais.

## 7. Cérebro grátis (FreeLLMAPI)

`CEREBRO=livre` usa o FreeLLMAPI (fala o formato da API do Claude em `/v1/messages`) e,
com `CEREBRO_RESERVA=livre`, ele assume quando o Claude falha (sem crédito, limite, rede).

## 8. Acesso completo ao PC

Preferência **Autonomia** (`cautelosa | normal | total`). Em *total*, as ações que hoje pedem
"sim" rodam direto; só as irreversíveis (apagar, formatar, desligar, terminal destrutivo) continuam
pedindo confirmação (e rosto, se configurado).

## Ordem de entrega

1. Núcleo: níveis de resposta + reconhecimento instantâneo, memória nova, verificação, autonomia,
   notícias de TI/IA, cérebro livre.
2. Agentes + cliente MCP + navegador + programador.
3. Engenharia reversa/segurança (REA) ligada à memória.
4. Vídeo (HyperFrames + ffmpeg).
5. Frentes pendentes da Fase 5/6: traje, sentinela, oficina, mãos livres.
