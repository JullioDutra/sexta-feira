// Extensão "traje": sequência de inicialização, diagnóstico do PC, alertas proativos e overlay de jogo.
// Os componentes ficam em src/extensoes/traje/ e só carregam quando aparecem.
import { Suspense, lazy } from "react";
import { aoInicializar, aoMetricas, useTraje } from "./traje/store";
import type { RelatorioTraje } from "./traje/tipos";
import type { Extensao } from "./tipos";

const Holograma = lazy(() => import("./traje/Holograma"));
const Ajustes = lazy(() => import("./traje/Ajustes"));
const Inicializacao = lazy(() => import("./traje/Inicializacao"));
const Overlay = lazy(() => import("./traje/Overlay"));

const carregando = <p className="text-sm text-aco">Carregando…</p>;

function HologramaTraje({ dados }: { dados: RelatorioTraje }) {
  return (
    <Suspense fallback={carregando}>
      <Holograma dados={dados} />
    </Suspense>
  );
}

function HologramaTrajeCelular({ dados }: { dados: RelatorioTraje }) {
  return (
    <Suspense fallback={carregando}>
      <Holograma dados={dados} largura={340} />
    </Suspense>
  );
}

function AjustesTraje({ mudar }: { mudar: (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown> }) {
  return (
    <Suspense fallback={carregando}>
      <Ajustes mudar={mudar} />
    </Suspense>
  );
}

/** Só baixa o componente da animação quando a sequência começa. */
function SobreposicaoInicializacao() {
  const ativa = useTraje((s) => s.inicializacao !== null);
  if (!ativa) return null;
  return (
    <Suspense fallback={null}>
      <Inicializacao />
    </Suspense>
  );
}

function PaginaOverlay() {
  return (
    <Suspense fallback={null}>
      <Overlay />
    </Suspense>
  );
}

const glifo = (tamanho: number) => (
  <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3c-3.6 0-6.5 2.2-6.5 6v3.2c0 1.6.6 3.1 1.7 4.3L9.5 19h5l2.3-2.5a6.3 6.3 0 0 0 1.7-4.3V9c0-3.8-2.9-6-6.5-6Z" />
    <path d="M8 10.5h3l-1 2.5M16 10.5h-3l1 2.5" />
    <path d="M10 16h4" />
  </svg>
);

const extensao: Extensao = {
  hologramas: { traje: { componente: HologramaTraje, celular: HologramaTrajeCelular, glifo } },
  doca: [{ tipo: "traje", rotulo: "Traje" }],
  eventos: { inicializacao: aoInicializar, "traje.overlay": aoMetricas },
  sobreposicoes: [SobreposicaoInicializacao],
  ajustes: [{ titulo: "Traje", componente: AjustesTraje }],
  rotas: { "/overlay": PaginaOverlay },
};

export default extensao;
