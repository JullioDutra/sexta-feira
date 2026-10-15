// Extensão "sentinela": Protocolo Sentinela (vigia pela câmera com o PC bloqueado), Casa Limpa (só voz) e
// "Onde eu parei?". Hologramas e Ajustes ficam em src/extensoes/sentinela/ e só carregam quando abertos.
import { Suspense, lazy } from "react";
import type { DadosRetomar, DadosSentinela } from "./sentinela/tipos";
import type { Extensao } from "./tipos";

const Holograma = lazy(() => import("./sentinela/Holograma"));
const Retomar = lazy(() => import("./sentinela/Retomar"));
const Ajustes = lazy(() => import("./sentinela/Ajustes"));

const carregando = <p className="text-sm text-aco">Carregando…</p>;

const HologramaSentinela = ({ dados }: { dados: DadosSentinela }) => (
  <Suspense fallback={carregando}>
    <Holograma dados={dados} />
  </Suspense>
);
const HologramaSentinelaCelular = ({ dados }: { dados: DadosSentinela }) => (
  <Suspense fallback={carregando}>
    <Holograma dados={dados} largura={340} />
  </Suspense>
);
const HologramaRetomar = ({ dados }: { dados: DadosRetomar }) => (
  <Suspense fallback={carregando}>
    <Retomar dados={dados} />
  </Suspense>
);
const HologramaRetomarCelular = ({ dados }: { dados: DadosRetomar }) => (
  <Suspense fallback={carregando}>
    <Retomar dados={dados} largura={340} />
  </Suspense>
);
const AjustesSentinela = ({ mudar }: { mudar: (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown> }) => (
  <Suspense fallback={carregando}>
    <Ajustes mudar={mudar} />
  </Suspense>
);

const glifoSentinela = (tamanho: number) => (
  <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3 4.5 6v5.5c0 4.5 3.2 8 7.5 9.5 4.3-1.5 7.5-5 7.5-9.5V6L12 3Z" />
    <path d="M7.5 12s1.8-3 4.5-3 4.5 3 4.5 3-1.8 3-4.5 3-4.5-3-4.5-3Z" />
    <circle cx="12" cy="12" r="1.3" />
  </svg>
);

const glifoRetomar = (tamanho: number) => (
  <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 12a8 8 0 1 0 2.4-5.7" />
    <path d="M4 4v4h4" />
    <path d="M12 8v4l2.5 2" />
  </svg>
);

const extensao: Extensao = {
  hologramas: {
    sentinela: { componente: HologramaSentinela, celular: HologramaSentinelaCelular, glifo: glifoSentinela },
    retomar: { componente: HologramaRetomar, celular: HologramaRetomarCelular, glifo: glifoRetomar },
  },
  doca: [{ tipo: "sentinela", rotulo: "Sentinela" }],
  ajustes: [{ titulo: "Protocolo Sentinela", componente: AjustesSentinela }],
};

export default extensao;
