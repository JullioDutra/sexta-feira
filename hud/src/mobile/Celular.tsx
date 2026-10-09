// Interface do celular: conversar, falar segurando o botão, atalhos e painéis.
import { useEffect, useRef, useState } from "react";
import { ErroApi, api, codigoDePareamentoNaUrl, comToken, limparCodigoDaUrl, nomeDoAparelho, salvarToken, token } from "../lib/api";
import { conexao } from "../lib/socket";
import { useHud } from "../lib/store";
import type { Holograma } from "../lib/tipos";
import Clima from "../holograms/Clima";
import { GlifoTipo, Icone } from "../holograms/Glifos";
import { Atividades, Lembretes, Protocolo, Rotinas } from "../holograms/Listas";
import Jornal from "../holograms/Jornal";
import Noticias from "../holograms/Noticias";
import Sistema from "../holograms/Sistema";
import Orbe from "./Orbe";

const PALAVRA: Record<string, string> = {
  iniciando: "Iniciando",
  inativa: "Pronta",
  ouvindo: "Ouvindo",
  pensando: "Pensando",
  falando: "Falando",
  verificando: "Confirmando identidade",
};

let audioDesbloqueado = false;
const tocador = typeof Audio !== "undefined" ? new Audio() : null;

function desbloquearAudio() {
  // iPhone só toca áudio depois de um toque do usuário
  if (audioDesbloqueado || !tocador) return;
  tocador.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";
  tocador.play().catch(() => {});
  audioDesbloqueado = true;
}

function tocar(caminho: string) {
  if (!tocador) return;
  tocador.src = comToken(caminho);
  tocador.play().catch(() => {});
}

function Pareamento({ aoParear }: { aoParear: () => void }) {
  const [codigo, setCodigo] = useState(codigoDePareamentoNaUrl() ?? "");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  const parear = async (valor: string) => {
    setEnviando(true);
    setErro("");
    try {
      const r = await api<{ token: string }>("/api/pareamento/concluir", { method: "POST", json: { codigo: valor, nome: nomeDoAparelho() } });
      salvarToken(r.token);
      limparCodigoDaUrl();
      useHud.setState({ semAcesso: false });
      aoParear();
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setEnviando(false);
    }
  };

  useEffect(() => {
    const doQr = codigoDePareamentoNaUrl();
    if (doQr) parear(doQr);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="min-h-full flex flex-col items-center justify-center px-6 py-10 text-center">
      <Orbe tamanho={130} />
      <h1 className="mt-4 numeral text-4xl font-[300] text-gelo">Parear com o PC</h1>
      <p className="mt-3 text-[15px] text-gelo/80 leading-relaxed max-w-[320px]">
        No HUD do computador, abra Ajustes e toque em "Parear um celular". Leia o QR code ou digite o código de 6 números.
      </p>
      <form
        className="mt-8 flex flex-col items-center gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          parear(codigo);
        }}
      >
        <label htmlFor="codigo" className="sr-only">
          Código de pareamento
        </label>
        <input
          id="codigo"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          placeholder="000000"
          value={codigo}
          onChange={(e) => setCodigo(e.target.value.replace(/\D/g, ""))}
          className="w-56 bg-transparent border-b border-aco/60 text-center numeral text-5xl tracking-[0.3em] text-gelo placeholder:text-aco/30 outline-none focus:border-[var(--luz)]"
        />
        {erro && <p className="text-sm text-coral max-w-[300px]">{erro}</p>}
        <button
          type="submit"
          disabled={codigo.length !== 6 || enviando}
          className="px-8 py-3 rounded-full border border-[var(--luz)] text-[var(--luz)] text-lg disabled:opacity-40"
        >
          {enviando ? "Pareando…" : "Parear"}
        </button>
      </form>
    </div>
  );
}

