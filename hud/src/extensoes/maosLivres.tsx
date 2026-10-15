// Extensão "maosLivres": o celular escuta "Sexta-Feira" sozinho (mãos livres) e mostra o print do PC na conversa.
// O microfone vira PCM 16 kHz mono int16 num AudioWorklet (ou ScriptProcessor) e vai em quadros de ~100 ms
// pelo WebSocket de sempre; a detecção da palavra, a gravação e a resposta acontecem no PC
// (sexta/extensoes/maos_livres.py), e a resposta volta só para este celular, com áudio.
import { create } from "zustand";
import { comToken } from "../lib/api";
import { conexao } from "../lib/socket";
import { useHud } from "../lib/store";
import type { Extensao } from "./tipos";

export type EstadoMaosLivres = "desligado" | "ligando" | "ouvindo" | "gravando" | "pensando" | "falando";

interface Imagem {
  url: string;
  legenda?: string;
}

interface StoreMaosLivres {
  ligado: boolean;
  estado: EstadoMaosLivres;
  nivel: number;
  ultima: string;
  imagens: Record<number, Imagem>;
  pendente: (Imagem & { ts: number }) | null;
}

export const useMaosLivres = create<StoreMaosLivres>(() => ({
  ligado: false,
  estado: "desligado",
  nivel: 0,
  ultima: "",
  imagens: {},
  pendente: null,
}));

export const ROTULO_ESTADO: Record<EstadoMaosLivres, string> = {
  desligado: "Mãos livres desligado",
  ligando: "Ligando o microfone…",
  ouvindo: "Ouvindo — diga “Sexta-Feira”",
  gravando: "Gravando seu pedido…",
  pensando: "Pensando…",
  falando: "Falando…",
};

// ------------------------------------------------------------------ captura (PCM 16 kHz)
const TAXA = 16000;
const AMOSTRAS_QUADRO = 1600; // 100 ms

// Reamostrador por média de caixa (taxa qualquer -> 16 kHz), usado no worklet e no fallback.
const CODIGO_REAMOSTRADOR = `
class Reamostrador {
  constructor(de, para, quadro) {
    this.passo = de / para; this.limite = this.passo; this.n = 0; this.soma = 0; this.cont = 0;
    this.quadro = quadro; this.saida = new Int16Array(quadro); this.i = 0; this.energia = 0;
  }
  processar(entrada, enviar) {
    for (let k = 0; k < entrada.length; k++) {
      this.soma += entrada[k]; this.cont++; this.n++;
      if (this.n >= this.limite) {
        this.limite += this.passo;
        const v = Math.max(-1, Math.min(1, this.soma / this.cont));
        this.soma = 0; this.cont = 0;
        this.energia += v * v;
        this.saida[this.i++] = v < 0 ? v * 32768 : v * 32767;
        if (this.i === this.quadro) {
          const nivel = Math.sqrt(this.energia / this.quadro);
          enviar(this.saida.buffer, nivel);
          this.saida = new Int16Array(this.quadro); this.i = 0; this.energia = 0;
        }
      }
    }
    if (this.n > 1e9) { this.n -= 1e9; this.limite -= 1e9; }
  }
}`;

const CODIGO_WORKLET = `${CODIGO_REAMOSTRADOR}
class CapturaSexta extends AudioWorkletProcessor {
  constructor() {
    super();
    this.r = new Reamostrador(sampleRate, ${TAXA}, ${AMOSTRAS_QUADRO});
  }
  process(entradas) {
    const canal = entradas[0] && entradas[0][0];
    if (canal) this.r.processar(canal, (buffer, nivel) => this.port.postMessage({ buffer, nivel }, [buffer]));
    return true;
  }
}
registerProcessor("captura-sexta", CapturaSexta);`;

interface Captura {
  parar: () => void;
}

