import { create } from "zustand";
import type { Aviso, Bloqueio, EstadoAssistente, Holograma, InfoRosto, Lembrete, LinhaConversa, Mao, Preferencias, Rotina } from "./tipos";

/** Valores que mudam muitas vezes por segundo: ficam fora do React (lidos em requestAnimationFrame). */
export const tempoReal = {
  maos: [] as Mao[],
  maosEm: 0,
  nivelFala: 0,
  nivelMic: 0,
};

export interface EstadoHud {
  conectado: boolean;
  semAcesso: boolean;
  cliente: { tipo: "pc" | "celular"; nome: string } | null;
  versao: string;
  modelo: string;
  estado: EstadoAssistente;
  microfone: boolean;
  maosLigadas: boolean;
  camera: boolean;
  avisosSistema: Record<string, string>;
  bloqueio: Bloqueio;
  prefs: Preferencias | null;
  hologramas: Holograma[];
  conversa: LinhaConversa[];
  ouvido: string;
  lembretes: Lembrete[];
  rotinas: Rotina[];
  rosto: InfoRosto | null;
  maosDisponivel: boolean;
  pin: boolean;
  verificacao: { fase: string; similaridade?: number; motivo?: string } | null;
  cadastro: { fase: string; instrucao?: string; etapa?: number; etapas?: number; progresso?: number; mensagem?: string } | null;
  alarme: { texto: string } | null;
  avisos: Aviso[];
  rotinaAtiva: { nome: string; passo: number; total: number } | null;
  ferramentaAtual: string | null;
  falaAtual: string;
  editorProtocolos: string | null; // null = fechado; "" = novo; nome = editando
  acoes: {
    avisar: (texto: string, nivel?: Aviso["nivel"]) => void;
    dispensarAviso: (id: number) => void;
    abrirEditor: (nome: string | null) => void;
  };
}

let proximoAviso = 1;

export const useHud = create<EstadoHud>()((set) => ({
  conectado: false,
  semAcesso: false,
  cliente: null,
  versao: "",
  modelo: "",
  estado: "iniciando",
  microfone: true,
  maosLigadas: false,
  camera: false,
  avisosSistema: {},
  bloqueio: { bloqueada: false, motivo: "", protecao: false },
  prefs: null,
  hologramas: [],
  conversa: [],
  ouvido: "",
  lembretes: [],
  rotinas: [],
  rosto: null,
  maosDisponivel: false,
  pin: false,
  verificacao: null,
  cadastro: null,
  alarme: null,
  avisos: [],
  rotinaAtiva: null,
  ferramentaAtual: null,
  falaAtual: "",
  editorProtocolos: null,
  acoes: {
    avisar: (texto, nivel = "info") => {
      const id = proximoAviso++;
      set((s) => ({ avisos: [...s.avisos.slice(-3), { id, texto, nivel }] }));
      window.setTimeout(() => set((s) => ({ avisos: s.avisos.filter((a) => a.id !== id) })), nivel === "erro" ? 9000 : 6000);
    },
    dispensarAviso: (id) => set((s) => ({ avisos: s.avisos.filter((a) => a.id !== id) })),
    abrirEditor: (nome) => set({ editorProtocolos: nome }),
  },
}));

const NOMES_FERRAMENTAS: Record<string, string> = {
  obter_clima: "consultando o clima",
  obter_noticias: "buscando notícias",
  abrir: "abrindo",
  fechar_programa: "fechando programa",
  pesquisar: "pesquisando",
  tocar_youtube: "procurando no YouTube",
  controlar_midia: "controlando a mídia",
  ajustar_volume: "ajustando o volume",
  computador: "no computador",
  criar_lembrete: "criando lembrete",
  gerenciar_lembretes: "vendo lembretes",
  rotina: "rotina",
  criar_protocolo: "montando protocolo",
  holograma: "projetando",
  memoria: "memória",
  assistente: "ajustando a mim mesma",
};

export function descreverFerramenta(nome: string): string {
  return NOMES_FERRAMENTAS[nome] ?? nome;
}

const manipuladoresExtras: Record<string, ((evento: any) => void)[]> = {};

/** Extensões (src/extensoes) recebem eventos do WebSocket por aqui. */
export function aoEvento(tipo: string, funcao: (evento: any) => void): void {
  (manipuladoresExtras[tipo] ??= []).push(funcao);
}

