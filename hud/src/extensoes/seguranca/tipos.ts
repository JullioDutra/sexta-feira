// Tipos do holograma "Segurança" (espelham sexta/extensoes/seguranca).
export type Risco = "alto" | "medio" | "baixo" | "ok";

export interface Motivo {
  id: string;
  texto: string;
  peso: number;
  evidencias: string[];
  tecnica: string;
}

export interface Secao {
  nome: string;
  tamanho_bruto: number;
  tamanho_virtual: number;
  entropia: number;
  executavel: boolean;
  gravavel: boolean;
}

export interface VirusTotal {
  conhecido: boolean;
  maliciosos?: number;
  suspeitos?: number;
  total?: number;
  rotulo?: string;
}

export interface AnaliseArquivo {
  tipo: "arquivo";
  id: string;
  arquivo: string;
  caminho: string;
  tamanho: number;
  sha256: string;
  descricao: string;
  categoria: string;
  risco: Exclude<Risco, "ok">;
  veredito: string;
  motivos: Motivo[];
  assinatura: { status: string; texto: string; assinante?: string; emissor?: string; validade?: string };
  capacidades: Record<string, string[]>;
  capacidades_rotulos: Record<string, string>;
  strings: { urls: string[]; ips: string[]; caminhos: string[]; registro: string[] };
  detalhes: {
    pe?: { arquitetura: string; tipo: string; subsistema: string; compilado_em: string | null; secoes: Secao[]; dotnet: boolean; compactadores: string[]; dlls: string[]; total_funcoes: number; sobra_bytes: number };
    asar?: { arquivos?: number; nome?: string; versao?: string; principal?: string; preload?: string[]; modulos_nativos?: string[]; dependencias?: string[]; caminho?: string; erro?: string };
    zip?: { entradas?: number; amostra?: string[] };
    linhas?: number;
  };
  limites: string[];
  sugestoes: string[];
  quando: string;
  virustotal?: VirusTotal;
}

export interface ItemPc {
  id: string;
  categoria: string;
  titulo: string;
  risco: Risco;
  detalhe: string;
  evidencias: string[];
  sugestao: string;
  acao: ({ acao: string } & Record<string, string>) | null;
}

export interface RevisaoPc {
  tipo: "pc";
  id?: string;
  risco: Exclude<Risco, "ok">;
  itens: ItemPc[];
  contagem: Record<Risco, number>;
  veredito: string;
  erros: string[];
  quando: string;
}

export interface Carregando {
  tipo: "carregando";
  texto: string;
}

export interface ResumoHistorico {
  id: string;
  tipo: "arquivo" | "pc";
  quando: string;
  risco: Risco;
  titulo: string;
  assinatura?: string | null;
  virustotal?: VirusTotal | null;
}

export interface DadosSeguranca {
  atual: AnaliseArquivo | RevisaoPc | Carregando | null;
  historico: ResumoHistorico[];
  virustotal: boolean;
}

export const ROTULO_RISCO: Record<Risco, string> = { alto: "Alto risco", medio: "Risco médio", baixo: "Baixo risco", ok: "OK" };
export const COR_RISCO: Record<Risco, string> = { alto: "text-coral", medio: "text-ambar", baixo: "text-menta", ok: "text-aco" };
export const BORDA_RISCO: Record<Risco, string> = {
  alto: "border-coral/60 bg-coral/10",
  medio: "border-ambar/60 bg-ambar/10",
  baixo: "border-menta/50 bg-menta/10",
  ok: "border-aco/40",
};

export const CATEGORIAS: Record<string, string> = {
  protecao: "Proteção",
  inicializacao: "Inicialização",
  tarefas: "Tarefas agendadas",
  portas: "Portas abertas",
  conexoes: "Conexões",
  processos: "Processos",
  extensoes: "Extensões do navegador",
};

export function quandoCurto(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function tamanho(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
