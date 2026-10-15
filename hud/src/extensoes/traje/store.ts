// Estado próprio da extensão "traje": a sequência de inicialização e as métricas do overlay de jogo.
import { create } from "zustand";
import type { EventoInicializacao, MetricasOverlay } from "./tipos";

interface EstadoTraje {
  inicializacao: EventoInicializacao | null;
  overlay: MetricasOverlay | null;
  dispensar: () => void;
}

export const useTraje = create<EstadoTraje>()((set) => ({
  inicializacao: null,
  overlay: null,
  dispensar: () => set({ inicializacao: null }),
}));

export function aoInicializar(e: EventoInicializacao): void {
  useTraje.setState({ inicializacao: e });
}

export function aoMetricas(e: MetricasOverlay): void {
  useTraje.setState({ overlay: e });
}
