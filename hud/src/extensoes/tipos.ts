// Contrato das extensões do HUD (Fases 5 e 6). Cada extensão é um arquivo em src/extensoes/
// que exporta por padrão um objeto `Extensao`; o index.ts junta todas.
import type { ComponentType, ReactNode } from "react";

export interface HologramaExtra {
  /** Conteúdo do holograma no HUD do PC (o Palco desenha a moldura, o título e os gestos). */
  componente: ComponentType<{ dados: any }>;
  /** Versão para o celular (se ausente, usa `componente`). */
  celular?: ComponentType<{ dados: any }>;
  /** Ícone (traço, viewBox 24x24, stroke="currentColor") para a barra lateral e o cabeçalho do holograma. */
  glifo?: (tamanho: number) => ReactNode;
}

export interface Extensao {
  /** tipo de holograma -> componente (o tipo precisa existir no backend: HOLOGRAMAS da extensão). */
  hologramas?: Record<string, HologramaExtra>;
  /** Botões extras na barra lateral (abrem o holograma do tipo, como os do núcleo). */
  doca?: { tipo: string; rotulo: string }[];
  /** Eventos do WebSocket (tipo -> função). Use um store próprio (zustand) se precisar de estado. */
  eventos?: Record<string, (evento: any) => void>;
  /** Camadas desenhadas por cima do HUD do PC (ex.: sequência de inicialização). */
  sobreposicoes?: ComponentType[];
  /** Seções extras em Ajustes (o componente recebe a função para salvar preferências). */
  ajustes?: { titulo: string; componente: ComponentType<{ mudar: (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown> }> }[];
  /** Componentes extras na tela do celular (abaixo dos atalhos). */
  celular?: ComponentType[];
  /** Páginas próprias por caminho (ex.: "/overlay" para o overlay de jogo). */
  rotas?: Record<string, ComponentType>;
}
