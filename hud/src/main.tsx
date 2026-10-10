import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { capturarTokenDaUrl } from "./lib/api";
import "./styles.css";

const Desktop = lazy(() => import("./desktop/Desktop"));
const Celular = lazy(() => import("./mobile/Celular"));
// páginas das extensões (src/extensoes, campo `rotas`), ex.: /overlay
const PaginaExtra = lazy(() => import("./extensoes").then((m) => ({ default: m.ROTAS[window.location.pathname] ?? (() => <p>Página não encontrada.</p>) })));

capturarTokenDaUrl();

const caminho = window.location.pathname;
const celular = caminho.startsWith("/m") || window.matchMedia("(max-width: 760px)").matches;
const extra = caminho !== "/" && !caminho.startsWith("/m") && !caminho.endsWith(".html");

createRoot(document.getElementById("raiz")!).render(
  <StrictMode>
    <Suspense fallback={null}>{extra ? <PaginaExtra /> : celular ? <Celular /> : <Desktop />}</Suspense>
  </StrictMode>,
);
