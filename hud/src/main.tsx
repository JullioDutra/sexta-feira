import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { capturarTokenDaUrl } from "./lib/api";
import "./styles.css";

const Desktop = lazy(() => import("./desktop/Desktop"));
const Celular = lazy(() => import("./mobile/Celular"));

capturarTokenDaUrl();

const celular = window.location.pathname.startsWith("/m") || window.matchMedia("(max-width: 760px)").matches;

createRoot(document.getElementById("raiz")!).render(
  <StrictMode>
    <Suspense fallback={null}>{celular ? <Celular /> : <Desktop />}</Suspense>
  </StrictMode>,
);
