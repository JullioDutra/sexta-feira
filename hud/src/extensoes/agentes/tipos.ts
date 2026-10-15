// Dados dos agentes (espelham sexta/extensoes/agentes.py) e o store que recebe o evento "agentes" do WebSocket.
import { create } from "zustand";
import { api } from "../../lib/api";

export type StatusAgente = "rodando" | "aguardando" | "conferindo" | "concluido" | "parcial" | "falhou" | "cancelado" | "interrompido";

export interface Passo {
  n: number;
  tipo: string; // inicio, pensamento, ferramenta, resultado, claude, aguardando, aprovado, recusado, aviso, conferencia, fim
  texto: string;
  ok: boolean | null;
  ts: number;
  ferramenta?: string;
}

export interface Agente {
  id: string;
  numero: number;
  tipo: string;
  rotulo: string;
  objetivo: string;
  status: StatusAgente;
  origem: string;
  criado: number;
  terminado: number | null;
  rodada: number;
  max_passos: number;
  max_segundos: number;
  passos: Passo[];
  relatorio: string;
  evidencia: string;
  resumo: string;
  pendente: { ferramenta: string; descricao: string; nivel: number } | null;
}

export interface TipoAgente {
  tipo: string;
  rotulo: string;
  descricao: string;
  confirmar: boolean;
}

export interface DadosAgentes {
  agentes: Agente[];
  tipos: TipoAgente[];
}

export const ATIVOS: StatusAgente[] = ["rodando", "aguardando", "conferindo"];

export const ROTULO_STATUS: Record<StatusAgente, string> = {
  rodando: "trabalhando",
  aguardando: "aguardando aprovação",
  conferindo: "conferindo",
  concluido: "concluído",
  parcial: "parcial",
  falhou: "falhou",
  cancelado: "cancelado",
  interrompido: "interrompido",
};

export const SIMBOLO_STATUS: Partial<Record<StatusAgente, string>> = { concluido: "✓", parcial: "≈", falhou: "✗" };

interface EstadoAgentes {
  dados: DadosAgentes | null;
  definir: (dados: DadosAgentes) => void;
  carregar: () => Promise<void>;
}

export const useAgentes = create<EstadoAgentes>()((set) => ({
  dados: null,
  definir: (dados) => set({ dados: { agentes: dados.agentes ?? [], tipos: dados.tipos ?? [] } }),
  carregar: () =>
    api<DadosAgentes>("/api/agentes")
      .then((d) => set({ dados: d }))
      .catch(() => undefined),
}));

export function cancelarAgente(id: string) {
  return api<{ texto: string }>(`/api/agentes/${id}/cancelar`, { method: "POST" });
}

export function aprovarAgente(id: string, aprovar: boolean) {
  return api<{ texto: string }>(`/api/agentes/${id}/aprovar`, { method: "POST", json: { aprovar } });
}

export function criarAgente(tipo: string, objetivo: string) {
  return api<{ ok: boolean; texto: string; pendente: boolean }>("/api/agentes", { method: "POST", json: { tipo, objetivo } });
}

export function duracao(segundos: number): string {
  const s = Math.max(0, Math.round(segundos));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}min` : `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}`;
}
