// Extensão "seguranca": análise estática de arquivos e revisão de segurança do PC.
// Holograma e seção de Ajustes ficam em src/extensoes/seguranca/ e só carregam quando abertos.
import { Suspense, lazy } from "react";
import type { DadosSeguranca } from "./seguranca/tipos";
import type { Extensao } from "./tipos";

const Holograma = lazy(() => import("./seguranca/Holograma"));
const Ajustes = lazy(() => import("./seguranca/Ajustes"));

const carregando = <p className="text-sm text-aco">Carregando…</p>;

function HologramaSeguranca({ dados }: { dados: DadosSeguranca }) {
  return (
    <Suspense fallback={carregando}>
      <Holograma dados={dados} />
    </Suspense>
  );
}

function HologramaSegurancaCelular({ dados }: { dados: DadosSeguranca }) {
  return (
    <Suspense fallback={carregando}>
      <Holograma dados={dados} largura={340} />
    </Suspense>
  );
}

function AjustesSeguranca({ mudar }: { mudar: (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown> }) {
  return (
    <Suspense fallback={carregando}>
      <Ajustes mudar={mudar} />
    </Suspense>
  );
}

const glifo = (tamanho: number) => (
  <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3 4.5 6v5.5c0 4.6 3.1 8.2 7.5 9.5 4.4-1.3 7.5-4.9 7.5-9.5V6L12 3Z" />
    <path d="m8.8 12.2 2.2 2.2 4.3-4.6" />
  </svg>
);

const extensao: Extensao = {
  hologramas: { seguranca: { componente: HologramaSeguranca, celular: HologramaSegurancaCelular, glifo } },
  doca: [{ tipo: "seguranca", rotulo: "Segurança" }],
  ajustes: [{ titulo: "Segurança", componente: AjustesSeguranca }],
};

export default extensao;
