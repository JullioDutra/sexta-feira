// Junta as extensões do HUD e registra os eventos delas no store.
import { aoEvento } from "../lib/store";
import agentes from "./agentes";
import aprendizado from "./aprendizado";
import comunicacao from "./comunicacao";
import documentos from "./documentos";
import maosLivres from "./maosLivres";
import oficina from "./oficina";
import seguranca from "./seguranca";
import sentinela from "./sentinela";
import tarefasAprendidas from "./tarefasAprendidas";
import traje from "./traje";
import video from "./video";
import type { Extensao, HologramaExtra } from "./tipos";

export const EXTENSOES: Extensao[] = [traje, oficina, sentinela, comunicacao, maosLivres, documentos, aprendizado, video, agentes, seguranca, tarefasAprendidas];

for (const ext of EXTENSOES) {
  for (const [tipo, funcao] of Object.entries(ext.eventos ?? {})) aoEvento(tipo, funcao);
}

export function hologramaExtra(tipo: string): HologramaExtra | undefined {
  for (const ext of EXTENSOES) if (ext.hologramas?.[tipo]) return ext.hologramas[tipo];
  return undefined;
}

export const DOCA_EXTRA = EXTENSOES.flatMap((e) => e.doca ?? []);
export const SOBREPOSICOES = EXTENSOES.flatMap((e) => e.sobreposicoes ?? []);
export const AJUSTES_EXTRA = EXTENSOES.flatMap((e) => e.ajustes ?? []);
export const CELULAR_EXTRA = EXTENSOES.flatMap((e) => e.celular ?? []);
export const ROTAS = Object.assign({}, ...EXTENSOES.map((e) => e.rotas ?? {})) as Record<string, React.ComponentType>;
