// Dados dos vídeos (espelham sexta/extensoes/video.py).
import { create } from "zustand";

export interface Trabalho {
  id: number;
  tipo: string;
  rotulo: string;
  estado: "fila" | "rodando" | "ok" | "erro" | "cancelado";
  etapa: string;
  progresso: number;
  erro: string;
  criado: number;
  saidas: string[];
}

export interface Gerado {
  id: number;
  nome: string;
  caminho: string;
  tipo: "video" | "audio" | "gif" | "legenda";
  origem: string;
  criado: number;
  tamanho: string;
  existe: boolean;
}

export interface DadosVideos {
  trabalhos: Trabalho[];
  gerados: Gerado[];
  pasta: string;
}

/** Progresso ao vivo (evento "video.trabalhos"): chega mais rápido que a atualização do holograma. */
export const useTrabalhos = create<{ trabalhos: Trabalho[] | null; ts: number }>()(() => ({ trabalhos: null, ts: 0 }));

export function aoTrabalhos(evento: { trabalhos: Trabalho[] }) {
  useTrabalhos.setState({ trabalhos: evento.trabalhos ?? [], ts: Date.now() });
}
