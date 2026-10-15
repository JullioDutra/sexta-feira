// Extensão "agentes": agentes autônomos em segundo plano (holograma ao vivo, Ajustes e cartão no celular).
// Holograma, Ajustes e o cartão do celular ficam em src/extensoes/agentes/ e só carregam quando abertos.
import { Suspense, lazy } from "react";
import { useAgentes, type DadosAgentes } from "./agentes/tipos";
import type { Extensao } from "./tipos";

const Holograma = lazy(() => import("./agentes/Holograma"));
const Ajustes = lazy(() => import("./agentes/Ajustes"));
const Celular = lazy(() => import("./agentes/Celular"));

const carregando = <p className="text-sm text-aco">Carregando…</p>;

function HologramaAgentes({ dados }: { dados: DadosAgentes }) {
  return (
    <Suspense fallback={carregando}>
      <Holograma dados={dados} />
    </Suspense>
  );
}

function HologramaAgentesCelular({ dados }: { dados: DadosAgentes }) {
  return (
    <Suspense fallback={carregando}>
      <Holograma dados={dados} largura={340} />
    </Suspense>
  );
}

function AjustesAgentes({ mudar }: { mudar: (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown> }) {
  return (
    <Suspense fallback={carregando}>
      <Ajustes mudar={mudar} />
    </Suspense>
  );
}

function AgentesNoCelular() {
  return (
    <Suspense fallback={null}>
      <Celular />
    </Suspense>
  );
}

const glifo = (tamanho: number) => (
  <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="6" y="8" width="12" height="10" rx="2.5" />
    <path d="M12 8V5M10.5 4.5h3M9.5 12.5h.01M14.5 12.5h.01M10 15.5h4M6 13H3.5M18 13h2.5" />
  </svg>
);

const extensao: Extensao = {
  hologramas: { agentes: { componente: HologramaAgentes, celular: HologramaAgentesCelular, glifo } },
  doca: [{ tipo: "agentes", rotulo: "Agentes" }],
  eventos: { agentes: (e) => useAgentes.getState().definir(e) },
  ajustes: [{ titulo: "Agentes", componente: AjustesAgentes }],
  celular: [AgentesNoCelular],
};

export default extensao;
