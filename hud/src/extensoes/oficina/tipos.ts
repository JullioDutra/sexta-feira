// Dados da oficina 3D e do visualizador de música (espelham sexta/extensoes/oficina.py).
import { create } from "zustand";

export type Formato = "stl" | "obj" | "glb" | "gltf" | "fbx" | "3mf";

export interface DadosOficina {
  id?: string;
  nome?: string;
  formato?: Formato;
  url?: string;
  tamanho?: string;
  bytes?: number;
}

export interface DadosVisualizador {
  ativo?: boolean;
  motivo?: string;
}

export type AcaoOficina = "explodir" | "juntar" | "girar" | "parar";

/** Comandos de voz para o visualizador aberto (evento "oficina.comando" vira evento da janela). */
export const EVENTO_COMANDO = "sexta:oficina.comando";

export function aoComando(evento: { acao: AcaoOficina; id?: string }) {
  window.dispatchEvent(new CustomEvent(EVENTO_COMANDO, { detail: { acao: evento.acao, id: evento.id } }));
}

/** Espectro ao vivo: muda 25 vezes por segundo, fica fora do React (lido no requestAnimationFrame). */
export const espectro = {
  bandas: new Float32Array(32),
  nivel: 0,
  grave: 0,
  em: 0,
};

export function aoEspectro(evento: { bandas?: number[]; nivel?: number; grave?: number }) {
  const bandas = evento.bandas ?? [];
  if (espectro.bandas.length !== bandas.length && bandas.length) espectro.bandas = new Float32Array(bandas.length);
  for (let i = 0; i < bandas.length; i++) espectro.bandas[i] = bandas[i];
  espectro.nivel = evento.nivel ?? 0;
  espectro.grave = evento.grave ?? 0;
  espectro.em = performance.now();
}

/** Estado da captura ("musica.estado"): ativo ou o motivo de não captar. */
export const useMusica = create<{ estado: DadosVisualizador | null }>()(() => ({ estado: null }));

export function aoEstadoMusica(evento: DadosVisualizador) {
  useMusica.setState({ estado: { ativo: !!evento.ativo, motivo: evento.motivo ?? "" } });
}

/** Cor da luz do tema (var(--luz)). */
export function corDaLuz(): string {
  return getComputedStyle(document.documentElement).getPropertyValue("--luz").trim() || "#ffb547";
}