/** Aplica um evento vindo do WebSocket ao estado. */
export function aplicarEvento(e: any): void {
  try {
    for (const funcao of manipuladoresExtras[e.tipo] ?? []) funcao(e);
  } catch (erro) {
    console.error("Erro numa extensão ao tratar", e.tipo, erro);
  }
  const set = useHud.setState;
  const get = useHud.getState;
  switch (e.tipo) {
    case "ola":
      set({
        conectado: true,
        semAcesso: false,
        cliente: e.cliente,
        versao: e.versao,
        modelo: e.modelo,
        estado: e.status.estado,
        microfone: e.status.microfone,
        maosLigadas: e.status.maos,
        camera: e.status.camera,
        avisosSistema: e.status.avisos ?? {},
        bloqueio: e.bloqueio,
        prefs: e.preferencias,
        hologramas: e.hologramas,
        lembretes: e.lembretes,
        rotinas: e.rotinas,
        rosto: e.rosto,
        maosDisponivel: e.maos_disponivel,
        pin: e.pin,
        alarme: e.alarme ? { texto: "Alarme" } : null,
      });
      break;
    case "estado":
      set({ estado: e.estado, ...(e.estado === "inativa" ? { ferramentaAtual: null } : {}) });
      break;
    case "status":
      set({ estado: e.estado, microfone: e.microfone, maosLigadas: e.maos, camera: e.camera, avisosSistema: e.avisos ?? {} });
      break;
    case "bloqueio":
      set({ bloqueio: { bloqueada: e.bloqueada, motivo: e.motivo, protecao: e.protecao } });
      if (!e.bloqueada) set({ verificacao: null });
      break;
    case "preferencias":
      set({ prefs: e.preferencias });
      break;
    case "holograma.abrir":
      set((s) => ({ hologramas: [...s.hologramas.filter((h) => h.id !== e.holograma.id), e.holograma] }));
      break;
    case "holograma.atualizar":
      set((s) => ({ hologramas: s.hologramas.map((h) => (h.id === e.holograma.id ? e.holograma : h)) }));
      break;
    case "holograma.fechar":
      set((s) => ({ hologramas: s.hologramas.filter((h) => h.id !== e.id) }));
      break;
    case "conversa": {
      const linha = {
        id: e.id,
        papel: e.papel,
        texto: e.texto ?? "",
        canal: e.canal,
        ferramentas: e.ferramentas,
        parcial: false,
        ts: Date.now(),
      };
      set((s) => {
        const resto = s.conversa.filter((l) => !(l.id === e.id && l.papel === e.papel));
        return { conversa: [...resto, linha].slice(-60), ...(e.papel === "assistente" ? { ferramentaAtual: null } : { ouvido: "" }) };
      });
      break;
    }
    case "resposta.parcial":
      set((s) => {
        const atual = s.conversa.find((l) => l.id === e.id && l.papel === "assistente");
        if (atual) {
          return { conversa: s.conversa.map((l) => (l === atual ? { ...l, texto: l.texto + e.texto, parcial: true } : l)) };
        }
        return {
          conversa: [...s.conversa, { id: e.id, papel: "assistente" as const, texto: e.texto, parcial: true, ts: Date.now() }].slice(-60),
        };
      });
      break;
    case "transcricao":
      set({ ouvido: e.texto ?? "" });
      break;
    case "ferramenta":
      set({ ferramentaAtual: descreverFerramenta(e.nome) });
      break;
    case "lembretes":
      set({ lembretes: e.itens });
      break;
    case "lembrete":
      if (e.alarme) set({ alarme: { texto: e.texto } });
      else get().acoes.avisar(e.perdido ? `Lembrete perdido: ${e.texto}` : e.texto, "lembrete");
      break;
    case "alarme.fim":
      set({ alarme: null });
      break;
    case "verificacao":
      set({ verificacao: { fase: e.fase, similaridade: e.similaridade, motivo: e.motivo } });
      if (e.fase === "ok") window.setTimeout(() => set({ verificacao: null }), 1500);
      break;
    case "cadastro":
      set({ cadastro: e });
      break;
    case "maos":
      tempoReal.maos = e.maos ?? [];
      tempoReal.maosEm = performance.now();
      break;
    case "maos.modo":
      set({ maosLigadas: e.ligado });
      break;
    case "fala.nivel":
      tempoReal.nivelFala = e.nivel ?? 0;
      break;
    case "mic.nivel":
      tempoReal.nivelMic = e.nivel ?? 0;
      break;
    case "fala.inicio":
      set({ falaAtual: e.texto ?? "" });
      break;
    case "aviso":
      get().acoes.avisar(e.texto, e.nivel === "erro" ? "erro" : "info");
      break;
    case "pareado":
      get().acoes.avisar(`Celular ${e.nome} pareado.`, "sucesso");
      break;
    case "rotina":
      set({ rotinaAtiva: e.concluida ? null : { nome: e.nome, passo: e.passo, total: e.total } });
      break;
    case "acesso":
      set({ pin: !!e.pin });
      break;
    case "rotinas":
      set({ rotinas: e.rotinas });
      break;
    case "protocolo.disparado":
      get().acoes.avisar(`Protocolo ${e.nome}: ${e.gatilho}`, "info");
      break;
    case "notificacao":
      get().acoes.avisar(e.texto, "lembrete");
      try {
        navigator.vibrate?.([120, 60, 120]);
        if (typeof Notification !== "undefined" && Notification.permission === "granted") new Notification(e.titulo ?? "Sexta-Feira", { body: e.texto });
      } catch {
        /* sem suporte a notificações */
      }
      break;
    default:
      break;
  }
}