function BotaoFalar({ aoResposta }: { aoResposta: (r: { transcricao?: string; texto: string; audio?: string }) => void }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const [gravando, setGravando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const gravador = useRef<MediaRecorder | null>(null);
  const pedacos = useRef<Blob[]>([]);
  const seguro = window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;

  const comecar = async () => {
    desbloquearAudio();
    if (!seguro) {
      avisar("Para falar pelo celular, abra a Sexta pelo endereço https do QR code. Ou use o microfone do teclado no campo de texto.", "erro");
      return;
    }
    try {
      const fluxo = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const tipo = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"].find((t) => MediaRecorder.isTypeSupported?.(t));
      const g = new MediaRecorder(fluxo, tipo ? { mimeType: tipo } : undefined);
      pedacos.current = [];
      g.ondataavailable = (e) => e.data.size && pedacos.current.push(e.data);
      g.onstop = async () => {
        fluxo.getTracks().forEach((t) => t.stop());
        const blob = new Blob(pedacos.current, { type: g.mimeType || "audio/webm" });
        if (blob.size < 2000) return;
        setEnviando(true);
        try {
          const corpo = new FormData();
          corpo.append("audio", blob, `fala.${(g.mimeType || "webm").includes("mp4") ? "m4a" : "webm"}`);
          const r = await api<{ transcricao?: string; texto: string; audio?: string }>("/api/voz?resposta_em_audio=true", { method: "POST", body: corpo });
          aoResposta(r);
        } catch (e: any) {
          avisar(e.message, "erro");
        } finally {
          setEnviando(false);
        }
      };
      gravador.current = g;
      g.start();
      setGravando(true);
      navigator.vibrate?.(15);
    } catch {
      avisar("Não consegui usar o microfone. Permita o acesso nas configurações do navegador.", "erro");
    }
  };

  const parar = () => {
    if (gravador.current?.state === "recording") gravador.current.stop();
    setGravando(false);
  };

  return (
    <button
      type="button"
      aria-label={gravando ? "Solte para enviar" : "Segure para falar"}
      onPointerDown={(e) => {
        e.preventDefault();
        comecar();
      }}
      onPointerUp={parar}
      onPointerLeave={parar}
      onContextMenu={(e) => e.preventDefault()}
      disabled={enviando}
      className={`grid place-items-center size-16 shrink-0 rounded-full border-2 transition-all select-none touch-none ${
        gravando ? "border-[var(--luz)] bg-[rgb(var(--luz-rgb)/0.3)] scale-110" : "border-[var(--luz)]/70 text-[var(--luz)]"
      } ${enviando ? "opacity-50 pulsando" : ""}`}
    >
      <Icone.Microfone tamanho={26} />
    </button>
  );
}

function PainelMovel({ holo }: { holo: Holograma }) {
  const conteudo = (() => {
    switch (holo.tipo) {
      case "clima":
        return <Clima dados={holo.dados} />;
      case "noticias":
        return <Noticias dados={holo.dados} />;
      case "sistema":
        return <Sistema dados={holo.dados} />;
      case "lembretes":
        return <Lembretes />;
      case "rotinas":
        return <Rotinas />;
      case "atividades":
        return <Atividades dados={holo.dados} />;
      case "protocolo":
        return <Protocolo dados={holo.dados} />;
      case "jornal":
        return <Jornal dados={holo.dados} largura={320} />;
      case "texto":
        return <p className="whitespace-pre-wrap text-gelo">{holo.dados?.texto}</p>;
      case "imagem":
        return <img src={comToken(holo.dados.url)} alt={holo.dados.legenda ?? "Imagem"} className="w-full" />;
      default:
        return <p className="text-sm text-aco">Este painel aparece no HUD do computador.</p>;
    }
  })();
  return (
    <section className="holo-corpo px-4 py-3 overflow-hidden">
      <header className="flex items-center gap-2 mb-2">
        <GlifoTipo tipo={holo.tipo} tamanho={16} className="text-[var(--luz)]" />
        <h3 className="text-sm text-gelo/85 flex-1 truncate">{holo.titulo}</h3>
        <button type="button" aria-label="Fechar" className="p-1 text-aco" onClick={() => api(`/api/hologramas/${holo.id}`, { method: "DELETE" }).catch(() => {})}>
          <Icone.Fechar tamanho={15} />
        </button>
      </header>
      <div style={{ zoom: 0.84 }} className="max-w-full overflow-x-auto">
        {conteudo}
      </div>
    </section>
  );
}

export default function Celular() {
  const semAcesso = useHud((s) => s.semAcesso);
  const conectado = useHud((s) => s.conectado);
  const estado = useHud((s) => s.estado);
  const conversa = useHud((s) => s.conversa);
  const bloqueio = useHud((s) => s.bloqueio);
  const rotinas = useHud((s) => s.rotinas);
  const hologramas = useHud((s) => s.hologramas);
  const microfonePc = useHud((s) => s.microfone);
  const temPin = useHud((s) => s.pin);
  const avisos = useHud((s) => s.avisos);
  const avisar = useHud((s) => s.acoes.avisar);
  const [texto, setTexto] = useState("");
  const [vozAqui, setVozAqui] = useState(true);
  const [aba, setAba] = useState<"conversa" | "paineis">("conversa");
  const [pin, setPin] = useState("");
  const fim = useRef<HTMLDivElement>(null);
  const [, setPareamentos] = useState(0);
  const precisaParear = !token() || semAcesso || !!codigoDePareamentoNaUrl();

  useEffect(() => {
    if (!precisaParear) conexao.conectar();
  }, [precisaParear]);

  useEffect(() => {
    fim.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [conversa.length, conversa[conversa.length - 1]?.texto]);

  if (precisaParear) return <Pareamento aoParear={() => setPareamentos((n) => n + 1)} />;

  const enviar = async (mensagem: string) => {
    if (!mensagem.trim()) return;
    desbloquearAudio();
    setTexto("");
    try {
      const r = await api<{ texto: string; audio?: string }>("/api/conversa", { method: "POST", json: { texto: mensagem, audio: vozAqui } });
      if (vozAqui && r.audio) tocar(r.audio);
    } catch (e: any) {
      avisar(e instanceof ErroApi ? e.message : "Sem conexão com o PC.", "erro");
    }
  };

  const acoes: { rotulo: string; fazer: () => void }[] = [
    { rotulo: "Clima", fazer: () => enviar("Como está o tempo hoje?") },
    { rotulo: "Notícias", fazer: () => enviar("Quais as principais notícias?") },
    { rotulo: "Meus lembretes", fazer: () => enviar("Quais são meus lembretes?") },
    ...rotinas.map((r) => ({
      rotulo: r.nome.charAt(0).toUpperCase() + r.nome.slice(1),
      fazer: () => api(`/api/rotinas/${encodeURIComponent(r.nome)}/executar`, { method: "POST" }).catch((e) => avisar(e.message, "erro")),
    })),
    { rotulo: "Print do PC", fazer: () => enviar("Tira um print da tela") },
    { rotulo: "Bloquear o PC", fazer: () => enviar("Bloqueia o computador") },
    {
      rotulo: microfonePc ? "Silenciar microfone do PC" : "Ligar microfone do PC",
      fazer: () => api("/api/microfone", { method: "POST", json: { ligado: !microfonePc } }).catch(() => {}),
    },
  ];

  return (
    <main className="h-full flex flex-col" style={{ paddingTop: "env(safe-area-inset-top)", paddingBottom: "env(safe-area-inset-bottom)" }}>
      <header className="flex items-center justify-between px-5 pt-4">
        <h1 className="numeral text-2xl font-[300] text-gelo">Sexta-Feira</h1>
        <span className={`text-xs ${conectado ? "text-aco" : "text-coral"}`}>{conectado ? "Conectada ao PC" : "Reconectando…"}</span>
      </header>

      <div className="flex flex-col items-center pt-2">
        <Orbe tamanho={128} />
        <p className="numeral text-lg font-[300] text-[var(--luz)] -mt-1">{bloqueio.bloqueada ? "Bloqueada" : PALAVRA[estado]}</p>
      </div>

      {bloqueio.bloqueada && temPin && (
        <form
          className="mx-5 mt-2 flex items-center gap-3 holo-corpo px-4 py-2"
          onSubmit={(e) => {
            e.preventDefault();
            api("/api/desbloquear", { method: "POST", json: { metodo: "pin", pin } })
              .then(() => setPin(""))
              .catch((erro) => avisar(erro.message, "erro"));
          }}
        >
          <label htmlFor="pin-celular" className="text-sm text-aco">
            PIN
          </label>
          <input id="pin-celular" type="password" inputMode="numeric" value={pin} onChange={(e) => setPin(e.target.value)} className="flex-1 bg-transparent text-gelo numeral text-xl tracking-[0.3em] outline-none" />
          <button type="submit" className="text-sm text-[var(--luz)]">
            Desbloquear Sexta
          </button>
        </form>
      )}

      <nav className="mt-3 flex gap-5 px-5 text-sm" aria-label="Seções">
        {(["conversa", "paineis"] as const).map((a) => (
          <button key={a} type="button" aria-pressed={aba === a} onClick={() => setAba(a)} className={aba === a ? "text-gelo border-b border-[var(--luz)] pb-1" : "text-aco pb-1"}>
            {a === "conversa" ? "Conversa" : `Painéis${hologramas.length ? ` (${hologramas.length})` : ""}`}
          </button>
        ))}
      </nav>

      <section className="flex-1 overflow-y-auto rolagem px-5 py-3" aria-live="polite">
        {aba === "conversa" ? (
          conversa.length ? (
            <ol className="space-y-3">
              {conversa.map((l) => (
                <li key={`${l.papel}-${l.id}`} className={l.papel === "usuario" ? "text-right" : ""}>
                  <p
                    className={`inline-block max-w-[88%] text-left text-[15px] leading-snug ${
                      l.papel === "usuario" ? "text-aco" : "text-gelo border-l-2 border-[var(--luz)]/70 pl-3"
                    }`}
                  >
                    {l.texto}
                  </p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-sm text-aco leading-relaxed">Segure o botão para falar ou escreva um pedido. A resposta chega aqui e, se quiser, em voz.</p>
          )
        ) : hologramas.length ? (
          <div className="space-y-3">
            {hologramas.map((h) => (
              <PainelMovel key={h.id} holo={h} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-aco">Nenhum painel aberto. Peça o clima ou as notícias e eles aparecem aqui e no PC.</p>
        )}
        <div ref={fim} />
      </section>

      <div className="flex gap-2 overflow-x-auto px-5 pb-3 rolagem" aria-label="Atalhos">
        {acoes.map((a) => (
          <button key={a.rotulo} type="button" onClick={a.fazer} className="shrink-0 px-3.5 py-1.5 rounded-full border border-aco/40 text-sm text-gelo/90 active:border-[var(--luz)]">
            {a.rotulo}
          </button>
        ))}
      </div>

      <form
        className="flex items-center gap-3 px-5 pb-4"
        onSubmit={(e) => {
          e.preventDefault();
          enviar(texto);
        }}
      >
        <div className="flex-1 holo-corpo flex items-center px-3 py-2.5">
          <label htmlFor="mensagem" className="sr-only">
            Mensagem
          </label>
          <input
            id="mensagem"
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            placeholder="Escreva um pedido"
            enterKeyHint="send"
            className="flex-1 min-w-0 bg-transparent text-[16px] text-gelo placeholder:text-aco/70 outline-none"
          />
          <button type="button" aria-pressed={vozAqui} title="Resposta em voz no celular" onClick={() => setVozAqui(!vozAqui)} className={`ml-2 text-xs ${vozAqui ? "text-[var(--luz)]" : "text-aco"}`}>
            {vozAqui ? "Voz ligada" : "Só texto"}
          </button>
        </div>
        <BotaoFalar aoResposta={(r) => vozAqui && r.audio && tocar(r.audio)} />
      </form>

      <div className="fixed top-3 inset-x-3 flex flex-col gap-2 z-50" role="status">
        {avisos.map((a) => (
          <p key={a.id} className={`holo-corpo surgir px-4 py-2.5 text-sm ${a.nivel === "erro" ? "text-coral" : "text-gelo"}`}>
            {a.texto}
          </p>
        ))}
      </div>
    </main>
  );
}
