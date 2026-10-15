// Extensão "oficina": oficina holográfica 3D (modelos STL/OBJ/GLB/GLTF/FBX/3MF) e visualizador de música.
// O three.js da oficina e o visualizador ficam em src/extensoes/oficina/ e só carregam quando abertos.
import { Suspense, lazy } from "react";
import { aoComando, aoEspectro, aoEstadoMusica, type DadosOficina, type DadosVisualizador } from "./oficina/tipos";
import type { Extensao } from "./tipos";

const Oficina = lazy(() => import("./oficina/Oficina"));
const Visualizador = lazy(() => import("./oficina/Visualizador"));

const carregando = <p className="text-sm text-aco">Carregando…</p>;

function HologramaOficina({ dados }: { dados: DadosOficina }) {
  return (
    <Suspense fallback={carregando}>
      <Oficina dados={dados} />
    </Suspense>
  );
}

function HologramaOficinaCelular({ dados }: { dados: DadosOficina }) {
  return (
    <Suspense fallback={carregando}>
      <Oficina dados={dados} largura={320} altura={260} />
    </Suspense>
  );
}

function HologramaVisualizador({ dados }: { dados: DadosVisualizador }) {
  return (
    <Suspense fallback={carregando}>
      <Visualizador dados={dados} />
    </Suspense>
  );
}

function HologramaVisualizadorCelular({ dados }: { dados: DadosVisualizador }) {
  return (
    <Suspense fallback={carregando}>
      <Visualizador dados={dados} tamanho={280} />
    </Suspense>
  );
}

const glifoOficina = (tamanho: number) => (
  <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3 4.5 7.2v8.6L12 20l7.5-4.2V7.2Z" />
    <path d="M4.5 7.2 12 11.4l7.5-4.2M12 11.4V20" />
    <path d="M2.5 21.5h19" opacity={0.6} />
  </svg>
);

const glifoVisualizador = (tamanho: number) => (
  <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="2.6" />
    {[0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330].map((a, i) => (
      <line key={a} x1="12" y1={6.2} x2="12" y2={i % 2 ? 4.4 : 2.6} transform={`rotate(${a} 12 12)`} />
    ))}
  </svg>
);

const extensao: Extensao = {
  hologramas: {
    oficina: { componente: HologramaOficina, celular: HologramaOficinaCelular, glifo: glifoOficina },
    visualizador: { componente: HologramaVisualizador, celular: HologramaVisualizadorCelular, glifo: glifoVisualizador },
  },
  doca: [
    { tipo: "oficina", rotulo: "Oficina" },
    { tipo: "visualizador", rotulo: "Visualizador" },
  ],
  eventos: {
    "oficina.comando": aoComando,
    "musica.espectro": aoEspectro,
    "musica.estado": aoEstadoMusica,
  },
};

export default extensao;