async function iniciarCaptura(aoQuadro: (buffer: ArrayBuffer, nivel: number) => void): Promise<Captura> {
  const fluxo = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
  const Contexto: typeof AudioContext = (window as any).AudioContext ?? (window as any).webkitAudioContext;
  const ctx = new Contexto();
  if (ctx.state === "suspended") await ctx.resume().catch(() => {});
  const fonte = ctx.createMediaStreamSource(fluxo);
  let no: AudioNode;
  let url = "";
  try {
    if (!ctx.audioWorklet) throw new Error("sem AudioWorklet");
    url = URL.createObjectURL(new Blob([CODIGO_WORKLET], { type: "application/javascript" }));
    await ctx.audioWorklet.addModule(url);
    const worklet = new AudioWorkletNode(ctx, "captura-sexta", { numberOfInputs: 1, numberOfOutputs: 0, channelCount: 1 });
    worklet.port.onmessage = (m) => aoQuadro(m.data.buffer, m.data.nivel);
    fonte.connect(worklet);
    no = worklet;
  } catch {
    // navegador antigo: ScriptProcessorNode na thread principal
    const Reamostrador = new Function(`${CODIGO_REAMOSTRADOR}; return Reamostrador;`)();
    const r = new Reamostrador(ctx.sampleRate, TAXA, AMOSTRAS_QUADRO);
    const processador = ctx.createScriptProcessor(4096, 1, 1);
    processador.onaudioprocess = (e) => r.processar(e.inputBuffer.getChannelData(0), aoQuadro);
    const mudo = ctx.createGain();
    mudo.gain.value = 0;
    fonte.connect(processador);
    processador.connect(mudo);
    mudo.connect(ctx.destination);
    no = processador;
  }
  return {
    parar: () => {
      try {
        fonte.disconnect();
        no.disconnect();
      } catch {
        /* já desligado */
      }
      fluxo.getTracks().forEach((t) => t.stop());
      ctx.close().catch(() => {});
      if (url) URL.revokeObjectURL(url);
    },
  };
}

// ------------------------------------------------------------------ reprodução e bipe
const tocador = typeof Audio !== "undefined" ? new Audio() : null;
let ctxBipe: AudioContext | null = null;
let tocandoLocal = false;

function avisarTocando(tocando: boolean) {
  if (tocando && tocandoLocal) return; // "parou" sempre vai: o PC não pode ficar esperando
  tocandoLocal = tocando;
  conexao.enviar({ tipo: "maos_livres.tocando", tocando });
  if (useMaosLivres.getState().ligado) {
    const estado = useMaosLivres.getState().estado;
    if (tocando) useMaosLivres.setState({ estado: "falando" });
    else if (estado === "falando") useMaosLivres.setState({ estado: "ouvindo" });
  }
}

if (tocador) {
  tocador.onplaying = () => avisarTocando(true);
  tocador.onended = () => avisarTocando(false);
  tocador.onpause = () => avisarTocando(false);
  tocador.onerror = () => avisarTocando(false);
}

function pararReproducao() {
  tocador?.pause();
  try {
    window.speechSynthesis?.cancel();
  } catch {
    /* sem síntese */
  }
  avisarTocando(false);
}

function falarResposta(texto: string, audio?: string | null) {
  if (!texto && !audio) return;
  pararReproducao();
  if (audio && tocador) {
    tocador.src = comToken(audio);
    tocador.play().catch(() => avisarTocando(false));
    return;
  }
  // sem áudio do PC (voz do Windows): usa a voz do próprio celular
  const sintese = window.speechSynthesis;
  if (!sintese || !texto) {
    avisarTocando(false);
    return;
  }
  const fala = new SpeechSynthesisUtterance(texto.slice(0, 600));
  fala.lang = "pt-BR";
  fala.onstart = () => avisarTocando(true);
  fala.onend = () => avisarTocando(false);
  fala.onerror = () => avisarTocando(false);
  sintese.speak(fala);
}

function bipe() {
  try {
    navigator.vibrate?.(30);
    const Contexto: typeof AudioContext = (window as any).AudioContext ?? (window as any).webkitAudioContext;
    ctxBipe ??= new Contexto();
    const ctx = ctxBipe;
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    const agora = ctx.currentTime;
    [880, 1320].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const ganho = ctx.createGain();
      osc.frequency.value = freq;
      ganho.gain.setValueAtTime(0.0001, agora + i * 0.09);
      ganho.gain.exponentialRampToValueAtTime(0.25, agora + i * 0.09 + 0.02);
      ganho.gain.exponentialRampToValueAtTime(0.0001, agora + i * 0.09 + 0.08);
      osc.connect(ganho).connect(ctx.destination);
      osc.start(agora + i * 0.09);
      osc.stop(agora + i * 0.09 + 0.1);
    });
  } catch {
    /* sem Web Audio */
  }
}

function desbloquearReproducao() {
  // iPhone: o áudio só toca depois de um toque; aproveita o toque no botão
  if (tocador && !tocador.src) {
    tocador.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";
    tocador.play().catch(() => {});
  }
  try {
    const Contexto: typeof AudioContext = (window as any).AudioContext ?? (window as any).webkitAudioContext;
    ctxBipe ??= new Contexto();
    ctxBipe.resume().catch(() => {});
  } catch {
    /* sem Web Audio */
  }
}

