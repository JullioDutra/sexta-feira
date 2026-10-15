// Extensão "video": holograma Vídeos (trabalhos com progresso e arquivos gerados), botão na doca e Ajustes.
// Os componentes ficam em src/extensoes/video/ e só carregam quando abertos.
import { Suspense, lazy } from "react";
import type { Extensao } from "./tipos";
import { aoTrabalhos, type DadosVideos } from "./video/tipos";

const Holograma = lazy(() => import("./video/Holograma"));
const Ajustes = lazy(() => import("./video/Ajustes"));

const carregando = <p className="text-sm text-aco">Carregando…</p>;

function HologramaVideos({ dados }: { dados: DadosVideos }) {
  return (
    <Suspense fallback={carregando}>
      <Holograma dados={dados} />
    </Suspense>
  );
}

function HologramaVideosCelular({ dados }: { dados: DadosVideos }) {
  return (
    <Suspense fallback={carregando}>
      <Holograma dados={dados} largura={340} />
    </Suspense>
  );
}

function AjustesVideos(props: { mudar: (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown> }) {
  return (
    <Suspense fallback={carregando}>
      <Ajustes {...props} />
    </Suspense>
  );
}

const glifo = (tamanho: number) => (
  <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="5.5" width="13" height="13" rx="1.5" />
    <path d="m16 10 5-3v10l-5-3" />
    <path d="M8 9.5v5l4-2.5z" />
  </svg>
);

const extensao: Extensao = {
  hologramas: { videos: { componente: HologramaVideos, celular: HologramaVideosCelular, glifo } },
  doca: [{ tipo: "videos", rotulo: "Vídeos" }],
  eventos: { "video.trabalhos": aoTrabalhos },
  ajustes: [{ titulo: "Vídeos", componente: AjustesVideos }],
};

export default extensao;
