// Tipos da extensão "traje" (espelham sexta/extensoes/traje.py).
export type Nivel = "ok" | "aviso" | "falha";

export interface ItemInicializacao {
  id: string;
  modulo: string;
  ok: boolean;
  nivel: Nivel;
  detalhe: string;
}

export interface EventoInicializacao {
  fase: "checando" | "fim";
  indice: number;
  total: number;
  modulo: string;
  ok: boolean;
  detalhe: string;
  itens: ItemInicializacao[];
  falhas?: string[];
}

export interface Disco {
  unidade: string;
  pct: number;
  livre_gb: number;
  total_gb: number;
  sistema: boolean;
}

export interface SaudeDisco {
  nome: string;
  tipo: string;
  saude: string;
  ok: boolean;
  tamanho_gb: number | null;
}

export interface Seguranca {
  defender: string;
  firewall: string;
  ultima_revisao: string | null;
  risco: string | null;
  nivel: Nivel;
  dica: string;
}

export interface RelatorioTraje {
  carregando?: boolean;
  quando: string;
  nivel: Nivel;
  atencao: { texto: string; nivel: Nivel }[];
  cpu: { temp: number | null; uso: number | null; fonte: string; erro: string; limite: number };
  gpu: { nome: string | null; temp: number | null; uso: number | null; vram_usada: number | null; vram_total: number | null; fonte: string | null; erro: string; limite: number };
  ram: { pct: number | null; usada: number | null; total: number | null };
  discos: Disco[];
  saude_discos: SaudeDisco[];
  saude_erro: string;
  rede: { ping_ms: number | null; ssid: string | null; erro: string };
  atualizacoes: { windows: number | null; winget: number | null; verificado: string | null; verificando: boolean; erro: string };
  bateria: { presente: boolean | null; saude_pct?: number; projetada_mwh?: number; atual_mwh?: number; verificando?: boolean; erro?: string };
  seguranca: Seguranca | null;
}

export interface MetricasOverlay {
  jogo: string;
  fps: number | null;
  fps_dica: string;
  cpu: number | null;
  ram: number | null;
  cpu_temp: number | null;
  gpu: number | null;
  gpu_temp: number | null;
  ping: number | null;
}
