export type EstadoAssistente = "iniciando" | "inativa" | "ouvindo" | "pensando" | "falando" | "verificando";

export type TipoHolograma =
  | "clima"
  | "noticias"
  | "sistema"
  | "relogio"
  | "globo"
  | "lembretes"
  | "rotinas"
  | "camera"
  | "atividades"
  | "protocolo"
  | "jornal"
  | "tarefas"
  | "plano"
  | "foco"
  | "texto"
  | "imagem";

export interface Holograma {
  id: string;
  tipo: TipoHolograma;
  titulo: string;
  dados: any;
  criado: number;
  atualizado: number;
}

export interface Preferencias {
  nome: string;
  tratamento: string;
  cidade: string;
  cidade_rotulo: string;
  cidade_lat: number | null;
  cidade_lon: number | null;
  bloqueio_facial: boolean;
  exigir_piscada: boolean;
  limiar_rosto: number;
  sessao_minutos: number;
  modo_continuacao: boolean;
  continuacao_segundos: number;
  tema: "sexta" | "jarvis";
  maos_sensibilidade: number;
  voz: string;
  voz_efeito: boolean;
  expediente_inicio: string;
  expediente_fim: string;
  almoco: string;
  foco_minutos: number;
  foco_pausa: number;
  foco_distracoes: string[];
  aviso_reuniao_min: number;
  onboarding_concluido: boolean;
  saudacao_ao_iniciar: boolean;
  atalhos_rapidos: boolean;
}

export interface Lembrete {
  id: number;
  texto: string;
  quando: string;
  descricao: string;
  hora: string;
  repetir: "nao" | "diario" | "dias_uteis" | "semanal";
  alarme: boolean;
}

export interface Rotina {
  nome: string;
  frases: string[];
  horario: string | null;
  dias: number[];
  passos: number;
  criada_pela_ia: boolean;
  acoes: string[];
  ativo?: boolean;
  gatilhos?: string[];
}

export interface LinhaConversa {
  id: number;
  papel: "usuario" | "assistente";
  texto: string;
  canal?: string;
  parcial?: boolean;
  ferramentas?: string[];
  ts: number;
}

export interface InfoRosto {
  cadastrado: boolean;
  modelos: boolean;
  piscada_disponivel: boolean;
  amostras?: number;
  data?: string;
}

export interface Bloqueio {
  bloqueada: boolean;
  motivo: string;
  protecao: boolean;
}

export interface Mao {
  lado: "esquerda" | "direita" | "?";
  conf: number;
  p: [number, number, number][];
}

export interface Aviso {
  id: number;
  texto: string;
  nivel: "info" | "erro" | "lembrete" | "sucesso";
}
