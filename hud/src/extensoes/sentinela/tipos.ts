// Dados dos hologramas "sentinela" e "retomar" (ver sexta/extensoes/sentinela.py).

export interface FotoSentinela {
  nome: string;
  quando: string;
  tamanho: number;
}

export interface DadosSentinela {
  armado: boolean;
  desde: string | null;
  motivo: string;
  alertas: number;
  auto: boolean;
  minutos: number;
  cadastrado: boolean;
  windows: boolean;
  fotos: FotoSentinela[];
}

export interface AppSessao {
  exe: string;
  caminho: string;
  titulo: string;
  janelas: number;
}

export interface ArquivoSessao {
  nome: string;
  caminho: string;
}

export interface AbaSessao {
  url: string;
  titulo: string;
}

export interface Sessao {
  id: string;
  inicio: string;
  fim: string;
  apps: AppSessao[];
  arquivos: ArquivoSessao[];
  abas: AbaSessao[];
}

export interface DadosRetomar {
  sessao: Sessao | null;
  resumo?: string;
}

export function horaCurta(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const hoje = new Date();
  const hora = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === hoje.toDateString() ? `hoje, ${hora}` : `${d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} ${hora}`;
}