// ------------------------------------------------------------------ liga/desliga
let captura: Captura | null = null;
let travaTela: any = null;
let temporizadorOculto = 0;
let ultimoNivel = 0;
const OCULTO_DESLIGA_MS = 60_000;

async function pedirTravaTela() {
  try {
    const wl = (navigator as any).wakeLock;
    if (!wl || document.visibilityState !== "visible") return;
    travaTela = await wl.request("screen");
    travaTela.addEventListener?.("release", () => (travaTela = null));
  } catch {
    travaTela = null; // modo de economia de bateria ou navegador sem suporte
  }
}

function aoMudarVisibilidade() {
  if (!useMaosLivres.getState().ligado) return;
  if (document.visibilityState === "visible") {
    window.clearTimeout(temporizadorOculto);
    temporizadorOculto = 0;
    if (!travaTela) pedirTravaTela();
  } else if (!temporizadorOculto) {
    temporizadorOculto = window.setTimeout(() => {
      desligarMaosLivres();
      useHud.getState().acoes.avisar("Mãos livres desligado: a página ficou em segundo plano.", "info");
    }, OCULTO_DESLIGA_MS);
  }
}

function aoQuadro(buffer: ArrayBuffer, nivel: number) {
  conexao.enviarBinario(buffer);
  const agora = performance.now();
  if (agora - ultimoNivel > 90) {
    ultimoNivel = agora;
    useMaosLivres.setState({ nivel: Math.min(1, nivel * 6) });
  }
}

export async function ligarMaosLivres(): Promise<void> {
  const avisar = useHud.getState().acoes.avisar;
  if (useMaosLivres.getState().ligado) return;
  desbloquearReproducao();
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    avisar("O mãos livres precisa do endereço https do QR code (o navegador só libera o microfone assim).", "erro");
    return;
  }
  useMaosLivres.setState({ ligado: true, estado: "ligando" });
  try {
    captura = await iniciarCaptura(aoQuadro);
  } catch {
    useMaosLivres.setState({ ligado: false, estado: "desligado" });
    avisar("Não consegui usar o microfone. Permita o acesso nas configurações do navegador.", "erro");
    return;
  }
  if (!useMaosLivres.getState().ligado) {
    captura.parar(); // desligou enquanto pedia permissão
    captura = null;
    return;
  }
  conexao.enviar({ tipo: "maos_livres", ligar: true });
  pedirTravaTela();
  document.addEventListener("visibilitychange", aoMudarVisibilidade);
}

export function desligarMaosLivres(): void {
  const estava = useMaosLivres.getState().ligado;
  useMaosLivres.setState({ ligado: false, estado: "desligado", nivel: 0 });
  captura?.parar();
  captura = null;
  travaTela?.release?.().catch?.(() => {});
  travaTela = null;
  window.clearTimeout(temporizadorOculto);
  temporizadorOculto = 0;
  document.removeEventListener("visibilitychange", aoMudarVisibilidade);
  if (estava) conexao.enviar({ tipo: "maos_livres", ligar: false });
}

// religa no servidor depois de uma reconexão (o PC limpa a sessão quando o WebSocket cai)
conexao.aoAbrir(() => {
  if (useMaosLivres.getState().ligado) conexao.enviar({ tipo: "maos_livres", ligar: true });
});

// ------------------------------------------------------------------ componentes
function Medidor({ nivel, ativo }: { nivel: number; ativo: boolean }) {
  const barras = 12;
  return (
    <div className="flex items-end gap-[3px] h-5" aria-hidden="true">
      {Array.from({ length: barras }, (_, i) => {
        const aceso = ativo && nivel * barras > i;
        return (
          <span
            key={i}
            className={`w-[4px] rounded-sm transition-all duration-75 ${aceso ? "bg-[var(--luz)]" : "bg-aco/25"}`}
            style={{ height: `${30 + (i / barras) * 70}%` }}
          />
        );
      })}
    </div>
  );
}

