// Extensão "documentos": memória dos documentos (perguntas respondidas com os seus arquivos).
// Holograma e seção de Ajustes ficam em src/extensoes/documentos/ e só carregam quando abertos.
import { Suspense, lazy } from "react";
import type { DadosDocumentos } from "./documentos/tipos";
import type { Extensao } from "./tipos";

const Holograma = lazy(() => import("./documentos/Holograma"));
const Ajustes = lazy(() => import("./documentos/Ajustes"));

const carregando = <p className="text-sm text-aco">Carregando…</p>;

function HologramaDocumentos({ dados }: { dados: DadosDocumentos }) {
  return (
    <Suspense fallback={carregando}>
      <Holograma dados={dados} />
    </Suspense>
  );
}

function HologramaDocumentosCelular({ dados }: { dados: DadosDocumentos }) {
  return (
    <Suspense fallback={carregando}>
      <Holograma dados={dados} largura={340} />
    </Suspense>
  );
}

function AjustesDocumentos() {
  return (
    <Suspense fallback={carregando}>
      <Ajustes />
    </Suspense>
  );
}

const glifo = (tamanho: number) => (
  <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M13 20.5H5.5v-17h8L18 8v4" />
    <path d="M13.5 3.5V8H18M8.5 11.5h6M8.5 15h3" />
    <circle cx="16.5" cy="16.5" r="2.8" />
    <path d="m18.6 18.6 2.4 2.4" />
  </svg>
);

const extensao: Extensao = {
  hologramas: { documentos: { componente: HologramaDocumentos, celular: HologramaDocumentosCelular, glifo } },
  doca: [{ tipo: "documentos", rotulo: "Documentos" }],
  ajustes: [{ titulo: "Memória dos documentos", componente: AjustesDocumentos }],
};

export default extensao;
