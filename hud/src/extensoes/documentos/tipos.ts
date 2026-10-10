// Dados da memória dos documentos (espelham sexta/extensoes/documentos.py).

export interface Fonte {
  id: number;
  arquivo: string;
  pagina: number | null;
  /** Trecho em pedaços: [texto, é termo da pergunta?] */
  trecho: [string, boolean][];
}

export interface ResumoMemoria {
  documentos: number;
  trechos: number;
  pastas: number;
  ultima: string;
  indexando: boolean;
  erro_banco: string;
}

export interface DadosDocumentos {
  pergunta?: string;
  resposta?: string;
  carregando?: boolean;
  fontes?: Fonte[];
  estado?: ResumoMemoria;
}

export interface PastaMemoria {
  caminho: string;
  origem: "ajustes" | "env";
  erro: string;
}

export interface EstadoMemoria {
  pastas: PastaMemoria[];
  documentos: number;
  trechos: number;
  erros: { arquivo: string; caminho: string; erro: string }[];
  total_erros: number;
  ultima: string;
  indexando: boolean;
  lendo: string;
  erro_banco: string;
}

export const numero = (n: number) => n.toLocaleString("pt-BR");