/** Botão "Mãos livres" + indicador de escuta e medidor de volume (página do celular). */
export function PainelMaosLivres({ destacar = false }: { destacar?: boolean }) {
  const ligado = useMaosLivres((s) => s.ligado);
  const estado = useMaosLivres((s) => s.estado);
  const nivel = useMaosLivres((s) => s.nivel);
  const ultima = useMaosLivres((s) => s.ultima);
  const gravando = estado === "gravando";
  return (
    <div
      className={`mx-5 mt-2 holo-corpo px-4 py-2 flex items-center gap-3 ${destacar && !ligado ? "pulsando" : ""} ${
        gravando ? "ring-1 ring-[var(--luz)]" : ""
      }`}
    >
      <button
        type="button"
        role="switch"
        aria-checked={ligado}
        onClick={() => (ligado ? desligarMaosLivres() : ligarMaosLivres())}
        className={`shrink-0 px-3 py-1.5 rounded-full border text-sm ${
          ligado ? "border-[var(--luz)] bg-[rgb(var(--luz-rgb)/0.25)] text-gelo" : "border-aco/50 text-gelo/85"
        }`}
      >
        Mãos livres {ligado ? "ligado" : "desligado"}
      </button>
      <div className="flex-1 min-w-0" role="status" aria-live="polite">
        <p className={`text-sm truncate ${ligado ? "text-[var(--luz)]" : "text-aco"}`}>
          {ligado && <span className={`inline-block size-2 rounded-full mr-2 align-middle ${gravando ? "bg-coral pulsando" : "bg-[var(--luz)]"}`} />}
          {ligado ? ROTULO_ESTADO[estado] : "Toque para eu escutar “Sexta-Feira” daqui"}
        </p>
        {ligado && ultima && <p className="text-xs text-aco truncate">{ultima}</p>}
      </div>
      <Medidor nivel={nivel} ativo={ligado} />
    </div>
  );
}

/** Imagem (print do PC) que acompanha uma resposta na conversa do celular. */
export function ImagemDaConversa({ id }: { id: number }) {
  const imagem = useMaosLivres((s) => s.imagens[id]);
  if (!imagem) return null;
  const url = comToken(imagem.url);
  return (
    <a href={url} target="_blank" rel="noreferrer" className="block mt-2 max-w-[88%]">
      <img src={url} alt={imagem.legenda ?? "Print da tela do PC"} className="w-full rounded border border-aco/30" loading="lazy" />
    </a>
  );
}

// ------------------------------------------------------------------ eventos
function guardarImagem(id: number | undefined, imagem: Imagem | null | undefined) {
  if (id == null || !imagem?.url) return;
  useMaosLivres.setState((s) => ({ imagens: { ...s.imagens, [id]: imagem }, pendente: null }));
}

function aoHolograma(e: any) {
  const h = e.holograma;
  const url = h?.dados?.url;
  if (h?.tipo === "imagem" && typeof url === "string" && url.startsWith("/api/prints/")) {
    useMaosLivres.setState({ pendente: { url, legenda: h.dados.legenda, ts: Date.now() } });
  }
}

const extensao: Extensao = {
  eventos: {
    "maos_livres.estado": (e) => {
      if (e.erro) {
        useHud.getState().acoes.avisar(e.erro, "erro");
        desligarMaosLivres();
        return;
      }
      if (!useMaosLivres.getState().ligado) return;
      if (!e.ligado) {
        // o PC desligou a sessão (ex.: Sexta reiniciou): a reconexão religa
        return;
      }
      if (e.estado === "ouvindo" && tocandoLocal) return; // ainda tocando a resposta
      useMaosLivres.setState({ estado: e.estado });
    },
    "maos_livres.ativado": () => {
      pararReproducao();
      bipe();
    },
    "maos_livres.resposta": (e) => {
      if (e.imagem) guardarImagem(e.id, e.imagem);
      useMaosLivres.setState({ ultima: e.texto ?? "" });
      if (useMaosLivres.getState().ligado) falarResposta(e.texto ?? "", e.audio);
    },
    "maos_livres.anuncio": (e) => {
      navigator.vibrate?.([80, 40, 80]);
      useMaosLivres.setState({ ultima: e.texto ?? "" });
      if (useMaosLivres.getState().ligado) falarResposta(e.texto ?? "", e.audio);
    },
    "maos_livres.parar_audio": () => pararReproducao(),
    "maos_livres.alerta": (e) => {
      try {
        navigator.vibrate?.([200, 80, 200, 80, 200]);
        if (typeof Notification !== "undefined" && Notification.permission === "granted") {
          new Notification(e.titulo ?? "Sexta-Feira", { body: e.texto, tag: "sexta-seguranca" });
        }
      } catch {
        /* sem notificações */
      }
    },
    "holograma.abrir": aoHolograma,
    "holograma.atualizar": aoHolograma,
    conversa: (e) => {
      if (e.papel !== "assistente") return;
      const pendente = useMaosLivres.getState().pendente;
      if (pendente && Date.now() - pendente.ts < 60_000 && (e.ferramentas ?? []).includes("computador")) {
        guardarImagem(e.id, pendente);
      }
    },
  },
};

export default extensao;
